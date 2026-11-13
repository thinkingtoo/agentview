"""The merge desk from the phone: this server relays the desk page, and only it, to the laptop's sheaf hub.

The hub answers only to `127.0.0.1` and `localhost` and holds its own sign-in, so a phone cannot
reach it. The phone reaches this server through `tailscale serve` (:8445, see the README), and this
module stands between the two:

  * `plan` is the allowlist. The desk page's own document, and the `/_/` routes that page uses for
    the desk (its state, its event stream, a tick, a comment, a seen mark), each with the desk's
    address in its query or body. Everything else is refused before the hub is asked: another
    document, any other route, a path written crooked, a body that names another document.
  * The relay signs in to the hub itself (`sheaf signin-url`, the cookie it gives) and sends that
    cookie. Nothing the caller sent for authentication goes on, and the hub's cookie never comes
    back; the phone has no hub credential at all.
  * Host and Origin are rewritten on the request to the hub, so the hub's own check stays as it is
    for everything else. The guard in front of that is `server.Handler`'s: the Host must be this
    server's own or an `AGENTVIEW_EXTRA_ORIGINS` entry, and a POST must carry an Origin that is
    that same entry.

What a press from the phone can do is what a press on the laptop does: it ticks the item, and the
watcher (`deskwatch`) merges the commit that was pinned.
"""
import http.client
import json
import re
import subprocess
import threading
import urllib.parse
from typing import NamedTuple

import desk as deskcmd
import deskfile
import log

BODY_MAX = 64 * 1024
POSTS = ("tick", "comment", "seen")
GETS = ("doc", "live")
PAGE_ENTRY = "/desk"
TIMEOUT = 15                     # connecting, and any wait for the hub's answer
STREAM_TIMEOUT = 70              # the hub's event stream says something every 25 s
CHUNK = 8192
LAST_EVENT = re.compile(r"[0-9A-Za-z:._-]{1,64}")
PASSED = ("Content-Type", "Cache-Control", "Content-Security-Policy", "Referrer-Policy",
          "X-Content-Type-Options", "Permissions-Policy")


class Refused(Exception):
    def __init__(self, status, why):
        super().__init__(why)
        self.status, self.why = status, why


class Desk(NamedTuple):
    """Where the hub is, and the desk page's URL path on it and its address (`<root>/merge-desk.md`)."""
    port: int
    page: str
    address: str


class Plan(NamedTuple):
    method: str
    target: str                  # the path and query to ask the hub, built here and never copied
    body: "bytes | None"
    stream: bool


def claims(path):
    """Whether this path is the relay's to answer, which is for it to accept or refuse: the
    hub's `/_/` routes, the entry link, and any path that names the desk's file."""
    path = path.partition("?")[0]
    return path.startswith("/_/") or path in ("/_", PAGE_ENTRY) or path.endswith("/" + deskfile.NAME)


