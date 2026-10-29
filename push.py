#!/usr/bin/env python3
"""Send the person's fleet to the hub, for FleetView on the phone (thinkingtoo/tt-tiroir#173).

What leaves is a projection of the roster, never the roster: the page shows
prompts verbatim, paths, branches and the first line of every Paste, and none
of that goes. The fields are listed here, one by one; a field the roster gains
later stays on the laptop until someone adds it to this list.

Only the projects named in `push.include` (config.json) are sent, by their key
(`repo:…`, `track:…`, `client:…`, `folder:…`); the list is empty until the
person fills it, and an empty list sends nothing at all. The device token is
the hub's, bound there to one member and one device; it lives in the login
keyring and never in a file.

    push.py once        one round: read the roster, send it if it changed

A timer runs `once` every 20 seconds (`agentview-push.timer`). A roster that
has not changed is sent again after five minutes, so the hub can tell a quiet
laptop from one that is gone.
"""
import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import credentials  # noqa: E402
import fleet  # noqa: E402
import log  # noqa: E402
import vault  # noqa: E402
import working  # noqa: E402

URL = "https://thinkingtoo.tiroir.me/fleet-push"
VERSION = 1
HEARTBEAT_MS = 5 * 60 * 1000
TIMEOUT = 10
# How the device token is found in the keyring, for `secret-tool store` to match.
TOKEN_ATTRIBUTES = {"application": vault.APPLICATION, "purpose": "fleet-push"}

# Where a tile's line may come from to be sent (`working.line_of`): the session's
# own words, and Claude Code's title, which Claude Code writes itself. A line read
# from the prompt or the branch is not, nor another provider's title: Codex's is
# its first prompt, cut (`providers/codex.py`).
OWN_SOURCES = (working.OWN, working.DID)
TITLED = {"claude"}
FLAGS = ("waiting", "ready", "tool", "stuck")
PASTE_ID = re.compile(r"[0-9a-f]{16}")       # as `paste.py` makes them
MAX_BODY = 256 * 1024                        # the hub refuses more (413)
FIT_MARGIN = 1024                            # for `at` and the separators the estimate leaves out
HIDDEN = "(hidden: looked like a credential)"
# The hub's limits (tiroir-fleet re-checks them): characters per field, and how many of each.
NAME_LEN, LINE_LEN, NEED_LEN = 60, 200, 200
QUESTION_LEN, LABEL_LEN, HINT_LEN, TITLE_LEN = 300, 60, 200, 120
MAX_COLUMNS, MAX_SESSIONS, MAX_QUESTIONS, MAX_OPTIONS, MAX_PASTES = 40, 40, 4, 6, 20


BREAKS = frozenset("\t\n\v\f\r\x1c\x1d\x1e\x85\u2028\u2029")


def _invisible(c):
    """A control or format character, or half of a surrogate pair: none of them is text to show."""
    return unicodedata.category(c) in ("Cc", "Cf", "Cs")


def say(value, limit):
    """A string as it may leave, or `HIDDEN`.

    A line break becomes a space and every other invisible character goes. The
    credential check looks at the text as it came, as it leaves, and with the
    breaks taken out as well: a zero-width character or a newline inside a
    token hides it from the shapes, and taking it out would put it back
    together after the check. Cut to `limit` last, since a cut token no longer
    looks like one."""
    if not isinstance(value, str):
        return ""
    shown = "".join(" " if c in BREAKS else c for c in value if c in BREAKS or not _invisible(c))
    joined = "".join(c for c in value if not _invisible(c) and c not in BREAKS)
    if any(credentials.looks_secret(t) for t in (value, shown, joined)):
        return HIDDEN
    return shown[:limit]


def projection(data, include):
    """The body the hub gets, from one roster (`poll.round`) and the projects
    named in `push.include`."""
    flags = {f.get("key"): f for f in data.get("flags") or [] if isinstance(f, dict)}
    # A column is its project's key, never its display name: two columns may share a name.
    wanted = set(include)
    return {"columns": [{"project": column["project"], "name": say(column.get("name"), NAME_LEN),
                         "sessions": _sessions(column["sessions"] if isinstance(column.get("sessions"), list) else [],
                                               flags)}
                        for column in data.get("columns") or []
                        if isinstance(column, dict) and isinstance(column.get("project"), str)
                        and column["project"] in wanted][:MAX_COLUMNS]}


def _sessions(tiles, flags):
    """The column's sessions. A tile that cannot be read stays behind; the rest go."""
    sent = []
    for t in tiles[:MAX_SESSIONS]:
        try:
            sent.append(_session(t, flags.get(t.get("key"), {})))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return sent


def _session(t, flag):
    stuck = t.get("stuck") or {}
    question = None
    if stuck.get("source") == "question":
        question = {"questions": [
            {"question": say(q.get("question"), QUESTION_LEN), "header": say(q.get("header"), LABEL_LEN),
             "multi": q.get("multi") is True,
             "options": [{"label": say(o.get("label"), LABEL_LEN), "description": say(o.get("description"), HINT_LEN)}
                         for o in q.get("options", [])[:MAX_OPTIONS]]}
            for q in stuck.get("context", {}).get("questions", [])[:MAX_QUESTIONS]]}
    return {
        "name": say(t.get("name"), NAME_LEN),
        "flag": flag.get("flag") if flag.get("flag") in FLAGS else None,
        "blocked": bool(t.get("blocked")),
        "since": int(t["stop"]),
        "line": say(t.get("line"), LINE_LEN) if _own_line(t) else "",
        # Only what the session wrote for you: an ask read out of its last words is transcript.
        "need": say(t.get("need"), NEED_LEN) if t.get("blocked") is True else "",
        "question": question,
        "pastes": [{"id": p.get("id"), "title": say(p.get("title"), TITLE_LEN), "secret": p.get("secret") is True}
                   for p in t.get("pastes", [])
                   if isinstance(p.get("id"), str) and PASTE_ID.fullmatch(p["id"])][:MAX_PASTES],
    }


