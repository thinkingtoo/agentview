"""The Round: one poll of the overview.

Ask every provider, build the roster, settle what is forgotten, sweep the
Pastes, and hand the handler one dict to send. This is the only place that
does the round's bookkeeping; `fleet.roster` is a query and the handler only
serialises. A provider that fails or stalls is reported under `providers` and
the round goes on without it: nothing of that provider is forgotten, and
session lines, whose files carry no provider, are forgotten only on a round
every provider answered (ADR-0001).
"""
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
    paste_root = paste.store(lines_root)
    with fleet.POLL:
        # A poll is due every 3 seconds. The 9-second round that made clicking
        # feel broken would have written a line every time.
        with log.timed("roster", 1.5):
            rows, answered, failed = fleet.live(providers, now=now, seen_path=seen_path,
                                                finished_path=finished_path, lines_root=lines_root)
            data = fleet.roster(providers, rows=rows, answered=answered, now=now,
                                paste_root=paste_root)
        flags = data["flags"]
        log.note_roster(flags)
        # A provider whose module did not load is as missing as one that
        # failed this round.
        failed = {**provider_registry.broken(), **failed}
        here = {f["key"] for f in flags}
        # The one decision of what is forgotten. A keyed store drops the gone
        # sessions of the providers that answered: a missed round must not
        # bring back as `ready` everything you had already read. Line files
        # carry no provider, so they go only on a round everyone answered.
        held = seen.keys(seen_path) | finished.keys(finished_path)
        droppable = {key for key in held
                     if key not in here and key.partition(":")[0] in answered}
        full = not failed
        seen.forget(droppable, seen_path)
        finished.forget(droppable, finished_path)
        if full:
            lines.forget({f["id"] for f in flags}, lines_root)
        paste.sweep(paste_root)
    status = {name: {"ok": True} for name in answered}
    status.update({name: {"ok": False, "error": why} for name, why in failed.items()})
    return {**data, "providers": status}
