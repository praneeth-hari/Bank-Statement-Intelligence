"""A stand-in Ollama server for tests: real HTTP on localhost, scripted answers.

The client under test makes real requests to it, so URL building, JSON bodies, error handling and timeouts are
exercised exactly as they would be against ``ollama serve``. Only the model is fake.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeOllama:
    def __init__(self, responder=None, models=("qwen2.5:3b",), chat_status=200, raw_reply=None):
        self.responder = responder or (lambda system, user, schema: {"items": []})
        self.models = list(models)
        self.chat_status = chat_status
        self.raw_reply = raw_reply  # send this string as the message content instead of the responder's JSON
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # keep test output clean
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._send(200, {"models": [{"name": m} for m in outer.models]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n))
                outer.requests.append(body)
                if self.path != "/api/chat":
                    return self._send(404, {"error": "not found"})
                if outer.chat_status != 200:
                    return self._send(outer.chat_status, {"error": "model failed to load"})
                system, user = body["messages"][0]["content"], body["messages"][1]["content"]
                content = outer.raw_reply if outer.raw_reply is not None else json.dumps(
                    outer.responder(system, user, body["format"]))
                self._send(200, {"message": {"role": "assistant", "content": content}, "done": True})

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def host(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
