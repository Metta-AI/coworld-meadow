import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from coworld.examples.meadow.player.policies import LlmPolicy


def test_native_player_prefers_sidecar_without_aws_credentials(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers.get("X-Coworld-Player-Slot"), body))
            reply = json.dumps({"content": [{"type": "text", "text": "ok"}],
                                "usage": {"input_tokens": 3, "output_tokens": 1}}).encode()
            self.send_response(200)
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
    monkeypatch.setenv("COWORLD_LLM_MODEL", "anthropic/claude-sonnet-4.6")
    monkeypatch.setenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", "http://retired.invalid")
    try:
        policy = LlmPolicy(model="retired-local-model")
        policy._system_prompt = "rules"
        assert policy.backend == "sidecar"
        assert policy._complete("action", slot=1) == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert len(requests) == 1
    path, slot, body = requests[0]
    assert path == "/v1/messages"
    assert slot == "1"
    assert body["model"] == "anthropic/claude-sonnet-4.6"
    assert "anthropic_version" not in body
    assert body["system"] == "rules"
    assert body["messages"] == [{"role": "user", "content": "action"}]
