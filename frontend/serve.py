#!/usr/bin/env python3
# Copyright (c) 2026 vertciti. All rights reserved.
# vertciti chat frontend dev/static server: serves this directory with the same
# security headers production must send (CSP without unsafe-inline, nosniff,
# frame-ancestors, Referrer-Policy) and a real 404 page.
#   python3 frontend/serve.py [--port 3120] [--api http://127.0.0.1:8120]
"""Static file server with security headers for the chat page."""

from __future__ import annotations

import argparse
import functools
import http.server
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def csp(api_origin: str) -> str:
    return "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "font-src 'self'",
        "img-src 'self' data:",
        f"connect-src 'self' {api_origin}",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "object-src 'none'",
    ])


class Handler(http.server.SimpleHTTPRequestHandler):
    api_origin = "http://127.0.0.1:8120"

    def end_headers(self) -> None:
        self.send_header("Content-Security-Policy", csp(self.api_origin))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        super().end_headers()

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        page = HERE / "404.html"
        if code == 404 and page.exists():
            body = page.read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        super().send_error(code, message, explain)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        # path and status only; never query strings (they carry session ids)
        path = self.path.split("?", 1)[0]
        print(f'{{"msg":"static","path":"{path}","status":"{args[1] if len(args) > 1 else ""}"}}')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "3120")))
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--api", default=os.environ.get("CHAT_API_ORIGIN", "http://127.0.0.1:8120"))
    args = parser.parse_args()
    Handler.api_origin = args.api
    handler = functools.partial(Handler, directory=str(HERE))
    with http.server.ThreadingHTTPServer((args.bind, args.port), handler) as srv:
        print(f"[chat] frontend on http://{args.bind}:{args.port} (API {args.api})", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()
