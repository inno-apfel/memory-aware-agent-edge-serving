"""Local deterministic HTTP fixture, never a model-performance benchmark."""

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def answer(messages):
    prompt = messages[-1]["content"]
    if "latest tool result" in prompt:
        return next(
            m["content"].split(": ")[1]
            for m in reversed(messages)
            if m["content"].startswith("Tool result:")
        )
    match = re.search(r"integer sum of (\d+) and (\d+)", prompt)
    if match:
        return str(int(match[1]) + int(match[2]))
    return ("FIFO processes ready requests in their arrival order. " * 25) + "END"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"mock-only")

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = body["messages"][-1]["content"]
        if prompt == "HTTP_ERROR":
            self.send_response(500)
            self.end_headers()
            return
        if prompt == "TIMEOUT":
            time.sleep(0.2)
        text = answer(body["messages"])
        time.sleep(0.025 if body["max_tokens"] < 512 else 0.08)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            event = {"choices": [{"delta": {"content": text}, "finish_reason": None}]}
            self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
            self.wfile.flush()
            if prompt == "INCOMPLETE":
                return
            event = {"choices": [{"delta": {}, "finish_reason": "stop"}]}
            self.wfile.write(
                ("data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n").encode()
            )
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--ready-file", required=True)
    a = p.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    from pathlib import Path

    Path(a.ready_file).write_text(str(server.server_port))
    server.serve_forever()


if __name__ == "__main__":
    main()
