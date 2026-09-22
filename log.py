"""Write down what happened, so a strange thing has a record to check.

Nothing here changes what the page does. It records four kinds of thing, and
each one exists because it is what you go looking for when something looks
wrong:

- **what the fleet did** -- a session appeared, went busy, went quiet, was
  flagged, disappeared. This is sampled from the peer files a couple of times
  a second by a thread of its own, so the history is there whether or not a
  browser was open at the time.
- **what you did** -- every POST the page makes, with what it asked for, what
  came back, and how long it took. A tab renamed to something surprising can
  be traced to the click that did it.
- **what broke** -- exceptions, including the ones the page catches and turns
  into a quiet "server unreachable", and JavaScript errors from the browser,
  which otherwise nobody ever sees.
- **what was slow** -- an operation over its budget, and no line at all when
  it was fast. Silence is the normal state of this file.

One JSON object per line. `python3 log.py` reads it back.
"""
import datetime
import json
import os
import threading
import time
import traceback
from pathlib import Path


def log_dir():
    state = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(state) / "agentview"


LOG = log_dir() / "events.jsonl"
MAX_BYTES = 5_000_000        # one rotation, kept: this is a diary, not an archive
_lock = threading.Lock()
_seen_errors = {}            # dedup key -> when, so a repeating error logs once


def event(kind, **fields):
    """Append one event. Never raises: logging must not break the page."""
    try:
        record = {"at": datetime.datetime.now().isoformat(timespec="milliseconds"),
                  "kind": kind, **fields}
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _lock:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            if LOG.exists() and LOG.stat().st_size > MAX_BYTES:
                LOG.replace(LOG.with_suffix(".jsonl.1"))
            with LOG.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return record
    except OSError:
        return None


def error(where, exc, **fields):
    """An exception, with its traceback -- and only once per repeat.

    A failure inside the poll loop happens every two seconds. The first one
    is the news; the next four hundred are noise that would push the news out
    of the file.
    """
    key = (where, type(exc).__name__, str(exc)[:200])
    now = time.time()
    if now - _seen_errors.get(key, 0) < 300:
        return None
    _seen_errors[key] = now
    return event("error", where=where, error=f"{type(exc).__name__}: {exc}",
                 trace=traceback.format_exc().strip().splitlines()[-6:], **fields)


class timed:
    """Log an operation only when it takes longer than it should.

    `with timed("roster", 1.0, sessions=9):` -- silent under a second, one
    `slow` line over it. The 9-second poll that made clicking feel broken
    would have written a line a round.
    """

    def __init__(self, op, budget=1.0, **fields):
        self.op, self.budget, self.fields = op, budget, fields

    def __enter__(self):
        self.started = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb):
        ms = round((time.monotonic() - self.started) * 1000)
        if exc is not None:
            error(self.op, exc, ms=ms, **self.fields)
        elif ms > self.budget * 1000:
            event("slow", op=self.op, ms=ms, **self.fields)
        return False


# ------------------------------------------------------------ fleet history

# `waitingFor` is Claude Code's own words for what a session is blocked on --
# "input needed", "sandbox request", or the title of the dialog on screen.
WATCHED = ("status", "waitingFor", "name", "cwd")


def peers(cfg):
    """Every live session, read from the peer files and nothing else.

    Deliberately not `fleet.sessions()`: this runs every couple of seconds
    and must stay cheap, so it never opens a transcript.
    """
    out = {}
    for path in (Path(cfg) / "sessions").glob("*.json"):
        try:
            with path.open(encoding="utf-8") as fh:
                rec = json.load(fh)
            pid = int(rec["pid"])
            os.kill(pid, 0)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        out[pid] = rec
    return out


def transitions(before, after):
    """What changed between two samples, as events ready to be written.

    Only the fields worth a line: a session arriving or leaving, and the
    handful that move while it runs. `updatedAt` changes every heartbeat and
    would say nothing.
    """
    events = []
    for pid, rec in after.items():
        if pid not in before:
            events.append(("session.seen", {
                "pid": pid, "name": rec.get("name"), "status": rec.get("status"),
                "cwd": rec.get("cwd"), "entrypoint": rec.get("entrypoint"),
                "sessionId": rec.get("sessionId")}))
            continue
        for field in WATCHED:
            was, now = before[pid].get(field), rec.get(field)
            if was != now:
                events.append((field, {
                    "pid": pid, "name": rec.get("name"), "from": was, "to": now,
                    "sessionId": rec.get("sessionId")}))
    for pid, rec in before.items():
        if pid not in after:
            events.append(("session.gone", {
                "pid": pid, "name": rec.get("name"), "status": rec.get("status"),
                "sessionId": rec.get("sessionId"),
                "ranFor": _uptime(rec)}))
    return events


