"""Complete a game with published bare-action clients and native action envelopes."""
import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import websockets

from coworld.examples.meadow.game.engine import MeadowConfig, parse_action
from coworld.examples.meadow.shared.decision import PlayerDecision
from coworld.examples.meadow.shared.trajectory import Attempt


async def main():
    root = Path(__file__).resolve().parents[1]
    output = Path(sys.argv[1]).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config = {"tokens": [str(i) for i in range(8)], "players": [{"name": f"seat-{i}"} for i in range(8)],
              "rounds": 60, "round_seconds": 20, "player_connect_timeout_seconds": 10}
    (output / "config.json").write_text(json.dumps(config))
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "COGAME_HOST": "127.0.0.1", "COGAME_PORT": str(port),
           "COGAME_CONFIG_URI": (output / "config.json").as_uri(), "COGAME_RESULTS_URI": (output / "results.json").as_uri(),
           "COGAME_SAVE_REPLAY_URI": (output / "replay.json").as_uri(),
           "COGAME_SAVE_TRAJECTORY_URI": (output / "trajectory.jsonl").as_uri(),
           "COWORLD_EPISODE_ID": "published-actions", "COWORLD_GAME_VERSION": "fixture",
           "COWORLD_SOURCE_REVISION": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
           "COWORLD_MEADOW_POST_GAME_LINGER_SECONDS": "0", "COWORLD_MEADOW_POST_GAME_MAX_LINGER_SECONDS": "0"}
    with (output / "game.log").open("w") as log:
        game = await asyncio.create_subprocess_exec(sys.executable, "-m", "coworld.examples.meadow.game.server",
                                                   cwd=root, env=env, stdout=log, stderr=log)
        try:
            async with asyncio.timeout(30):
                while "Application startup complete" not in (output / "game.log").read_text():
                    assert game.returncode is None
                    await asyncio.sleep(0.02)
                async def play(seat):
                    async with websockets.connect(f"ws://127.0.0.1:{port}/player?slot={seat}&token={seat}") as ws:
                        async for raw in ws:
                            view = json.loads(raw)
                            if view["type"] == "final":
                                return
                            action = {"harvest": 1, "message": "x" * 139 + " " + "beyond limit"}
                            if seat < 4:
                                packet = action
                            else:
                                attempt = Attempt(policy="public-contract", origin="unknown", prompt=None,
                                                  response=json.dumps(action))
                                packet = PlayerDecision(round=view["round"],
                                    action=parse_action(action, seat, MeadowConfig(num_players=8)),
                                    attempts=[attempt], selected_attempt_id=attempt.attempt_id).model_dump()
                            await ws.send(json.dumps(packet))
                await asyncio.gather(*(play(seat) for seat in range(8)))
                assert await game.wait() == 0
            results = json.loads((output / "results.json").read_text())
            assert results["scores"] == [60.0] * 8, results
            events = [json.loads(line) for line in (output / "trajectory.jsonl").read_text().splitlines()]
            decisions = [event for event in events if event["event_type"] == "decision"]
            assert len(decisions) == 480
            assert all(d["executed_action"]["message"] == "x" * 139 for d in decisions)
            assert all(a["origin"] == "unknown" for d in decisions for a in d["attempts"])
            assert (output / "replay.json").is_file()
            print("480 decisions completed; bare and enveloped actions score equally, provenance remains unknown")
        finally:
            if game.returncode is None:
                game.terminate()
            await game.wait()


if __name__ == "__main__":
    asyncio.run(main())
