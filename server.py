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
import jump

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

    def _local(self):
        """A page on another origin can POST here; it cannot forge these.

        The damage would only be a switched terminal tab, but a jump is still
        an action, and actions get a guard.
        """
        origin = self.headers.get("Origin")
        if origin and not origin.startswith(("http://127.0.0.1", "http://localhost")):
            return False
        return self.headers.get("X-Fleet") == "1"

    def do_POST(self):
        if not self.path.startswith("/api/jump"):
            return self.send_error(404)
        if not self._local():
            return self.send_error(403, "not a local request")
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or "{}")
            pid = int(body["pid"])
        except (ValueError, KeyError, TypeError):
            return self.send_error(400, "expected {pid, tmux}")
        # Only ever act on a pid Claude Code itself registered as a session.
        live = {s["pid"]: s for s in fleet.sessions()}
        if pid not in live:
            return self.send_error(404, "no such live session")
        self._send(json.dumps(jump.jump(pid, live[pid]["tmux"])), "application/json")

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
