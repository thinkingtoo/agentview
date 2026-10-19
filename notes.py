"""The card's "notes" link: a look through the person's own notes, on a click
and at no other time.

The roster never searches, and a search is never where a context line comes
from. It is one search, for the project's name and its context line, and the
top three hits go to the page as text.

Where the notes live is not in this repo, which is public. As with the
embedder, the address and the key come from a local file in the person's own
folder, mode 0600 (a file others can read is refused, since it holds a key):

    ~/.config/tiroir/agentview-brain.env      or the path in $AGENTVIEW_BRAIN_ENV

        BRAIN_URL=http://HOST:PORT/...
        BRAIN_API_KEY=...

Without that file there is no search and the link says so. Nothing here reads
another program's configuration for a key.

Nothing in a reason says where the service is or what the key is: reasons
reach the page and the log.
"""
import os
from pathlib import Path

import localenv
from context import squash

DEFAULT_ENV = "~/.config/tiroir/agentview-brain.env"
ENV_VAR = "AGENTVIEW_BRAIN_ENV"
HITS = 3
QUERY_MAX = 400
TITLE_MAX, PATH_MAX, SNIPPET_MAX = 200, 300, 400
NOT_SET_UP = "notes search is not set up here"


class Unavailable(Exception):
    """A search cannot be made now. The text says why, and never says where."""


def config_path():
    return Path(os.environ.get(ENV_VAR) or DEFAULT_ENV).expanduser()


def settings(path=None):
    """(address, key) from the local config, or `Unavailable` saying what is
    wrong with it."""
    path = Path(path) if path else config_path()
    try:
        mode = path.stat().st_mode
    except OSError:
        raise Unavailable(NOT_SET_UP) from None
    if mode & 0o077:
        raise Unavailable("the notes config file is readable by others; chmod 600 it")
    try:
        env = localenv.read_env(path)
    except (OSError, UnicodeDecodeError):
        env = {}
    if not (env.get("BRAIN_URL") and env.get("BRAIN_API_KEY")):
        raise Unavailable("the notes config file lacks BRAIN_URL or BRAIN_API_KEY")
    return env["BRAIN_URL"], env["BRAIN_API_KEY"]


def searcher():
    """The function that looks through the notes: `query -> list of hits`.
    Raises `Unavailable` when there is none."""
    settings()
    # The config is in place; the call to the service is the one thing not
    # built, because it needs a service to be built against.
    raise Unavailable("notes search is configured, but this version cannot call it yet")


def _text(value, limit):
    return squash(value)[:limit] if isinstance(value, str) else ""


def tidy(hits):
    """The top hits as three short texts each. What the service sent beyond
    that is left out; a text is whatever the note said, kept as it was."""
    return [{"title": _text(h.get("title"), TITLE_MAX), "path": _text(h.get("path"), PATH_MAX),
             "snippet": _text(h.get("snippet"), SNIPPET_MAX)}
            for h in hits if isinstance(h, dict)][:HITS]


def search(query):
    """What a click on the link gets: `{"ok": True, "hits": [...]}`, or
    `{"ok": False, "reason": text}`. The only place a search is ever made."""
    query = squash(query)[:QUERY_MAX]
    if not query:
        return {"ok": False, "reason": "nothing to search for"}
    try:
        hits = searcher()(query)
    except Unavailable as why:
        return {"ok": False, "reason": str(why)}
    return {"ok": True, "hits": tidy(hits)}
