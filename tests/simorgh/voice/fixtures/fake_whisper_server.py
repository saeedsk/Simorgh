"""A stand-in for whisper-server: answers POST /inference with a fixed
transcript after the multipart body is read. Args mimic the real one
(`-m`, `--host`, `--port`, `-nt`)."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a) -> None:  # quiet
        pass

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        text = " Hello there. [BLANK_AUDIO]" if b"turn.wav" in body else " no file"
        if b"name=\"language\"\r\n\r\nfa" in body:
            text = " salam"
        reply = json.dumps({"text": text}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)


def main() -> None:
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1]) if "--port" in args else 8080
    if "--die" in args:
        return
    HTTPServer(("127.0.0.1", port), _Handler).serve_forever()


if __name__ == "__main__":
    main()
