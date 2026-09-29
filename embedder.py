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

The index is built for one model. The service must say it is EmbeddingGemma at
768 dimensions and name both prompts; the bge-m3 service on the same machine
is refused, as is anything else. Which model made a vector is checked every
time a vector is made or used, before and after the call, never remembered:
a service that swaps its model between two calls must not put two models in
one comparison, or one index.

Nothing here raises anything but `Unavailable`. A caller that gets one carries
on without meaning: the keyword index answers alone and the page says so.
After a failure the embedder is left alone for BACKOFF seconds, so a box that
is off costs one slow search, not one per keystroke.
"""
import http.client
import json
import math
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

# The one model this index is built for, by the name its service reports (the
# size is not enough, other services also give 768; a name that merely contains
# the word is not enough either). A new export under another name is a change
# to make here, on purpose.
MODELS = ("google/embeddinggemma-300m",)
DIMENSIONS = 768

# A component of a unit vector is at most 1. Far beyond it is not a vector, and
# beyond float32's range it would turn into infinity when stored.
LARGEST = 1e6

# What makes two vectors comparable. Not the device, not the batch cap.
IDENTITY_FIELDS = ("model", "dimensions", "query_prompt", "document_prompt", "max_len")


class Unavailable(Exception):
    """The embedder cannot be used now. The text says why, and never says where."""


class Embedder:
    def __init__(self, url="", key="", problem=""):
        base = url.rstrip("/")
        self.base = base[: -len("/api/v1")] if base.endswith("/api/v1") else base
        self.key, self.problem = key, problem
        self.retry_at, self.last_error, self.dims = 0.0, "", 0
        self.where = None
        if not problem:
            try:
                self.where = urllib.parse.urlsplit(self.base)
                self.where.port                     # a port that is not a number raises here
                if self.where.scheme not in ("http", "https") or not self.where.hostname:
                    raise ValueError
            except ValueError:
                self.where = None
                self.problem = "EMBEDDER_URL in the embedder's config file is not a URL"

    # ------------------------------------------------------------ the wire

    def _call(self, method, path, body=None, read=None, connect=None):
        if self.problem:
            raise Unavailable(self.problem)
        if time.monotonic() < self.retry_at:
            raise Unavailable(f"{self.last_error} (not asked again for a while)")
        where = self.where
        cls = http.client.HTTPSConnection if where.scheme == "https" else http.client.HTTPConnection
        data = json.dumps(body).encode() if body is not None else None
        conn = None
        try:
            conn = cls(where.hostname, where.port, timeout=connect or CONNECT_TIMEOUT)
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
            if conn is not None:
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
        """The model as a string, from the service's model endpoint, asked
        every time. Vectors with different identities are never compared or
        stored together. Refuses a service that is not EmbeddingGemma at 768
        dimensions with both prompts named."""
        info = self._call("GET", "/model")
        model, dims = info.get("model"), info.get("dimensions")
        if not isinstance(model, str) or not isinstance(dims, int) or isinstance(dims, bool):
            self._fail("the embedder did not say which model it is")
        # Nothing the service says is repeated in a reason: it reaches the page and the log.
        if model not in MODELS:
            self._fail("the embedder is not the EmbeddingGemma service this index is built for")
        if dims != DIMENSIONS:
            self._fail(f"the embedder's vectors are not the {DIMENSIONS} dimensions this index is built for")
        if not all(isinstance(info.get(k), str) and info[k] for k in ("query_prompt", "document_prompt")):
            self._fail("the embedder does not name its query and document prompts")
        self.dims = dims
        return json.dumps({k: info.get(k) for k in IDENTITY_FIELDS}, sort_keys=True)

    # ------------------------------------------------------------ vectors

    @staticmethod
    def _number(x):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return False
        try:
            return math.isfinite(x) and abs(x) <= LARGEST
        except OverflowError:               # an integer too large for a float
            return False

    def _usable(self, vec):
        """A list of the right length holding finite numbers, and only those."""
        return isinstance(vec, list) and len(vec) == self.dims and all(map(self._number, vec))

    def query(self, text, identity):
        """The vector of a question, through the query endpoint. `identity` is
        that of the vectors it will be compared with: the embedder must be that
        model before the call and after it, or nothing is returned."""
        if self.identity() != identity:
            raise Unavailable("the vectors are from another model: the next update rebuilds them")
        got = self._call("POST", "/embed/text", {"text": text})
        if self.identity() != identity:
            self._fail("the embedder changed model while it was asked")
        vec = got.get("vector")
        if not self._usable(vec):
            self._fail("the embedder gave a vector this code cannot use")
        return vec

    def documents(self, texts, identity):
        """The vectors of stored passages, through the document endpoint, at
        most BATCH texts a call, in the order given. `identity` is that of the
        vectors already stored: each batch is checked against it before and
        after, and a batch made by another model is not returned."""
        out = []
        for i in range(0, len(texts), BATCH):
            chunk = texts[i:i + BATCH]
            if self.identity() != identity:
                self._fail("the embedder changed model in the middle of a run")
            got = self._call("POST", "/embed/batch", {"texts": chunk}, read=BATCH_TIMEOUT, connect=BATCH_CONNECT)
            if self.identity() != identity:
                self._fail("the embedder changed model while it was asked")
            vecs = got.get("vectors")
            if not isinstance(vecs, list) or len(vecs) != len(chunk) or not all(map(self._usable, vecs)):
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
