"""Writes counted per minute: the 30-slot strip behind a project's graph.

A provider counts the records its sessions write, in the minute each record is
stamped with, as they go by. A minute is a whole number of minutes since the
epoch; the strip is read off it. Claude Code and Codex stamp every record the
same way (a top-level `timestamp`, ISO with a Z), so both count with this.
"""
import collections
import datetime
import time

# Movement is counted per minute, 30 of them, as the records go by. A minute
# is a whole number of minutes since the epoch; the strip is read off it.
STRIP_MINUTES = 30
KEEP_MINUTES = STRIP_MINUTES + 10


def seconds_of(stamp):
    try:
        return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError, OverflowError):
        return None


def minute_of(stamp):
    seconds = seconds_of(stamp)
    return None if seconds is None else int(seconds // 60)


def blank_counts():
    # `seen_from` is the first minute this reader saw from its beginning. 0
    # means the file was read from the top, so every minute is known; a larger
    # number means a cold start began mid-file, and earlier minutes are
    # unknown rather than empty.
    return {"offset": 0, "ino": None, "head": b"",
            "minutes": collections.Counter(), "first": None, "seen_from": 0}


def count(state, rec):
    """One more write, in the minute its record is stamped with. A record with
    no stamp (a title, a mode switch) is bookkeeping, not the session at work."""
    minute = minute_of(rec.get("timestamp"))
    if minute is None:
        return
    state["minutes"][minute] += 1
    if state["first"] is None or minute < state["first"]:
        state["first"] = minute


def prune(state):
    """Minutes the strip can no longer show are not kept. Measured from the
    newest write, not the clock, so a session quiet for a day keeps its last
    few minutes and nothing older."""
    minutes = state["minutes"]
    if minutes:
        edge = max(minutes) - KEEP_MINUTES
        for minute in [m for m in minutes if m < edge]:
            del minutes[minute]


def cold_counts(state):
    """The first sight of a big file read only its tail. The first minute in
    that tail may be cut short, so what is known starts one minute after it."""
    first = state["first"]
    state["seen_from"] = (first + 1 if first is not None
                          else int(time.time() // 60) + 1)


def strip(state, now):
    """30 per-minute write counts, oldest first, newest (this minute) last.
    None where this reader was not yet looking."""
    newest = int(now // 60)
    return [None if minute < state["seen_from"] else state["minutes"].get(minute, 0)
            for minute in range(newest - STRIP_MINUTES + 1, newest + 1)]
