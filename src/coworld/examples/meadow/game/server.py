"""Meadow game server.

Wraps the pure engine in the Coworld game-container contract (see
`docs/roles/GAME.md`): config via `COGAME_CONFIG_URI`, results and replay
written to runner URIs, `/healthz`, browser clients, and the `/player`,
`/global`, `/admin`, `/replay` websocket routes.

Unlike Paint Arena's fixed-rate ticks, Meadow advances on a round barrier: a
round settles as soon as every connected player has submitted an action, or
when `round_seconds` elapses — whichever comes first. Missing or disconnected
players pass (harvest 0), so a slow seat bounds the round, never the episode.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

from coworld.examples.meadow.game.engine import (
    MeadowConfig,
    MeadowState,
    RoundAction,
    new_state,
    observation,
    parse_action,
    step,
    welfare,
)
from coworld.examples.meadow.shared.artifact_io import (
    artifact_method,
    load_replay_data,
    read_data,
    write_data,
)
from coworld.examples.meadow.shared.log_shipper import get_logger

CLIENT_DIR = Path(__file__).parent / "client"
logger = get_logger("meadow.game")
GAME_HOST = os.environ.get("COGAME_HOST", "0.0.0.0")
GAME_PORT = int(os.environ.get("COGAME_PORT", "8080"))

REPLAY_MODE = "COGAME_LOAD_REPLAY_URI" in os.environ
if REPLAY_MODE:
    REPLAY_LOAD_URI = os.environ["COGAME_LOAD_REPLAY_URI"]
    RAW_CONFIG: dict[str, Any] = {"tokens": ["replay", "replay"], "players": [{"name": "replay"}] * 2}
    RESULTS_URI = ""
    REPLAY_URI = ""
else:
    REPLAY_LOAD_URI = ""
    RAW_CONFIG = json.loads(read_data(os.environ["COGAME_CONFIG_URI"]))
    RESULTS_URI = os.environ["COGAME_RESULTS_URI"]
    REPLAY_URI = os.environ["COGAME_SAVE_REPLAY_URI"]

TOKENS: list[str] = RAW_CONFIG["tokens"]
PLAYER_NAMES: list[str] = [player["name"] for player in RAW_CONFIG["players"]]
CONFIG = MeadowConfig.model_validate({**RAW_CONFIG, "num_players": len(TOKENS)})
ROUND_SECONDS = float(RAW_CONFIG.get("round_seconds", 20.0))
PLAYER_CONNECT_TIMEOUT_SECONDS = float(RAW_CONFIG.get("player_connect_timeout_seconds", 180))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    timeout_task = asyncio.create_task(_start_after_player_connect_timeout()) if TOKENS and not REPLAY_MODE else None
    yield
    if timeout_task is not None:
        timeout_task.cancel()
        with suppress(asyncio.CancelledError):
            await timeout_task


app = FastAPI(lifespan=lifespan)
server: uvicorn.Server


class GameSession:
    def __init__(self) -> None:
        self.engine: MeadowState = new_state(CONFIG)
        self.players: dict[int, WebSocket] = {}
        self.pending: dict[int, RoundAction] = {}
        self.frames: list[dict[str, Any]] = []
        self.started = False
        self.done = False
        self.paused = False
        self.round_seconds = ROUND_SECONDS


session = GameSession()


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/client/global")
def global_client() -> HTMLResponse:
    return HTMLResponse((CLIENT_DIR / "global.html").read_text())


@app.get("/client/admin")
def admin_client() -> HTMLResponse:
    return HTMLResponse((CLIENT_DIR / "admin.html").read_text())


@app.get("/client/replay")
def replay_client() -> HTMLResponse:
    return HTMLResponse((CLIENT_DIR / "replay.html").read_text())


@app.get("/client/player")
def player_client() -> HTMLResponse:
    return HTMLResponse((CLIENT_DIR / "player.html").read_text())


@app.websocket("/global")
async def global_viewer(websocket: WebSocket) -> None:
    await websocket.accept()
    sender = asyncio.create_task(_send_global_snapshots(websocket))
    receiver = asyncio.create_task(_drain_messages(websocket))
    done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        task.result()


async def _send_global_snapshots(websocket: WebSocket) -> None:
    await websocket.send_json(_snapshot())
    while not session.done:
        await asyncio.sleep(0.5)
        await websocket.send_json(_snapshot())
    await websocket.send_json(_snapshot())


async def _drain_messages(websocket: WebSocket) -> None:
    async for _ in websocket.iter_json():
        pass


@app.websocket("/admin")
async def admin(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json(_snapshot())
    async for command in websocket.iter_json():
        if command["command"] == "pause":
            session.paused = True
        elif command["command"] == "resume":
            session.paused = False
        elif command["command"] == "round_seconds":
            session.round_seconds = float(command["round_seconds"])
        await websocket.send_json(_snapshot())


@app.websocket("/replay")
async def replay_viewer(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "replay", **load_replay_data(REPLAY_LOAD_URI)})
    async for command in websocket.iter_json():
        await websocket.send_json({"type": "control", "command": command})


@app.websocket("/player")
async def player(websocket: WebSocket) -> None:
    slot = int(websocket.query_params["slot"])
    token = websocket.query_params["token"]
    if slot < 0 or slot >= len(TOKENS) or TOKENS[slot] != token:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    session.players[slot] = websocket
    logger.info("player slot %d connected (%d/%d)", slot, len(session.players), len(TOKENS))
    await websocket.send_json(_player_observation(slot))
    if len(session.players) == len(TOKENS) and not session.started:
        session.started = True
        logger.info("all players connected, starting game")
        asyncio.create_task(_play_game())

    try:
        async for message in websocket.iter_json():
            if not session.done and session.engine.round < CONFIG.rounds:
                session.pending[slot] = parse_action(message, slot, CONFIG)
    finally:
        if session.players.get(slot) is websocket:
            del session.players[slot]


async def _start_after_player_connect_timeout() -> None:
    await asyncio.sleep(PLAYER_CONNECT_TIMEOUT_SECONDS)
    if not session.started and not session.done:
        session.started = True
        logger.info("player connect timeout elapsed, starting game")
        asyncio.create_task(_play_game())


async def _play_game() -> None:
    loop = asyncio.get_running_loop()
    await asyncio.sleep(0.5)
    while session.engine.round < CONFIG.rounds:
        if session.paused:
            await asyncio.sleep(0.1)
            continue
        deadline = loop.time() + session.round_seconds
        while loop.time() < deadline:
            connected = set(session.players)
            if connected and connected.issubset(session.pending.keys()):
                break
            await asyncio.sleep(0.05)

        actions = [session.pending.get(slot, RoundAction()) for slot in range(CONFIG.num_players)]
        session.pending.clear()
        record = step(session.engine, actions, CONFIG)
        session.frames.append({**record.model_dump(), "player_names": PLAYER_NAMES})
        await _broadcast_observations()

    results = _results()
    logger.info("game finished after %d rounds, scores=%s", session.engine.round, results["scores"])
    write_data(
        RESULTS_URI,
        json.dumps(results),
        content_type="application/json",
        http_method=artifact_method("COGAME_RESULTS_METHOD"),
    )
    write_data(
        REPLAY_URI,
        json.dumps(_replay_payload(results)),
        content_type="application/json",
        http_method=artifact_method("COGAME_SAVE_REPLAY_METHOD"),
    )

    session.done = True
    server.should_exit = True
    for slot, websocket in session.players.items():
        await websocket.send_json({**_player_observation(slot), "type": "final", "done": True})
    await asyncio.sleep(0.5)


async def _broadcast_observations() -> None:
    for slot, websocket in session.players.items():
        await websocket.send_json(_player_observation(slot))


def _player_observation(slot: int) -> dict[str, Any]:
    return observation(session.engine, CONFIG, slot, PLAYER_NAMES, session.round_seconds)


def _results() -> dict[str, object]:
    engine = session.engine
    return {
        "scores": [round(score, 3) for score in engine.scores],
        "total_harvested": [round(total, 3) for total in engine.total_harvested],
        "welfare": round(welfare(engine), 3),
        "final_stock": round(engine.stock, 3),
        "collapse_round": engine.collapse_round,
        "rounds": engine.round,
    }


def _replay_payload(results: dict[str, object]) -> dict[str, Any]:
    return {
        "config": {key: value for key, value in RAW_CONFIG.items() if key != "tokens"},
        "player_names": PLAYER_NAMES.copy(),
        "frames": session.frames,
        "results": results,
    }


def _snapshot() -> dict[str, Any]:
    engine = session.engine
    last = engine.history[-1] if engine.history else None
    return {
        "type": "state",
        "round": engine.round,
        "rounds": CONFIG.rounds,
        "stock": round(engine.stock, 2),
        "stock_capacity": CONFIG.stock_capacity,
        "collapse_threshold": CONFIG.collapse_threshold,
        "collapsed": engine.collapsed,
        "collapse_round": engine.collapse_round,
        "scores": [round(score, 2) for score in engine.scores],
        "total_harvested": [round(total, 2) for total in engine.total_harvested],
        "player_names": PLAYER_NAMES.copy(),
        "last_round": last.model_dump() if last else None,
        "connected": sorted(session.players),
        "submitted": sorted(session.pending),
        "started": session.started,
        "paused": session.paused,
        "round_seconds": session.round_seconds,
        "done": session.done,
    }


if __name__ == "__main__":
    server = uvicorn.Server(uvicorn.Config(app, host=GAME_HOST, port=GAME_PORT))
    server.run()
