"""When a track will be done, from how fast its boxes have been ticked.

A goal file says how many of its "Done when" boxes are ticked, never when
each one was. So this keeps the one fact the card needs: when agentview first
saw the track and how many boxes were ticked then, and the count it saw last. The pace is the boxes
ticked since, over the time since -- up to now, so a track that stops moving
sees its estimate slip day by day instead of standing still. Before a box has
been ticked while it watched, there is no pace and the card says so.

A box unticked (or a "Done when" list rewritten shorter) starts the count
again from that moment: a pace measured across it would be a guess.

Kept beside the trackers' folder (`~/.claude/agentview/pace.json`), not in
`config.json`: that file is yours to hand-edit, and this one changes by itself.
"""
import datetime
import json
import threading

import projects

DAY = 86400
FAR = 90 * DAY                  # beyond this an estimate is not a date
_LOCK = threading.Lock()


def store():
    return projects.pm_dir().parent / "agentview" / "pace.json"


def load(path=None):
    try:
        with (path or store()).open(encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(got, dict):
        return {}
    return {track: seen for track, seen in got.items()
            if isinstance(seen, dict) and all(isinstance(seen.get(k), (int, float)) for k in ("since", "done"))
            and isinstance(seen.get("last", 0), (int, float))}


def save(marks, path=None):
    """Write atomically. Never raises: a card without an estimate is a
    smaller problem than a page that will not load."""
    path = path or store()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(marks, fh)
        tmp.replace(path)
    except OSError:
        pass


def observe(track, done, now, path=None):
    """The track's starting point `{"since", "done"}`, recorded on first
    sight and again when its count goes down; `last` is the count seen last."""
    with _LOCK:
        marks = load(path)
        seen = marks.get(track)
        if seen is None or done < seen.get("last", seen["done"]):
            seen = marks[track] = {"since": now, "done": done, "last": done}
            save(marks, path)
        elif done != seen.get("last"):
            seen["last"] = done
            save(marks, path)
        return seen


def when(at, now):
    """A date the way the card says it: the weekday and day when it is within
    a week, the day and month further off."""
    day = datetime.datetime.fromtimestamp(at)
    if day.date() == datetime.datetime.fromtimestamp(now).date():
        return "today"
    if at - now < 7 * DAY:
        return day.strftime("%a %-d")
    return day.strftime("%-d %b")


def span(seconds):
    hours = seconds / 3600
    if hours < 48:
        return f"{max(1, round(hours))} h"
    return f"{round(hours / 24)} days"


def eta(track, done, total, now, path=None):
    """`{"text", "why"}` for a track still open: when it will be done at the
    pace measured so far, and on what that pace rests."""
    seen = observe(track, done, now, path)
    ticked, watched = done - seen["done"], now - seen["since"]
    since = datetime.datetime.fromtimestamp(seen["since"]).strftime("%-d %b %H:%M")
    if ticked <= 0 or watched <= 0:
        return {"text": "ETA after the next box",
                "why": f"no box ticked since {since}, when agentview started counting: no pace yet"}
    left = (total - done) * watched / ticked
    basis = f"{ticked} {'box' if ticked == 1 else 'boxes'} in {span(watched)} since {since}"
    if left > FAR:
        return {"text": "ETA over 3 months", "why": basis}
    return {"text": f"ETA {when(now + left, now)}", "why": f"{basis}: {total - done} left, about {span(left)}"}
