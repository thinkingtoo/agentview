#!/usr/bin/env python3
"""Serve the fleet page on localhost.

Bound to 127.0.0.1 on purpose: the page shows your prompts verbatim, which is
client work, and occasionally a credential someone pasted into an error.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fleet

HERE = Path(__file__).resolve().parent


def port():
    try:
        with (HERE / "config.json").open(encoding="utf-8") as fh:
            return int(json.load(fh).get("port", 8765))
    except (OSError, ValueError, TypeError):
        return 8765


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype):
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/api/roster"):
            self._send(json.dumps({"blocks": fleet.roster()}), "application/json")
        elif self.path in ("/", "/index.html"):
            self._send((HERE / "index.html").read_text(encoding="utf-8"),
                       "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass  # a polling page would fill the journal with noise


def main():
    p = port()
    server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
    print(f"fleet on http://127.0.0.1:{p}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
