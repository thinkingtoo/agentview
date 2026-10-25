"""The Round: one poll of the overview.

Ask every provider, build the roster, settle what is forgotten, sweep the
Pastes, and hand the handler one dict to send. This is the only place that
does the round's bookkeeping; `fleet.roster` is a query and the handler only
serialises. A provider that fails or stalls is reported under `providers` and
the round goes on without it: nothing of that provider is forgotten, and
session lines, whose files carry no provider, are forgotten only on a round
every provider answered (ADR-0001).
"""
from pathlib import Path

import finished
import fleet
import lines
import log
import paste
import providers as provider_registry
import seen


def round(providers=None, now=None, seen_path=None, finished_path=None, lines_root=None):
    """One round. Every argument has a production default: the registered
    providers, the clock, and the stores' own places. A test passes fakes
    and a temporary directory and patches nothing.

    Returns the roster (`columns`, `counts`, `banners`, `flags`, `pastes`,
    `kept`) with `providers`: `{name: {"ok": True}}` for each that answered,
    `{"ok": False, "error": why}` for each that did not, this round or at
    start-up (`providers.broken`).
    """
    paste_root = Path(lines_root).parent / "pastes" if lines_root else None
    with fleet.POLL:
        # A poll is due every 3 seconds. The 9-second round that made clicking
        # feel broken would have written a line every time.
        with log.timed("roster", 1.5):
            rows, answered, failed = fleet.ask(providers, now=now, seen_path=seen_path,
                                               finished_path=finished_path)
            data = fleet.roster(providers, rows=rows, answered=answered, now=now,
                                paste_root=paste_root)
        flags = data["flags"]
        log.note_roster(flags)
        live = {f["key"] for f in flags}
        # Only the providers that answered get their dead sessions forgotten:
        # a missed round must not bring back as `ready` everything you had
        # already read.
        seen.forget(live, seen_path, answered=answered)
        finished.forget(live, finished_path, answered=answered)
        if not failed:
            lines.forget({f["id"] for f in flags}, lines_root)
        paste.sweep(paste_root)
    failed = {**provider_registry.broken(), **failed}
    status = {name: {"ok": True} for name in answered}
    status.update({name: {"ok": False, "error": why} for name, why in failed.items()})
    return {**data, "providers": status}
