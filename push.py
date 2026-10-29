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
# own words and Claude Code's title. A line read from the prompt or the branch is not.
LINE_SOURCES = (working.OWN, working.DID, working.TITLE)
FLAGS = ("waiting", "ready", "tool", "stuck")
PASTE_ID = re.compile(r"[0-9a-f]{16}")       # as `paste.py` makes them
HIDDEN = "(hidden: looked like a credential)"
# The hub's limits (tiroir-fleet re-checks them): characters per field, and how many of each.
NAME_LEN, LINE_LEN, NEED_LEN = 60, 200, 200
QUESTION_LEN, LABEL_LEN, HINT_LEN, TITLE_LEN = 300, 60, 200, 120
MAX_COLUMNS, MAX_SESSIONS, MAX_QUESTIONS, MAX_OPTIONS, MAX_PASTES = 40, 40, 4, 6, 20


def say(value, limit):
    """A string as it may leave: checked whole for a credential shape before it
    is cut (a cut token no longer looks like one), then without control and
    format characters, and cut to `limit`."""
    if not isinstance(value, str):
        return ""
    if credentials.looks_secret(value):
        return HIDDEN
    return "".join(c for c in value if unicodedata.category(c) not in ("Cc", "Cf"))[:limit]


def projection(data, include):
    """The body the hub gets, from one roster (`poll.round`) and the projects
    named in `push.include`."""
    flags = {f.get("key"): f for f in data.get("flags", [])}
    # A column is its project's key, never its display name: two columns may share a name.
    wanted = set(include)
    return {"columns": [{"project": column["project"], "name": say(column.get("name"), NAME_LEN),
                         "sessions": [_session(t, flags.get(t.get("key"), {}))
                                      for t in column.get("sessions", [])[:MAX_SESSIONS]]}
                        for column in data.get("columns", []) if column.get("project") in wanted][:MAX_COLUMNS]}


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
        "since": t["stop"],
        "line": say(t.get("line"), LINE_LEN) if t.get("lineSource") in LINE_SOURCES else "",
        "need": say(t.get("need"), NEED_LEN),
        "question": question,
        "pastes": [{"id": p.get("id"), "title": say(p.get("title"), TITLE_LEN), "secret": p.get("secret") is True}
                   for p in t.get("pastes", [])
                   if isinstance(p.get("id"), str) and PASTE_ID.fullmatch(p["id"])][:MAX_PASTES],
    }


def state_path():
    return log.log_dir() / "push.json"


def _last(state):
    try:
        got = json.loads(Path(state).read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def once(*, include, read, post, token, url, state, now):
    """One round. `read` gives the roster, `token` the device token (None when
    there is none), and `post(url, token, body)` the hub's HTTP status. Says
    what it did: sent, unchanged, nothing included, no token, or refused <status>."""
    if not include:
        return "nothing included"
    columns = projection(read(), include)["columns"]
    digest = hashlib.sha256(json.dumps(columns, sort_keys=True).encode()).hexdigest()
    last = _last(state)
    if last.get("digest") == digest and now - last.get("sent", 0) < HEARTBEAT_MS:
        return "unchanged"
    secret = token()
    if not secret:
        return "no token"
    body = json.dumps({"v": VERSION, "at": now, "columns": columns}, ensure_ascii=False).encode("utf-8")
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
    with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
        return json.load(answer)


def post_body(url, token, body):
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            return answer.status
    except urllib.error.HTTPError as err:
        return err.code


def device_token():
    try:
        return vault.lookup(TOKEN_ATTRIBUTES)
    except vault.Unavailable as err:
        log.event("push", outcome="no token", why=str(err))
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["once"])
    parser.parse_args(argv)
    settings = fleet.config_value("push", {})
    settings = settings if isinstance(settings, dict) else {}
    include = [p for p in settings.get("include", []) if isinstance(p, str)] \
        if isinstance(settings.get("include"), list) else []
    try:
        outcome = once(include=include, read=read_roster, post=post_body, token=device_token,
                       url=settings.get("url") or URL, state=state_path(), now=int(time.time() * 1000))
    except (OSError, ValueError) as err:
        log.error("push", err)
        print(f"push: {type(err).__name__}", file=sys.stderr)
        return 1
    if outcome not in ("sent", "unchanged", "nothing included"):
        log.event("push", outcome=outcome)
    print(outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