def _uptime(rec):
    started = rec.get("startedAt")
    if not started:
        return None
    return round((time.time() * 1000 - started) / 1000)


_flags = {}


def note_roster(blocks):
    """Write down when a session becomes flagged, and when it stops.

    The flag is not in the peer files -- it is worked out from the transcript
    while the page is being built -- so this hangs off the poll rather than
    the watcher thread. It says nothing on a poll where nothing changed.
    """
    after = {m["key"]: (m["flag"], m.get("name"))
             for b in blocks for m in b["members"]}
    for sid, (flag, name) in after.items():
        was = _flags.get(sid, (None, None))[0]
        if sid in _flags and was != flag:
            event("flag", sessionId=sid, name=name, **{"from": was, "to": flag})
    _flags.clear()
    _flags.update(after)


def watch(cfg, every=2.0):
    """Sample the peer files forever, writing down what moved.

    A thread rather than a hook on the page's poll: the interesting minute is
    often the one where nobody was looking, and a session that came and went
    between two page loads left no trace at all before this.
    """
    before = {}
    while True:
        try:
            after = peers(cfg)
            for kind, fields in transitions(before, after):
                event(kind, **fields)
            before = after
        except Exception as exc:            # a watcher must not die of one bad read
            error("watch", exc)
        time.sleep(every)


def start(cfg, every=2.0):
    thread = threading.Thread(target=watch, args=(cfg, every), daemon=True,
                              name="fleet-log")
    thread.start()
    event("watching", cfg=str(cfg), every=every, log=str(LOG))
    return thread


# ------------------------------------------------------------------ reading

def read(path=None, limit=200, kinds=(), who="", since=""):
    """The tail of the log, oldest first, after filtering."""
    path = Path(path or LOG)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if kinds and not any(rec.get("kind", "").startswith(k) for k in kinds):
            continue
        if who and who.lower() not in json.dumps(rec, default=str).lower():
            continue
        if since and rec.get("at", "") < since:
            continue
        rows.append(rec)
    return rows[-limit:]


def render(rec):
    """One event on one line, with the fields that event actually carries."""
    at = rec.get("at", "")[11:23]
    kind = rec.get("kind", "?")
    rest = {k: v for k, v in rec.items() if k not in ("at", "kind")}
    who = rest.pop("name", None)
    head = f"{at}  {kind:<14}" + (f"{who:<10}" if who else " " * 10)
    if kind in WATCHED:
        return head + f"{rest.get('from')} -> {rest.get('to')}"
    if kind == "error":
        return head + f"{rest.get('where')}: {rest.get('error')}"
    return head + "  ".join(f"{k}={v}" for k, v in rest.items() if v not in (None, "", []))


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Read the agentview event log.")
    ap.add_argument("-n", type=int, default=60, help="how many events (default 60)")
    ap.add_argument("-f", "--follow", action="store_true", help="keep printing new ones")
    ap.add_argument("-k", "--kind", action="append", default=[],
                    help="only these kinds, by prefix (status, action, error, slow...)")
    ap.add_argument("-w", "--who", default="", help="only events mentioning this text")
    ap.add_argument("--since", default="", help="ISO timestamp to start from")
    ap.add_argument("--path", default=str(LOG))
    args = ap.parse_args()

    shown = read(args.path, args.n, tuple(args.kind), args.who, args.since)
    for rec in shown:
        print(render(rec))
    if not args.follow:
        if not shown:
            print(f"(nothing in {args.path})")
        return
    last = shown[-1]["at"] if shown else ""
    while True:
        time.sleep(1)
        fresh = [r for r in read(args.path, 500, tuple(args.kind), args.who)
                 if r.get("at", "") > last]
        for rec in fresh:
            print(render(rec), flush=True)
        if fresh:
            last = fresh[-1]["at"]


if __name__ == "__main__":
    main()