def _own_line(t):
    source = t.get("lineSource")
    return source in OWN_SOURCES or (source == working.TITLE and t.get("provider") in TITLED)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def fit(columns, limit=MAX_BODY - FIT_MARGIN):
    """Cut the projection until the body fits the hub's limit: the open
    questions first, from the last session up, then sessions from the end."""
    total = len(_encoded({"v": VERSION, "at": 0, "columns": columns}))
    everyone = [s for c in columns for s in c["sessions"]]
    for s in reversed(everyone):
        if total <= limit:
            return columns
        if s["question"] is not None:
            before = len(_encoded(s))
            s["question"] = None
            total -= before - len(_encoded(s))
    for c in reversed(columns):
        while c["sessions"] and total > limit:
            total -= len(_encoded(c["sessions"].pop())) + 2
    while total > limit and columns:
        columns.pop()
        total = len(_encoded({"v": VERSION, "at": 0, "columns": columns}))
    return columns


def clean_token(value):
    """The device token as a header can carry it, or None. `mint` prints it with a newline."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and all(33 <= ord(c) <= 126 for c in value) else None


def state_path():
    return log.log_dir() / "push.json"


def _last(state):
    try:
        got = json.loads(Path(state).read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _digest(columns):
    return hashlib.sha256(json.dumps(columns, sort_keys=True).encode()).hexdigest()


EMPTY = _digest([])


def once(*, include, read, post, token, url, state, now):
    """One round. `read` gives the roster, `token` the device token (None when
    there is none), and `post(url, token, body)` the hub's HTTP status. Says
    what it did: sent, unchanged, nothing included, no token, or refused <status>."""
    last = _last(state)
    if include:
        columns = fit(projection(read(), include)["columns"])
    elif last.get("digest") in (None, EMPTY):
        return "nothing included"
    else:
        # The list was emptied: the hub is told once, or it keeps showing the last cards.
        columns = []
    digest = _digest(columns)
    sent = last.get("sent")
    if last.get("digest") == digest and isinstance(sent, int) and now - sent < HEARTBEAT_MS:
        return "unchanged"
    secret = token()
    if not secret:
        return "no token"
    body = _encoded({"v": VERSION, "at": now, "columns": columns})
    status = post(url, secret, body)
    if status != 204:
        return f"refused {status}"
    Path(state).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(state).with_suffix(".tmp")
    tmp.write_text(json.dumps({"digest": digest, "sent": now}), encoding="utf-8")
    tmp.replace(state)
    return "sent"


def read_roster():
    """The roster from the running page, the way the page itself asks for it:
    a round of its own here would do the server's bookkeeping a second time."""
    try:
        port = int(fleet.read_config().get("port", 8765))     # as `server.setting` reads it
    except (ValueError, TypeError):
        port = 8765
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/roster",
                                     headers={"Host": f"127.0.0.1:{port}"})
    with _opener().open(request, timeout=TIMEOUT) as answer:
        return json.load(answer)


class _Stay(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer, never followed: a POST replayed elsewhere would take the token along."""

    def redirect_request(self, *args, **kwargs):
        return None


def _opener():
    # No proxy: the roster holds prompts, and the token is the hub's alone.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _Stay)


def post_body(url, token, body):
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with _opener().open(request, timeout=TIMEOUT) as answer:
            return answer.status
    except urllib.error.HTTPError as err:
        return err.code


def device_token():
    try:
        found = vault.lookup(TOKEN_ATTRIBUTES)
    except vault.Unavailable as err:
        log.event("push", outcome="no token", why=str(err))
        return None
    token = clean_token(found)
    if found and not token:
        # Never the value: what is wrong with it is said, not shown.
        log.event("push", outcome="no token", why="the keyring item is not a token a header can carry")
    return token


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["once"])
    parser.parse_args(argv)
    settings = fleet.config_value("push", {})
    settings = settings if isinstance(settings, dict) else {}
    include = [p for p in settings.get("include", []) if isinstance(p, str)] \
        if isinstance(settings.get("include"), list) else []
    url = settings.get("url") or URL
    if not isinstance(url, str) or not url.startswith("https://"):
        print("push: push.url must be an https:// address", file=sys.stderr)
        return 1
    try:
        outcome = once(include=include, read=read_roster, post=post_body, token=device_token,
                       url=url, state=state_path(), now=int(time.time() * 1000))
    except (OSError, ValueError) as err:
        # The type only: an error's text can carry what it was given, such as a header.
        log.event("push", outcome="failed", error=type(err).__name__)
        print(f"push: {type(err).__name__}", file=sys.stderr)
        return 1
    if outcome not in ("sent", "unchanged", "nothing included"):
        log.event("push", outcome=outcome)
    print(outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
