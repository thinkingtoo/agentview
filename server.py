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
import log
import seen

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

    ROUTES = ("jump", "order", "name", "line", "assign", "hold")

    def do_POST(self):
        if not self._local():
            log.event("refused", path=self.path, origin=self.headers.get("Origin"))
            return self.send_error(403, "not a local request")
        try:
            body = self._body()
        except ValueError:
            return self.send_error(400, "expected JSON")

        if self.path.startswith("/api/log"):
            return self._log(body)
        for name in self.ROUTES:
            if self.path.startswith(f"/api/{name}"):
                # Every action is written down. A tab that ends up called
                # something surprising can then be traced back to the click
                # that did it, which is exactly the trail that was missing.
                log.event("action", what=name, asked=body)
                with log.timed(f"action.{name}", 2.0, asked=body):
                    return getattr(self, f"_{name}")(body)
        return self.send_error(404)

    def _log(self, body):
        """Errors from the page itself.

        A JavaScript exception used to be invisible: the poll stops, the page
        goes stale, and nothing anywhere says why.
        """
        log.event("page.error", **{k: str(v)[:2000] for k, v in body.items()
                                   if k in ("message", "stack", "source", "where")})
        self._send(json.dumps({"ok": True}), "application/json")

    def _jump(self, body):
        try:
            pid = int(body["pid"])
        except (ValueError, KeyError, TypeError):
            return self.send_error(400, "expected {pid}")
        # Only ever act on a pid Claude Code itself registered as a session.
        rec = fleet.live_session(pid)
        if not rec:
            return self.send_error(404, "no such live session")
        # Looking is looking, whether or not the terminal comes to the front.
        seen.mark(rec.get("sessionId"), rec.get("statusUpdatedAt"))
        done = jump.jump(pid, rec.get("tmux") or "")
        log.event("jumped", pid=pid, name=rec.get("name"), **done)
        self._send(json.dumps(done), "application/json")

    def _hold(self, body):
        """Freeze the order of the cards, or let them sort themselves again.

        Lives in config.json with the pins and the labels: it is a decision
        about how you want to read the page, and it should still be true
        tomorrow.
        """
        hold = body.get("hold")
        if not isinstance(hold, bool):
            return self.send_error(400, "expected {hold: true|false}")
        fleet.write_config({"hold": hold})
        self._send(json.dumps({"ok": True, "hold": hold}), "application/json")

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

    def _assign(self, body):
        sid, project = body.get("sessionId"), body.get("project")
        if not isinstance(sid, str) or not isinstance(project, str):
            return self.send_error(400, "expected {sessionId, project}")
        project = project.strip()
        assign = fleet.config_value("assign", {})
        # Empty puts the session back where its directory says it belongs.
        assign.pop(sid, None) if not project else assign.update({sid: project})
        fleet.write_config({"assign": assign})
        self._send(json.dumps({"ok": True, "project": project}), "application/json")

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
        # What was actually run on the terminal, not just what was intended:
        # an empty list here is a rename that silently did nothing.
        log.event("retitle", sessionId=sid, text=text, ran=ran)
        self._send(json.dumps({"ok": True, "ran": ran}), "application/json")

    def do_GET(self):
        if self.path.startswith("/api/roster"):
            # A poll is expected to be fast. The 9-second round that made
            # clicking feel broken would have written a line every time.
            with log.timed("roster", 1.5):
                blocks = fleet.roster()
            log.note_roster(blocks)
            seen.forget({m["sessionId"] for b in blocks for m in b["members"]})
            self._send(json.dumps({"blocks": blocks,
                                   "hold": fleet.config_value("hold", False)}),
                       "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(page(), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass  # a polling page would fill the journal with noise


def main():
    p = setting("port", 8765)
    server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
    log.start(fleet.claude_dir())
    print(f"fleet on http://127.0.0.1:{p}", flush=True)
    print(f"log      {log.LOG}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
