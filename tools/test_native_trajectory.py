"""Exercise actual native HTTP, player process, authenticated socket, and engine episodes."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

revision, output = sys.argv[1:]
ROOT = Path(__file__).resolve().parents[1]
root = Path(output).resolve()
os.umask(0o077)
root.mkdir(mode=0o700)
reports = []

for mode in ["accepted", "greedy", "invalid", "throttled", "deadline"]:
    folder = root / mode
    folder.mkdir(mode=0o700)
    archives = {}

    class Native(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            call_id = str(uuid4())
            raw = '{"harvest":1,"message":"public speech"}' if mode != "invalid" else "PRIVATE INVALID REPLY"
            response = {"id": call_id, "model": "fixture/served", "content": [{"type": "text", "text": raw}],
                "stop_reason": "end_turn", "usage": {"input_tokens": 100, "output_tokens": 10}}
            if mode == "greedy":
                response["sampling_evidence"] = {"prompt_token_ids": [1], "completion_token_ids": [2],
                    "behavior_log_probs": None, "stop_reason": "eos"}
            status = 429 if mode == "throttled" else 200
            if status != 200:
                response = {"error": "PRIVATE THROTTLE SENTINEL"}
            text = json.dumps(response)
            archives[call_id] = {"request": body, "response": response, "response_text": text,
                "seat": self.headers["X-Coworld-Player-Slot"], "http_status": status}
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Softmax-Llm-Call-Id", call_id)
            self.send_header("X-Coworld-Checkpoint-Sha256", "a" * 64)
            if mode == "deadline":
                self.send_header("Content-Length", str(len(text.encode())))
                self.end_headers()
                time.sleep(2.5)
                return
            payload = text.encode()
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    native = ThreadingHTTPServer(("127.0.0.1", 0), Native)
    threading.Thread(target=native.serve_forever, daemon=True).start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config = {"seed": 17, "rounds": 2, "round_seconds": 2, "ledger_public": False,
        "stock_start": 60, "tokens": ["zero", "one"], "players": [{"name": "one"}, {"name": "two"}],
        "player_connect_timeout_seconds": 10}
    config_path = folder / "config.json"
    config_path.write_text(json.dumps(config))
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "COGAME_HOST": "127.0.0.1", "COGAME_PORT": str(port),
        "COGAME_CONFIG_URI": config_path.as_uri(), "COGAME_RESULTS_URI": (folder / "results.json").as_uri(),
        "COGAME_SAVE_REPLAY_URI": (folder / "replay.json").as_uri(), "COGAME_SAVE_TRAJECTORY_URI": (folder / "trajectory.jsonl").as_uri(),
        "COWORLD_EPISODE_ID": "native-" + mode, "COWORLD_GAME_VERSION": "source-" + revision, "COWORLD_SOURCE_REVISION": revision,
        "COWORLD_MEADOW_POST_GAME_LINGER_SECONDS": "0", "COWORLD_MEADOW_POST_GAME_MAX_LINGER_SECONDS": "1",
        "COWORLD_LLM_ENDPOINT": f"http://127.0.0.1:{native.server_port}", "COWORLD_LLM_MODEL": "fixture/requested",
        "COWORLD_LLM_TEMPERATURE": "0", "COWORLD_MEADOW_PROMPT": "PRIVATE OPERATOR SENTINEL"}
    players = []
    logs = []
    with (folder / "game.log").open("w") as game_log:
        game = subprocess.Popen([sys.executable, "-m", "coworld.examples.meadow.game.server"], cwd=ROOT,
            env=env, stdout=game_log, stderr=game_log)
        try:
            deadline = time.monotonic() + 20
            while True:
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", port)) == 0:
                        break
                assert game.poll() is None, (folder / "game.log").read_text()
                assert time.monotonic() < deadline
                threading.Event().wait(0.01)
            for slot, token in enumerate(config["tokens"]):
                log = (folder / f"player-{slot}.log").open("w")
                logs.append(log)
                players.append(subprocess.Popen([sys.executable, "-m", "coworld.examples.meadow.player.player", "llm"],
                    cwd=ROOT, env={**env, "COWORLD_PLAYER_WS_URL": f"ws://127.0.0.1:{port}/player?slot={slot}&token={token}"}, stdout=log, stderr=log))
            assert game.wait(timeout=30) == 0, (folder / "game.log").read_text()
            for slot, player in enumerate(players):
                assert player.wait(timeout=5) == 0, (folder / f"player-{slot}.log").read_text()
        finally:
            for process in [game, *players]:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
            for log in logs: log.close()
            native.shutdown()
            native.server_close()
    events = [json.loads(line) for line in (folder / "trajectory.jsonl").read_text().splitlines()]
    assert events[-1]["status"] == "completed" and events[-1]["outcome"]["rounds"] == 2
    decisions = events[:-1]
    assert len(decisions) == 4
    seen = set()
    for decision in decisions:
        for attempt in decision["attempts"]:
            if attempt["platform_call_id"] is None:
                continue
            seen.add(attempt["platform_call_id"])
            archive = archives[attempt["platform_call_id"]]
            assert attempt["request"] == archive["request"] and decision["seat"] == archive["seat"]
            if mode != "deadline":
                assert attempt["raw_response"] in [archive["response"], archive["response_text"]]
            assert attempt["latency_ms"] is not None
        if mode in {"accepted", "greedy"}:
            assert decision["action_status"] == "accepted"
            chosen = next(attempt for attempt in decision["attempts"] if attempt["attempt_id"] == decision["selected_attempt_id"])
            assert chosen["accepted"] and chosen["parsed_action"] == decision["executed_action"]
            assert chosen["model"] == "fixture/served"
        else:
            assert decision["action_status"] == "fallback" and decision["selected_attempt_id"] is None
            assert all(not attempt["accepted"] for attempt in decision["attempts"])
    assert seen == set(archives), (seen, set(archives))
    public = (folder / "replay.json").read_text() + (folder / "game.log").read_text()
    assert "PRIVATE" not in public
    assert (folder / "trajectory.jsonl").stat().st_mode & 0o777 == 0o600
    (folder / "native-call-archives.json").write_text(json.dumps(archives))
    reports.append({"mode": mode, "decisions": 4, "native_call_joins": len(archives), "source_revision": revision,
        "cohort": "local native HTTP/player/socket fixture; no hosted platform claim"})
(root / "report.json").write_text(json.dumps(reports, indent=2) + "\n")
print(json.dumps(reports))
