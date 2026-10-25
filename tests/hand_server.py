#!/usr/bin/env python3
"""A throwaway server for the page smoke: fake sessions, a config of its own.

    python3 tests/hand_server.py DIR

DIR holds everything it writes -- `config.json`, the seen marks, the lines, the
log -- and nothing else is touched. It listens on a port the system picks
(never 8765), prints `PORT <n>` once it is listening and serves until it is
killed. The sessions are invented and nothing here can reach a real terminal;
the route that retitles a tab is never sent a pid.
"""
import json
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import fleet
import lines
import log
import marks
import server
from test_providers import Fake, minimal

SESSIONS = [minimal(id=sid, name=name, cwd=f"/home/alice/Projects/{where}", updatedAt=1790000000000 + n)
            for n, (sid, name, where) in enumerate((("a", "Ilse", "maple"), ("b", "Odile", "orchard"),
                                                      ("c", "Saskia", "pear"), ("d", "Femi", "maple")))]


class Reloaded(Fake):
    """The sessions the smoke last wrote to `sessions.json` beside the config, or
    the invented ones above while it has written none: a way to say that a
    session wrote again, stopped again or closed, to a server that is running."""

    def __init__(self, path):
        super().__init__(SESSIONS)
        self.path = path

    def live(self):
        try:
            return [dict(s) for s in json.loads(self.path.read_text())]
        except (OSError, ValueError):
            return super().live()


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = Path(sys.argv[1])
    root.mkdir(parents=True, exist_ok=True)
    cfg = root / "config.json"
    if not cfg.exists():
        cfg.write_text("{}")
    fake = Reloaded(root / "sessions.json")
    for target, new in (("fleet.CONFIG", cfg), ("fleet._providers", lambda: [fake]),
                        ("marks.store", lambda: root / "marks.json"), ("lines.store", lambda: root / "lines"),
                        ("log.LOG", root / "events.jsonl"), ("server.restorable", lambda live: None),
                        ("server.closed_now", lambda live: []), ("server.coverage", lambda live: None),
                        ("providers.broken", lambda: {})):
        mock.patch(target, new).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    print(f"PORT {httpd.server_address[1]}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
