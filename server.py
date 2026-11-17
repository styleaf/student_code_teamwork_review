#!/usr/bin/env python3
"""Small local HTTP server for the student replay application."""

from __future__ import annotations

import argparse
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent


class ReplayHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/":
            self.path = urlunsplit((parsed.scheme, parsed.netloc, "/app/index.html", parsed.query, parsed.fragment))
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the replay page in the default browser")
    args = parser.parse_args()

    handler = partial(ReplayHandler, directory=str(ROOT))
    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as error:
        print(f"Unable to start the replay server on {args.host}:{args.port}: {error}")
        print("If another copy is already running, open http://127.0.0.1:8765/ or stop that copy first.")
        return 1

    url = f"http://{args.host}:{args.port}/"
    print(f"Student replay is running at {url}")
    if args.open:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
