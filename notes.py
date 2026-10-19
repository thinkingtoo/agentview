"""The card's "notes" link: a look through the person's own notes, on a click
and at no other time.

The roster never searches, and a search is never where a context line comes
from. It is one search, for the project's name and its context line, and the
top three hits go to the page as text.

Where the notes live is not in this repo, which is public. As with the
embedder, the address and the key come from a local file in the person's own
folder, mode 0600 (a file others can read is refused, since it holds a key):

    ~/.config/tiroir/agentview-brain.env      or the path in $AGENTVIEW_BRAIN_ENV

        BRAIN_URL=...     the notes service's MCP address (the tiroir-library one)
        BRAIN_AUTH=...    the whole Authorization header value, "Bearer ..." included

Without that file there is no search and the link says so. Nothing here reads
another program's configuration for a key.

The search is MCP's streamable HTTP, as much of it as one search needs: start
a session, ask the `rag_search` tool, end the session. Three requests, one
connection each. A redirect is not followed and a proxy is not used, so the
key goes to the address in the file and nowhere else.

Nothing in a reason says where the service is, what the key is or what the
service said: reasons reach the page and the log.
"""
import http.client
import json
import os
import urllib.parse
from pathlib import Path, PurePosixPath

import localenv
from context import squash

DEFAULT_ENV = "~/.config/tiroir/agentview-brain.env"
ENV_VAR = "AGENTVIEW_BRAIN_ENV"
HITS = 3
QUERY_MAX = 400
CONNECT_TIMEOUT = 3.0   # the service is over Tailscale: a box that is off is found out here
CALL_TIMEOUT = 20.0     # ...and a search waits this long for each answer: it embeds the question first
REPLY_MAX = 1_000_000
PROTOCOL = "2025-06-18"
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
    url, auth = env.get("BRAIN_URL"), env.get("BRAIN_AUTH")
    if not (url and auth):
        raise Unavailable("the notes config file lacks BRAIN_URL or BRAIN_AUTH")
    if not _is_url(url):
        raise Unavailable("BRAIN_URL in the notes config file is not a URL")
    if not _is_header_value(auth):
        raise Unavailable("BRAIN_AUTH in the notes config file is not a header value")
    return url, auth


def _is_url(url):
    try:
        where = urllib.parse.urlsplit(url)
        where.port                                  # a port that is not a number raises here
    except ValueError:
        return False
    return where.scheme in ("http", "https") and bool(where.hostname)


def _is_header_value(value):
    return value.isascii() and all(c >= " " and c != "\x7f" for c in value)


def searcher():
    """The function that looks through the notes: `query -> list of hits`.
    Raises `Unavailable` when there is none. Nothing is asked until it is called."""
    url, auth = settings()
    where = urllib.parse.urlsplit(url)
    return lambda query: _ask(where, auth, query)


# ------------------------------------------------------------------ the wire

UNKNOWN = "the notes service gave an answer this code does not know"


def _call(where, headers, body=None, method="POST"):
    """One request on a connection of its own: (status, session id, text)."""
    cls = http.client.HTTPSConnection if where.scheme == "https" else http.client.HTTPConnection
    target = (where.path or "/") + (f"?{where.query}" if where.query else "")
    data = json.dumps(body).encode() if body is not None else None
    conn = None
    try:
        conn = cls(where.hostname, where.port, timeout=CONNECT_TIMEOUT)
        conn.connect()
        conn.sock.settimeout(CALL_TIMEOUT)
        conn.request(method, target, body=data, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.getheader("mcp-session-id"), resp.read(REPLY_MAX).decode("utf-8", "replace")
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise Unavailable(f"the notes service is unreachable ({type(exc).__name__})") from None
    finally:
        if conn is not None:
            conn.close()


def _accepted(status):
    if status in (401, 403):
        raise Unavailable("the notes service refused the key")
    if status not in (200, 202):
        raise Unavailable(f"the notes service answered {status}")


def _result(text):
    """The result in an answer, which is a JSON message or an event stream of them."""
    if not text.lstrip().startswith("{"):
        data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        text = data[-1] if data else ""
    try:
        message = json.loads(text)
    except ValueError:
        message = None
    if not isinstance(message, dict):
        raise Unavailable(UNKNOWN)
    if "error" in message:
        raise Unavailable("the notes service reported an error")
    if not isinstance(message.get("result"), dict):
        raise Unavailable(UNKNOWN)
    return message["result"]


def _hits(result):
    """The hits of a `rag_search` result as title, path and snippet. The service
    sends them as `original_location` and `chunk_text`, among other things."""
    if result.get("isError"):
        raise Unavailable("the notes search failed on the service")
    structured = result.get("structuredContent")
    found = structured.get("result") if isinstance(structured, dict) else None
    if not isinstance(found, list):
        content = result.get("content")
        if not isinstance(content, list):           # neither: not "no hits", an answer not understood
            raise Unavailable(UNKNOWN)
        found = []
        for part in content:
            try:
                found.append(json.loads(part["text"]))
            except (KeyError, TypeError, ValueError):
                pass
    return [_hit(h) for h in found if isinstance(h, dict)]


def _hit(hit):
    where = hit.get("original_location")
    where = where if isinstance(where, str) else ""
    return {"title": PurePosixPath(where).stem, "path": where, "snippet": hit.get("chunk_text")}


def _ask(where, auth, query):
    headers = {"Authorization": auth, "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    status, session, text = _call(where, headers, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                   "clientInfo": {"name": "agentview", "version": "0"}}})
    _accepted(status)
    _result(text)
    if session:
        headers["mcp-session-id"] = session
    try:
        _accepted(_call(where, headers, {"jsonrpc": "2.0", "method": "notifications/initialized"})[0])
        status, _, text = _call(where, headers, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "rag_search", "arguments": {"query": query, "top_k": HITS}}})
        _accepted(status)
        return _hits(_result(text))
    finally:
        if session:
            try:
                _call(where, headers, method="DELETE")
            except Unavailable:
                pass


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
