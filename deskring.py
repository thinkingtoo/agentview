"""What the header's Merges button and the daily ring read off the merge desk.

The count comes through `deskfile.items()`. An item waits for the person until its box is ticked: a
ticked item is the watcher's now. How long an item has waited is read from its "Handed over by X,
YYYY-MM-DD HH:MM." line; an item without a readable time is never taken for old.

The ring is at most one a day, and the moment it last rang is kept in `$XDG_STATE_HOME/agentview/`, so a
restart of the service does not ring again.
"""
import json
import os
import re
import time
from pathlib import Path

import deskfile
import lines

STAMP = "desk-ring.json"
DAY = 24 * 3600
HANDED = re.compile(r"Handed over by .*?, (\d{4}-\d\d-\d\d \d\d:\d\d)\.")


def _waiting():
    try:
        return [i for i in deskfile.items() if not i.ticked]
    except (OSError, ValueError):     # unreadable or not UTF-8: the roster must still answer
        return []


def waiting():
    return len(_waiting())


def _handed_at(item):
    got = HANDED.search(item.block)
    if not got:
        return None
    try:
        return time.mktime(time.strptime(got.group(1), "%Y-%m-%d %H:%M"))
    except (ValueError, OverflowError):
        return None


def _stamp_path():
    return lines.store().parent / STAMP


def _last_rang():
    try:
        return float(json.loads(_stamp_path().read_text(encoding="utf-8"))["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def ring_pending(now=None):
    """The words of the ring when it is due now, else None. It asks only: the day is spent by `mark_rung`,
    which the page calls once the ring has really sounded, so a ring nobody heard is still due."""
    now = time.time() if now is None else now
    open_items = _waiting()
    times = [t for t in map(_handed_at, open_items) if t is not None]
    if not times or now - min(times) <= DAY:
        return None
    last = _last_rang()
    if last is not None and 0 <= now - last < DAY:
        return None
    n = len(open_items)
    return f"The merge desk has waited over a day for you: {n} {'item' if n == 1 else 'items'} waiting"


def mark_rung(now=None):
    """The ring sounded: no other before tomorrow, also after a restart. Whether it landed."""
    p = _stamp_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    return lines.write_atomic(p, json.dumps({"at": time.time() if now is None else now}))
