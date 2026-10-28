#!/usr/bin/env python3
# Copyright (c) 2026 vertciti. All rights reserved.
# Test double for the anomalies runtime product surface (M1: HTTP only), used
# by ci/check-e2e.sh. Behaviour is chosen by the message text:
#   "inline ..." -> immediate reply, no run
#   "slow ..."   -> a run that streams one word every 1.5 s (for stop/offline tests)
#   "fail ..."   -> HTTP 503 (runtime down)
#   anything else -> a run that streams a short reply quickly
"""Mock anomalies runtime for end-to-end tests."""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

RUNS: dict[str, float] = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def _json(self, code: int, obj: object) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        u = urlparse(self.path)
        if u.path == "/api/v1/health":
            return self._json(200, {"status": "ok"})
        if u.path == "/api/v1/chat/stream":
            run_id = parse_qs(u.query).get("run_id", [""])[0]
            delay = RUNS.get(run_id, 0.05)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for word in ("Mock ", "runtime ", "reply ", "<b>not bold</b> ", "done."):
                    self.wfile.write(f"data: {json.dumps({'text': word})}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(delay)
                self.wfile.write(b"event: done\ndata: {}\n\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
            return None
        return self._json(404, {})

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        msg = str(body.get("message", ""))
        if msg.startswith("fail"):
            return self._json(503, {"error": "down"})
        if msg.startswith("inline"):
            return self._json(200, {"run_id": None, "reply": "inline reply: " + msg, "cards": []})
        run_id = f"run-{time.time_ns()}"
        RUNS[run_id] = 1.5 if msg.startswith("slow") else 0.05
        return self._json(200, {"run_id": run_id, "reply": "", "cards": []})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8100
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
