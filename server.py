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


def setting(key, default):
    try:
        with (HERE / "config.json").open(encoding="utf-8") as fh:
            return type(default)(json.load(fh).get(key, default))
    except (OSError, ValueError, TypeError):
        return default


def page():
    """The page, with the configured scale baked in.

    Substituted server-side rather than applied by script, so the page never
    renders once at the wrong size and then jumps.
    """
    html = (HERE / "index.html").read_text(encoding="utf-8")
    return html.replace("{{ZOOM}}", str(setting("zoom", 1.5)))


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

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or "{}")

    def do_POST(self):
        if not self._local():
            return self.send_error(403, "not a local request")
        try:
            body = self._body()
        except ValueError:
            return self.send_error(400, "expected JSON")

        if self.path.startswith("/api/jump"):
            return self._jump(body)
        if self.path.startswith("/api/order"):
            return self._order(body)
        if self.path.startswith("/api/name"):
            return self._name(body)
        if self.path.startswith("/api/line"):
            return self._line(body)
        return self.send_error(404)

    def _jump(self, body):
        try:
            pid = int(body["pid"])
        except (ValueError, KeyError, TypeError):
            return self.send_error(400, "expected {pid}")
        # Only ever act on a pid Claude Code itself registered as a session.
        live = {s["pid"]: s for s in fleet.sessions()}
        if pid not in live:
            return self.send_error(404, "no such live session")
        self._send(json.dumps(jump.jump(pid, live[pid]["tmux"])), "application/json")

    def _order(self, body):
        pinned = body.get("pinned")
        if not isinstance(pinned, list) or not all(isinstance(p, str) for p in pinned):
            return self.send_error(400, "expected {pinned: [project, ...]}")
        fleet.write_config({"pinned": pinned})
        self._send(json.dumps({"ok": True, "pinned": pinned}), "application/json")

    def _name(self, body):
        key, label = body.get("project"), body.get("label")
        if not isinstance(key, str) or not isinstance(label, str):
            return self.send_error(400, "expected {project, label}")
        names = fleet.config_value("names", {})
        # An empty label is how you take a rename back.
        names.pop(key, None) if not label.strip() else names.update({key: label.strip()})
        fleet.write_config({"names": names})
        self._send(json.dumps({"ok": True}), "application/json")

    def _line(self, body):
        sid, text = body.get("sessionId"), body.get("text")
        if not isinstance(sid, str) or not isinstance(text, str):
            return self.send_error(400, "expected {sessionId, text}")
        text = text.strip()
        lines = fleet.config_value("lines", {})
        lines.pop(sid, None) if not text else lines.update({sid: text})
        fleet.write_config({"lines": lines})

        # The tab in the terminal has to say the same thing, or you end up
        # hunting for a session whose tab still carries the old title.
        ran = []
        for s in fleet.sessions():
            if s["sessionId"] == sid:
                ran = jump.set_title(s["pid"], s["tmux"], text)
                break
        self._send(json.dumps({"ok": True, "ran": ran}), "application/json")

    def do_GET(self):
        if self.path.startswith("/api/roster"):
            self._send(json.dumps({"blocks": fleet.roster()}), "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(page(), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass  # a polling page would fill the journal with noise


def main():
    p = setting("port", 8765)
    server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
    print(f"fleet on http://127.0.0.1:{p}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
