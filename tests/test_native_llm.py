import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4

from coworld.examples.meadow.game.engine import MeadowConfig, new_state, observation
from coworld.examples.meadow.player.policies import LlmPolicy, system_prompt
from coworld.examples.meadow.shared.decision import apply_player_decision


def test_native_player_captures_actual_request_response_and_applied_action(monkeypatch):
    requests = []
    call_id = str(uuid4())
    response = {"model": "fixture/served", "content": [{"type": "text", "text": '{"harvest":2}'}],
        "stop_reason": "end_turn", "usage": {"input_tokens": 3, "output_tokens": 1},
        "sampling_evidence": {"prompt_token_ids": [1], "completion_token_ids": [2],
            "behavior_log_probs": None, "stop_reason": "eos"}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers["X-Coworld-Player-Slot"], body))
            reply = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("X-Softmax-Llm-Call-Id", call_id)
            self.send_header("X-Coworld-Checkpoint-Sha256", "a" * 64)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("COWORLD_LLM_ENDPOINT", f"http://127.0.0.1:{server.server_port}/")
    monkeypatch.setenv("COWORLD_LLM_MODEL", "fixture/requested")
    monkeypatch.setenv("COWORLD_LLM_TEMPERATURE", "0")
    config = MeadowConfig(num_players=2)
    view = observation(new_state(config), config, 1, ["one", "two"], 5)
    try:
        decision = LlmPolicy(strategy="PRIVATE OPERATOR SENTINEL").act(view)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert len(requests) == 1
    path, slot, body = requests[0]
    assert path == "/v1/messages" and slot == "1"
    assert body["model"] == "fixture/requested" and body["temperature"] == 0
    assert body["system"] == system_prompt(view, "PRIVATE OPERATOR SENTINEL")
    attempt = decision.attempts[0]
    assert attempt.request == body and attempt.raw_response == response
    assert str(attempt.platform_call_id) == call_id and attempt.model == "fixture/served"
    assert attempt.model_identity == "a" * 64
    assert attempt.prompt_token_ids == [1] and attempt.sampled_token_ids == [2]
    assert attempt.behavior_logprobs is None
    applied = apply_player_decision(decision, 1, config)
    assert applied.action.harvest == 2 and applied.attempts[0].parsed_action == applied.action.model_dump()
