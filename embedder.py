#!/usr/bin/env python3
"""The embedder behind meaning search: EmbeddingGemma-300m (int4, 768
dimensions), a small HTTP service the owner runs on a machine of their own.

Where it lives is not in this repo, which is public. The address and the key
come from a local file, mode 0600 (a file others can read is refused, since
it holds a key):

    ~/.config/tiroir/agentview-embedder.env      or the path in $AGENTVIEW_EMBEDDER_ENV

        EMBEDDER_URL=http://HOST:PORT
        EMBEDDER_API_KEY=...

The model is asymmetric. A question goes to the query endpoint and a stored
passage to the document endpoint; the wrong one does not fail, it ranks worse
(36% less separation between right and wrong documents, the service's own
number). So the two paths are two methods here and nothing chooses between them.

Only text that is a passage, or a query, is ever sent. Never a name, a title,
a path or a project.

Nothing here raises anything but `Unavailable`. A caller that gets one carries
on without meaning: the keyword index answers alone and the page says so.
After a failure the embedder is left alone for BACKOFF seconds, so a box that
is off costs one slow search, not one per keystroke.
"""
import http.client
import json
import os
import time
import urllib.parse
from pathlib import Path

DEFAULT_ENV = "~/.config/tiroir/agentview-embedder.env"
ENV_VAR = "AGENTVIEW_EMBEDDER_ENV"
BATCH = 100              # the service refuses more texts than this in one call
BACKOFF = 30.0           # seconds to leave it alone after a failure
CONNECT_TIMEOUT = 0.5    # a search waits this long to reach the embedder. A box that is off is
                         # found out here, so the first search after it went down costs this much
QUERY_TIMEOUT = 1.5      # ...and this long for the question's vector. A live one answers in tens
                         # of milliseconds; it is slow only while it embeds a batch
BATCH_CONNECT = 5.0      # a backfill can afford to be patient
BATCH_TIMEOUT = 120.0    # a batch of long passages takes a couple of seconds
IDENTITY_TTL = 60.0      # how long the model's identity is trusted before it is asked again

# What makes two vectors comparable. Not the device, not the batch cap.
IDENTITY_FIELDS = ("model", "dimensions", "query_prompt", "document_prompt", "max_len")


class Unavailable(Exception):
    """The embedder cannot be used now. The text says why, and never says where."""


class Embedder:
    def __init__(self, url="", key="", problem=""):
        base = url.rstrip("/")
        self.base = base[: -len("/api/v1")] if base.endswith("/api/v1") else base
        self.key, self.problem = key, problem
        self.retry_at, self.last_error = 0.0, ""
        self._identity, self._identity_until = None, 0.0

    # ------------------------------------------------------------ the wire

    def _call(self, method, path, body=None, read=None, connect=None):
        if self.problem:
            raise Unavailable(self.problem)
        if time.monotonic() < self.retry_at:
            raise Unavailable(f"{self.last_error} (not asked again for a while)")
        where = urllib.parse.urlsplit(self.base)
        cls = http.client.HTTPSConnection if where.scheme == "https" else http.client.HTTPConnection
        data = json.dumps(body).encode() if body is not None else None
        conn = cls(where.hostname, where.port, timeout=connect or CONNECT_TIMEOUT)
        try:
            conn.connect()
            conn.sock.settimeout(read or QUERY_TIMEOUT)
            conn.request(method, f"{where.path.rstrip('/')}/api/v1{path}", body=data,
                         headers={"X-API-Key": self.key, "Content-Type": "application/json"})
            resp = conn.getresponse()
            status, raw = resp.status, resp.read()
        except (OSError, http.client.HTTPException, ValueError) as exc:
            # A refused or timed-out connection, a reset, a reply cut short.
            self._fail(f"the embedder is unreachable ({type(exc).__name__})")
        finally:
            conn.close()
        if status != 200:
            self._fail(f"the embedder answered {status}")
        try:
            got = json.loads(raw)
        except ValueError:
            got = None
        if not isinstance(got, dict):
            self._fail("the embedder gave an answer this code does not know")
        return got

    def _fail(self, why):
        self.last_error, self.retry_at = why, time.monotonic() + BACKOFF
        raise Unavailable(why)

    # ------------------------------------------------------------ what it is

    def identity(self):
        """The model as a string, from the service's model endpoint. Vectors
        with different identities are never compared or stored together."""
        if self._identity and time.monotonic() < self._identity_until:
            return self._identity
        info = self._call("GET", "/model")
        if not isinstance(info.get("model"), str) or not isinstance(info.get("dimensions"), int):
            self._fail("the embedder did not say which model it is")
        self._identity = json.dumps({k: info.get(k) for k in IDENTITY_FIELDS}, sort_keys=True)
        self._identity_until = time.monotonic() + IDENTITY_TTL
        return self._identity

    def dimensions(self):
        return json.loads(self.identity())["dimensions"]

    # ------------------------------------------------------------ vectors

    def query(self, text):
        """The vector of a question, through the query endpoint."""
        got = self._call("POST", "/embed/text", {"text": text})
        vec = got.get("vector")
        if not isinstance(vec, list) or len(vec) != self.dimensions():
            self._fail("the embedder gave a vector of the wrong size")
        return vec

    def documents(self, texts):
        """The vectors of stored passages, through the document endpoint, at
        most BATCH texts a call. In the order given."""
        out = []
        for i in range(0, len(texts), BATCH):
            chunk = texts[i:i + BATCH]
            got = self._call("POST", "/embed/batch", {"texts": chunk}, read=BATCH_TIMEOUT, connect=BATCH_CONNECT)
            vecs = got.get("vectors")
            if (not isinstance(vecs, list) or len(vecs) != len(chunk)
                    or any(not isinstance(v, list) or len(v) != self.dimensions() for v in vecs)):
                self._fail("the embedder gave vectors this code cannot use")
            out.extend(vecs)
        return out


# ------------------------------------------------------------ the local config

_LOADED = {}


def config_path():
    return Path(os.environ.get(ENV_VAR) or DEFAULT_ENV).expanduser()


def _read_env(path):
    got = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            got[name.strip()] = value.strip().strip("'\"")
    return got


def load(path=None):
    """The embedder the local config names. Always an Embedder: when there is
    no config, or it cannot be used, the Embedder says so on its first call.
    The same file gives the same Embedder, so its back-off outlives a request."""
    path = Path(path) if path else config_path()
    try:
        st = path.stat()
    except OSError:
        return Embedder(problem="no embedder is configured")
    stamp = (str(path), st.st_mtime_ns, st.st_size)
    if stamp in _LOADED:
        return _LOADED[stamp]
    if st.st_mode & 0o077:
        emb = Embedder(problem="the embedder's config file is readable by others; chmod 600 it")
    else:
        try:
            env = _read_env(path)
        except (OSError, UnicodeDecodeError):
            env = {}
        if env.get("EMBEDDER_URL") and env.get("EMBEDDER_API_KEY"):
            emb = Embedder(env["EMBEDDER_URL"], env["EMBEDDER_API_KEY"])
        else:
            emb = Embedder(problem="the embedder's config file lacks EMBEDDER_URL or EMBEDDER_API_KEY")
    _LOADED.clear()
    _LOADED[stamp] = emb
    return emb
