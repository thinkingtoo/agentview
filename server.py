#!/usr/bin/env python3
"""Serve the fleet page on localhost.

Bound to 127.0.0.1 on purpose: the page shows your prompts verbatim, which is
client work, and occasionally a credential someone pasted into an error.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fleet
import jump
import lines
import log
import providers
import seen
import snapshot
import subprocess
import sys
from providers import claude

HERE = Path(__file__).resolve().parent


def setting(key, default):
    try:
        return type(default)(fleet.read_config().get(key, default))
    except (ValueError, TypeError):
        return default


def page():
    """The page, with the configured scale baked in.

    Substituted server-side rather than applied by script, so the page never
    renders once at the wrong size and then jumps.
    """
    html = (HERE / "index.html").read_text(encoding="utf-8")
    return (html.replace("{{ZOOM}}", str(setting("zoom", 1.5)))
                .replace("{{HOME}}", str(Path.home())))


_SNAP = {"files": None, "snap": None, "latest": None}


def _snapshots():
    """Read the snapshot folder again only when a file came or went."""
    try:
        files = tuple(sorted(p.name for p in snapshot.store().glob("*.json")))
    except OSError:
        return False
    if files != _SNAP["files"]:
        snaps, boot = snapshot.load_all(), snapshot.boot_id()
        _SNAP.update(files=files, snap=snapshot.choose(snaps, boot),
                     latest=snapshot.latest(snaps, boot))
    return True


def saved_at():
    """When this boot last wrote down where every session lives."""
    if not _snapshots() or not _SNAP["latest"]:
        return None
    return _SNAP["latest"]["taken_at"]


def restorable(live_ids):
    """What the last boot had running that is not running now, for the button."""
    if not _snapshots():
        return None
    snap = _SNAP["snap"]
    if not snap:
        return None
    gone = snapshot.missing(snap, live_ids)
    clients = snapshot.tmux_clients()
    tabs = snapshot.missing_tabs(snap, clients)
    tabs += [t for t in snapshot.unseen_tmux(snapshot.live_peers(), snapshot.tmux_panes(), clients)
             if t not in tabs]
    return {"taken_at": snap["taken_at"],
            "names": [s["name"] or s["sessionId"][:8] for s in gone] + [f"tmux {t}" for t in tabs]}


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

    ROUTES = ("jump", "seen", "order", "name", "line", "assign", "hold", "chime", "restore", "snapshot")

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

    def _seen(self, body):
        """You looked. That is all a click on a row without a terminal means,
        and it is enough: the tick goes, the count comes down."""
        key = body.get("key")
        if not isinstance(key, str):
            return self.send_error(400, "expected {key}")
        if not fleet.look(key):
            return self.send_error(404, "no such live session")
        self._send(json.dumps({"ok": True}), "application/json")

    def _jump(self, body):
        key = body.get("key")
        if not isinstance(key, str):
            return self.send_error(400, "expected {key}")
        # The key names a provider and a session; the provider says whether
        # it is still alive. Only ever act on one that is.
        hit = fleet.look(key)          # looking is looking, whatever comes next
        if not hit:
            return self.send_error(404, "no such live session")
        provider, session = hit
        done = fleet.jump_to(provider, session)
        log.event("jumped", key=key, pid=session.get("pid"),
                  name=session.get("name"), **done)
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

    def _chime(self, body):
        """Ring, or stay quiet, when a session starts waiting on you.

        Next to `hold` for the same reason: it is how you want the page to
        behave, and it should still be true tomorrow.
        """
        chime = body.get("chime")
        if not isinstance(chime, bool):
            return self.send_error(400, "expected {chime: true|false}")
        fleet.write_config({"chime": chime})
        self._send(json.dumps({"ok": True, "chime": chime}), "application/json")

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
        key, project = body.get("key"), body.get("project")
        if not isinstance(key, str) or not isinstance(project, str):
            return self.send_error(400, "expected {key, project}")
        project = project.strip()
        assign = fleet.config_value("assign", {})
        # Empty puts the session back where its directory says it belongs.
        assign.pop(key, None) if not project else assign.update({key: project})
        fleet.write_config({"assign": assign})
        self._send(json.dumps({"ok": True, "project": project}), "application/json")

    def _line(self, body):
        key, text = body.get("key"), body.get("text")
        if not isinstance(key, str) or not isinstance(text, str):
            return self.send_error(400, "expected {key, text}")
        text = text.strip()
        own = fleet.config_value("lines", {})
        own.pop(key, None) if not text else own.update({key: text})
        fleet.write_config({"lines": own})

        # The tab in the terminal has to say the same thing, or you end up
        # hunting for a session whose tab still carries the old title. A
        # session with no pid has no tab: the line in config.json is all.
        ran = []
        hit = fleet.find(key)
        if hit and isinstance(hit[1].get("pid"), int):
            ran = jump.set_title(hit[1]["pid"], hit[1].get("tmux") or "", text)
        # What was actually run on the terminal, not just what was intended:
        # an empty list here is a rename that silently did nothing.
        log.event("retitle", key=key, text=text, ran=ran)
        self._send(json.dumps({"ok": True, "ran": ran}), "application/json")

    def _restore(self, body):
        """Reopen what the last boot left running. In the background: resuming
        goes one session at a time and takes a while, and the page keeps polling."""
        out = snapshot.store().parent / "restore.log"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "a") as fh:
            subprocess.Popen([sys.executable, str(HERE / "snapshot.py"), "restore"],
                             stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True, cwd=str(HERE))
        self._send(json.dumps({"ok": True, "log": str(out)}), "application/json")

    def _snapshot(self, body):
        """Save now rather than at the next 2-minute tick: the button you press
        before shutting down. A save that finds nothing moved writes no file,
        and the last one already describes this minute."""
        path = snapshot.save()
        self._send(json.dumps({"ok": True, "changed": bool(path), "taken_at": saved_at()}),
                   "application/json")

    def do_GET(self):
        if self.path.startswith("/api/roster"):
            # A poll is expected to be fast. The 9-second round that made
            # clicking feel broken would have written a line every time.
            with fleet.POLL:
                with log.timed("roster", 1.5):
                    blocks = fleet.roster()
                failed = {**providers.broken(), **fleet.ROUND["failed"]}
                answered = set(fleet.ROUND["answered"])
            log.note_roster(blocks)
            live = {m["key"] for b in blocks for m in b["members"]}
            # Only the providers that answered get their dead sessions
            # forgotten: a missed round must not bring back as `ready`
            # everything you had already read.
            seen.forget(live, answered=answered)
            if not fleet.ROUND["failed"]:
                lines.forget({m["id"] for b in blocks for m in b["members"]})
            status = {name: {"ok": True} for name in answered}
            status.update({name: {"ok": False, "error": why} for name, why in failed.items()})
            live_ids = {m["key"].partition(":")[2] for b in blocks for m in b["members"]
                        if m["key"].startswith("claude:")}
            self._send(json.dumps({"blocks": blocks,
                                   "restore": restorable(live_ids),
                                   "saved": saved_at(),
                                   "providers": status,
                                   "hold": fleet.config_value("hold", False),
                                   "chime": fleet.config_value("chime", True)}),
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
    # Stores written before providers existed are keyed by bare session id.
    migrated = fleet.migrate_keys()
    log.start(claude.claude_dir())
    if migrated:
        log.event("migrated", fields=migrated)
    print(f"fleet on http://127.0.0.1:{p}", flush=True)
    print(f"log      {log.LOG}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