def _only_doc(query, address):
    """Whether the query is exactly `doc=<the desk's address>`: once, and nothing else."""
    try:
        got = urllib.parse.parse_qsl(query, keep_blank_values=True, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return False
    return got == [("doc", address)]


def _no_constant(name):
    raise ValueError(name)


def _post_body(route, data, address):
    if len(data) > BODY_MAX:
        raise Refused(413, "that is too much for the desk")
    try:
        obj = json.loads(data.decode("utf-8"), parse_constant=_no_constant)
    except (ValueError, UnicodeDecodeError):
        raise Refused(400, "expected JSON") from None
    if not isinstance(obj, dict):
        raise Refused(400, "expected a JSON object")
    if obj.get("doc") != address:
        raise Refused(404, "the desk relay answers for the desk page alone")
    if obj.get("tell", False) is not False:
        # A Tell runs the hub account's own agent session on the laptop: not a thing the desk page needs
        raise Refused(403, "the desk relay does not send a Tell")
    return json.dumps(obj).encode("utf-8")      # what was checked is what is sent, never the caller's own bytes


def plan(method, target, data, desk):
    """What to ask the hub for this request, or `Refused`. `desk` is a `Desk`, or a function that gives it:
    called only for a request that has the shape of one the relay serves, so a stranger's
    request costs no look at the hub. `target` is the raw request target; nothing in it is decoded
    before it is compared, and what is sent on is built from the desk's own address."""
    path, sep, query = target.partition("?")
    nope = Refused(404, "the desk relay answers for the desk page alone")
    if method == "GET":
        shaped = path == PAGE_ENTRY or path.endswith("/" + deskfile.NAME) or path in [f"/_/{g}" for g in GETS]
    elif method == "POST":
        shaped = path in [f"/_/{p}" for p in POSTS] and not sep
    else:
        shaped = False
    if not shaped:
        raise nope
    desk = desk() if callable(desk) else desk
    if method == "GET":
        if path == PAGE_ENTRY:
            return Plan("GET", PAGE_ENTRY, None, False)
        if path == desk.page:
            return Plan("GET", desk.page, None, False)
        if path in [f"/_/{g}" for g in GETS] and _only_doc(query, desk.address):
            return Plan("GET", f"{path}?doc={urllib.parse.quote(desk.address, safe='')}", None, path == "/_/live")
        raise nope
    return Plan("POST", path, _post_body(path.rpartition("/")[2], data or b"", desk.address), False)


class SheafHub:
    """The laptop's hub, as `sheaf` itself says where it is and how to sign in. Both are asked for
    once and kept; a hub that moved or a key that was rotated is asked for again."""

    def __init__(self):
        self._lock = threading.Lock()
        self._desk = None
        self._cookie = None

    def reset(self):
        with self._lock:
            self._desk = self._cookie = None

    def desk(self):
        with self._lock:
            if self._desk is None:
                self._desk = self._locate()
            return self._desk

    def _locate(self):
        try:
            said = deskcmd.page(browser=False)
        except (deskcmd.Refused, OSError) as why:
            raise Refused(503, f"the desk's hub could not be found: {why}") from None
        m = re.search(r"http://127\.0\.0\.1:(\d{1,5})(/[^\s?#]*)", said)
        if not m or not m.group(2).endswith("/" + deskfile.NAME) or not 0 < int(m.group(1)) < 65536:
            raise Refused(503, "sheaf did not say where the desk page is")
        page = m.group(2)
        return Desk(int(m.group(1)), page, urllib.parse.unquote(page[1:], errors="strict"))

    def cookie(self, fresh=False):
        """`name=value`, the hub's cookie for this relay."""
        with self._lock:
            if fresh or self._cookie is None:
                if self._desk is None:
                    self._desk = self._locate()
                self._cookie = self._sign_in(self._desk.port)
            return self._cookie

    @staticmethod
    def _sign_in(port):
        if not deskcmd.SHEAF:
            raise Refused(503, "sheaf was not found on PATH")
        try:
            got = subprocess.run([deskcmd.SHEAF, "signin-url"], capture_output=True, text=True,
                                 stdin=subprocess.DEVNULL, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as err:
            raise Refused(503, f"sheaf signin-url failed: {type(err).__name__}") from None
        m = re.search(r"http://127\.0\.0\.1:(\d{1,5})/_/open\?key=([A-Za-z0-9_-]{20,100})&next=/", got.stdout)
        if got.returncode != 0 or not m or int(m.group(1)) != port:
            raise Refused(503, "sheaf gave no sign-in for the desk's hub")
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=TIMEOUT)
            try:
                conn.request("GET", f"/_/open?key={m.group(2)}&next=/")
                res = conn.getresponse()
                res.read()
                cookie = (res.getheader("Set-Cookie") or "").partition(";")[0]
            finally:
                conn.close()
        except (OSError, http.client.HTTPException):
            raise Refused(503, "the desk's hub did not answer the sign-in") from None
        if res.status != 303 or not re.fullmatch(r"sheaf_\d{1,5}=[0-9a-f]{32,128}", cookie):
            raise Refused(503, "the desk's hub did not sign the relay in")
        return cookie


HUB = SheafHub()


def _ask(desk, plan_, cookie, last_event):
    """Send the plan to the hub. Host and Origin are the hub's own."""
    host = f"127.0.0.1:{desk.port}"
    headers = {"Host": host, "Cookie": cookie}
    if plan_.body is not None:
        headers.update({"Origin": f"http://{host}", "Content-Type": "application/json"})
    if plan_.stream and last_event and LAST_EVENT.fullmatch(last_event):
        headers["Last-Event-ID"] = last_event
    conn = http.client.HTTPConnection("127.0.0.1", desk.port, timeout=TIMEOUT)
    try:
        conn.request(plan_.method, plan_.target, body=plan_.body, headers=headers)
        res = conn.getresponse()
    except BaseException:
        conn.close()
        raise
    return conn, res


def _relay(plan_, desk, last_event):
    """The hub's answer to the plan, signing in again once when it says it does not know the relay."""
    for fresh in (False, True):
        conn, res = _ask(desk, plan_, HUB.cookie(fresh=fresh), last_event)
        if res.status != 401 or fresh:
            return conn, res
        res.read()
        conn.close()


def serve(h, method):
    """Answer the request `h` (a `server.Handler`) holds. The caller has judged Host and, for a POST, Origin."""
    path = h.path.partition("?")[0]
    try:
        data = None
        if method == "POST":
            try:
                length = int(h.headers.get("Content-Length", ""))
            except ValueError:
                raise Refused(411, "a POST needs its length") from None
            if not 0 <= length <= BODY_MAX:
                raise Refused(413, "that is too much for the desk")
            data = h.rfile.read(length)
        plan_ = plan(method, h.path, data, HUB.desk)
        desk = HUB.desk()
        if plan_.target == PAGE_ENTRY:
            h.send_response(302)
            h.send_header("Location", desk.page)
            h.send_header("Content-Length", "0")
            return h.end_headers()
        try:
            conn, res = _relay(plan_, desk, h.headers.get("Last-Event-ID"))
        except (OSError, http.client.HTTPException):
            if hasattr(HUB, "reset"):
                HUB.reset()
            raise Refused(503, "the laptop's sheaf hub did not answer") from None
    except Refused as why:
        log.event("desk-relay-refused", method=method, path=path, status=why.status, why=why.why)
        if why.status in (411, 413):
            h.close_connection = True
        return h.send_error(why.status, why.why)
    try:
        h.send_response(res.status)
        for name in PASSED:
            if res.getheader(name):
                h.send_header(name, res.getheader(name))
        if res.getheader("Content-Length") and not plan_.stream:
            h.send_header("Content-Length", res.getheader("Content-Length"))
        h.send_header("Connection", "close")
        h.close_connection = True
        h.end_headers()
        if plan_.method == "POST":
            log.event("desk-relay", path=path, status=res.status)
        if plan_.stream and conn.sock:
            conn.sock.settimeout(STREAM_TIMEOUT)
        while True:
            chunk = res.read1(CHUNK)
            if not chunk:
                break
            h.wfile.write(chunk)
            h.wfile.flush()
    except (OSError, http.client.HTTPException):
        pass                                   # the phone went away, or the hub did: nothing to tell either
    finally:
        conn.close()
