"""The merge desk from the phone: AgentView relays the desk page, and only it, to the laptop's sheaf hub.

Two layers. `plan` is the allowlist, a pure function: every path, query and body the page does not
use is refused there, so the table below is where a crafted request is tried. The rest runs the real
Handler in front of a stub hub on a port the system picks, and reads what the stub was sent: Host and
Origin rewritten to the hub's own, the hub's cookie put on by the relay and never the caller's, and the
guards of AgentView's own routes unchanged. No sheaf, no network beyond loopback.
"""
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import deskrelay
import server

TS = "tiroir-xps-15-7590.tail23d36e.ts.net"
ENTRY = f"https://{TS}:8445"
PAGE = "/agentview/merge-desk.md"
ADDRESS = "agentview/merge-desk.md"
DESK = deskrelay.Desk(port=4242, page=PAGE, address=ADDRESS)


def body(**fields):
    return json.dumps({"doc": ADDRESS, **fields}).encode()


class Plan(unittest.TestCase):
    def ok(self, method, target, data=None):
        return deskrelay.plan(method, target, data, DESK)

    def refused(self, method, target, data=None):
        with self.assertRaises(deskrelay.Refused, msg=f"{method} {target}") as caught:
            self.ok(method, target, data)
        return caught.exception.status

    def test_the_page_and_the_routes_it_uses_pass(self):
        self.assertEqual(self.ok("GET", PAGE).target, PAGE)
        self.assertEqual(self.ok("GET", f"/_/doc?doc={ADDRESS.replace('/', '%2F')}").target, f"/_/doc?doc=agentview%2Fmerge-desk.md")
        self.assertEqual(self.ok("GET", "/_/live?doc=agentview%2Fmerge-desk.md").stream, True)
        for route in ("tick", "comment", "seen"):
            plan = self.ok("POST", f"/_/{route}", body(action=0, word="Merge", op="reply"))
            self.assertEqual((plan.target, plan.stream), (f"/_/{route}", False))

    def test_a_comment_passes_with_each_of_the_five_ops_and_with_no_other(self):
        # Decision (Tarek, 2026-11-14): only Thierry's own devices reach the relay, and he resolves and edits his
        # comments from the phone, so all five of the hub's ops pass; a sixth is refused here, not left to the hub
        for op in ("add", "reply", "status", "edit", "delete"):
            with self.subTest(op=op):
                self.assertEqual(self.ok("POST", "/_/comment", body(op=op, id="c1")).target, "/_/comment")
        for op in ("purge", "Reply", "reply ", "", None, 1, ["reply"], {"op": "reply"}):
            with self.subTest(op=op):
                self.assertEqual(self.refused("POST", "/_/comment", body(op=op, id="c1")), 400)
        self.assertEqual(self.refused("POST", "/_/comment", body(id="c1")), 400)

    def test_the_page_is_asked_without_a_query(self):
        self.assertEqual(self.ok("GET", PAGE + "?next=/other.md").target, PAGE)

    def test_every_other_document_and_page_is_refused(self):
        for target in ("/", "/agentview/other.md", "/other/merge-desk.md", "/agentview/", "/agentview",
                       PAGE + "/", PAGE + "x", "/AGENTVIEW/merge-desk.md", "/agentview/Merge-Desk.md",
                       "//agentview/merge-desk.md", "/agentview//merge-desk.md", "/./agentview/merge-desk.md",
                       "/agentview/../agentview/merge-desk.md", "/agentview/%2e%2e/agentview/merge-desk.md",
                       "/agentview%2Fmerge-desk.md", "/agentview/merge%2Ddesk.md", "/agentview/merge-desk.md%00",
                       "/agentview/merge-desk.md%2f", "/x/../agentview/merge-desk.md", "/_/../agentview/merge-desk.md",
                       "http://127.0.0.1:4242/agentview/merge-desk.md", "agentview/merge-desk.md", ""):
            with self.subTest(target=target):
                self.assertEqual(self.refused("GET", target), 404)

    def test_every_route_the_page_does_not_need_is_refused(self):
        for target in ("/_/index.json", "/_/health", "/_/open?key=x&next=/", "/_/open?nonce=x", "/_/mount?doc=" + ADDRESS,
                       "/_/mount.js", "/_/jobs", "/_/session", "/_/export", "/_/transcribe", "/_/live",
                       "/_/live?list=1", "/_/", "/_", "/_/doc", "/_/%64oc?doc=" + ADDRESS, "/_/doc/?doc=" + ADDRESS,
                       "/_/DOC?doc=" + ADDRESS, "/_/doc%2f?doc=" + ADDRESS):
            with self.subTest(target=target):
                self.assertEqual(self.refused("GET", target), 404)
        for route in ("save", "pin", "tell", "target", "cancel", "jump", "export", "diag", "render", "forget", "stop",
                      "rotate", "signin", "restarting", "mcp", "code", "sessions", "transcribe", "open", "nothing"):
            with self.subTest(post=route):
                self.assertEqual(self.refused("POST", f"/_/{route}", body()), 404)

    def test_the_doc_must_be_the_desk_in_query_and_body(self):
        for target in ("/_/doc?doc=other/doc.md", "/_/doc?doc=", "/_/doc?doc=agentview/merge-desk.md/",
                       "/_/doc?doc=agentview/../agentview/merge-desk.md", "/_/doc?doc=AGENTVIEW/merge-desk.md",
                       "/_/doc?doc=agentview/merge-desk.md&doc=other.md", "/_/doc?doc=other.md&doc=agentview/merge-desk.md",
                       "/_/doc?doc=agentview/merge-desk.md&list=1", "/_/doc?doc=agentview/merge-desk.md&member=x",
                       "/_/live?doc=agentview/merge-desk.md&doc=x", "/_/live?doc=agentview/merge-desk.md%00"):
            with self.subTest(target=target):
                self.assertEqual(self.refused("GET", target), 404)
        for route in ("tick", "comment", "seen"):
            for data in (b'{"doc": "other.md"}', b'{}', b'{"doc": ["agentview/merge-desk.md"]}', b'{"doc": null}',
                         b'{"doc": "agentview/merge-desk.md/"}', b'{"doc": "agentview/merge-desk.md", "doc": "other.md"}',
                         b'{"Doc": "agentview/merge-desk.md"}',
                         b'[]', b'"agentview/merge-desk.md"', b'not json', b'', b'{"doc": "agentview/merge-desk.md"'):
                with self.subTest(route=route, data=data):
                    self.assertIn(self.refused("POST", f"/_/{route}", data), (400, 404))

    def test_a_body_nested_past_the_parser_is_refused_not_dropped(self):
        self.assertEqual(self.refused("POST", "/_/tick", b"[" * 60000), 400)

    def test_a_post_with_a_query_is_refused(self):
        for route in ("tick", "comment", "seen"):
            self.assertEqual(self.refused("POST", f"/_/{route}?doc=other.md", body()), 404)

    def test_what_the_doc_check_read_is_what_is_sent(self):
        # a body with the doc twice is read by the hub as its last one: the check reads the same, and the
        # bytes sent are the parsed object written again, never the bytes the caller chose
        plan = self.ok("POST", "/_/tick", b'{"doc": "other.md", "doc": "agentview/merge-desk.md", "action": 1}')
        self.assertEqual(json.loads(plan.body), {"doc": ADDRESS, "action": 1})
        self.assertEqual(plan.body.count(b'"doc"'), 1)
        self.assertEqual(self.refused("POST", "/_/tick", b'{"doc": "agentview/merge-desk.md", "doc": "other.md"}'), 404)

    def test_a_comment_never_tells_the_session(self):
        # `tell: true` makes the hub run the hub account's own agent session: not a thing the desk page needs
        for tell in (True, "yes", 1, "tell", {"a": 1}):
            with self.subTest(tell=tell):
                self.assertEqual(self.refused("POST", "/_/comment", body(op="reply", body="x", tell=tell)), 403)
        for fields in ({}, {"tell": False}):
            self.assertEqual(self.ok("POST", "/_/comment", body(op="reply", body="x", **fields)).target, "/_/comment")

    def test_the_wrong_method_is_refused(self):
        for method, target in (("POST", PAGE), ("POST", f"/_/doc?doc={ADDRESS}"), ("GET", "/_/tick"), ("GET", "/_/comment"),
                               ("PUT", "/_/tick"), ("DELETE", "/_/tick"), ("HEAD", PAGE), ("OPTIONS", "/_/tick")):
            with self.subTest(method=method, target=target):
                self.assertIn(self.refused(method, target, body() if method in ("POST", "PUT", "DELETE") else None), (404, 405))

    def test_a_body_too_big_is_refused(self):
        self.assertEqual(self.refused("POST", "/_/comment", body(op="add", body="x" * deskrelay.BODY_MAX)), 413)


class StubHub(BaseHTTPRequestHandler):
    """What the laptop's hub would answer, and a record of what it was sent."""
    seen = []
    stream_gate = None

    def _record(self, data=b""):
        type(self).seen.append({"method": self.command, "path": self.path, "headers": dict(self.headers.items()), "body": data})

    def do_GET(self):
        self._record()
        if self.path.startswith("/_/live"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Set-Cookie", "stub=1")
            self.end_headers()
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
            type(self).stream_gate.wait(10)
            self.wfile.write(b"data: late\n\n")
            return
        if self.headers.get("Cookie") != "sheaf_4242=good":
            return self._send(401, b"not signed in", "text/plain")
        self._send(200, b"<html>desk</html>", "text/html; charset=utf-8")

    def do_POST(self):
        data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._record(data)
        if self.headers.get("Cookie") != "sheaf_4242=good":
            return self._send(401, b"not signed in", "text/plain")
        self._send(200, b'{"ok": true}', "application/json")

    def _send(self, status, data, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Set-Cookie", "stub=1")
        self.send_header("Location", "http://evil.example/")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class FakeHub:
    """The laptop's hub as the relay sees it: where it is, and the cookie that signs in."""
    def __init__(self, port):
        self.port, self.cookies, self.rejected, self.resets = port, ["sheaf_4242=stale", "sheaf_4242=good"], 0, 0
        self.generation = 0

    def reset(self, seen=None):
        self.resets += 1

    def desk(self):
        return deskrelay.Desk(port=self.port, page=PAGE, address=ADDRESS)

    def cookie(self, fresh=False):
        if fresh:
            self.rejected += 1
        return self.cookies[1 if self.rejected else 0]


class Relayed(unittest.TestCase):
    def setUp(self):
        StubHub.seen, StubHub.stream_gate = [], threading.Event()
        self.addCleanup(StubHub.stream_gate.set)
        self.stub = ThreadingHTTPServer(("127.0.0.1", 0), StubHub)
        threading.Thread(target=self.stub.serve_forever, daemon=True).start()
        self.addCleanup(self.stub.server_close)
        self.addCleanup(self.stub.shutdown)
        self.hub = FakeHub(self.stub.server_port)
        for target, name, value in ((deskrelay, "HUB", self.hub), (server, "page", lambda: "<html>fleet</html>")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"AGENTVIEW_EXTRA_ORIGINS": ENTRY})
        env.start()
        self.addCleanup(env.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_port

    def call(self, method, target, data=None, host=f"{TS}:8445", origin=ENTRY, headers=None, read=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        sent = {"Host": host, **(headers or {})}
        if origin is not None:
            sent["Origin"] = origin
        if data is not None:
            sent["Content-Type"] = "application/json"
        conn.request(method, target, body=data, headers=sent)
        res = conn.getresponse()
        return res, (res.read() if read else None)

    def test_the_page_comes_through_with_the_hubs_own_host_and_the_relays_cookie(self):
        res, data = self.call("GET", PAGE)
        self.assertEqual((res.status, data), (200, b"<html>desk</html>"))
        sent = StubHub.seen[-1]
        self.assertEqual(sent["headers"]["Host"], f"127.0.0.1:{self.stub.server_port}")
        self.assertEqual(sent["headers"]["Cookie"], "sheaf_4242=good")

    def test_a_press_reaches_the_hub_with_the_hubs_own_origin(self):
        res, data = self.call("POST", "/_/tick", body(action=0, word="Merge", hash="h"))
        self.assertEqual((res.status, json.loads(data)), (200, {"ok": True}))
        sent = StubHub.seen[-1]
        self.assertEqual(sent["path"], "/_/tick")
        self.assertEqual(sent["headers"]["Host"], f"127.0.0.1:{self.stub.server_port}")
        self.assertEqual(sent["headers"]["Origin"], f"http://127.0.0.1:{self.stub.server_port}")
        self.assertEqual(json.loads(sent["body"]), {"doc": ADDRESS, "action": 0, "word": "Merge", "hash": "h"})

    def test_what_the_caller_holds_never_reaches_the_hub_and_what_the_hub_holds_never_reaches_the_caller(self):
        res, _ = self.call("GET", PAGE, headers={"Cookie": "sheaf_4242=mine", "X-Sheaf-Key": "k", "Authorization": "Bearer t",
                                                 "X-Forwarded-For": "100.1.2.3", "Referer": "https://x/"})
        sent = StubHub.seen[-1]["headers"]
        self.assertNotIn("mine", sent.get("Cookie", ""))
        for name in ("X-Sheaf-Key", "Authorization", "X-Forwarded-For", "Referer"):
            self.assertNotIn(name, sent)
        for name in ("Set-Cookie", "Location"):
            self.assertIsNone(res.getheader(name))

    def test_a_cookie_the_hub_no_longer_takes_is_replaced_once(self):
        res, data = self.call("GET", PAGE)
        self.assertEqual(res.status, 200)
        self.assertEqual([r["headers"].get("Cookie") for r in StubHub.seen], ["sheaf_4242=stale", "sheaf_4242=good"])
        self.assertEqual(self.hub.rejected, 1)

    def test_another_origin_or_host_gets_nothing_and_the_hub_is_not_asked(self):
        cases = [("GET", PAGE, dict(host="rebound.attacker.example")), ("GET", PAGE, dict(host=f"{TS}:8446")),
                 ("GET", PAGE, dict(host=f"{TS}.attacker.example:8445")), ("GET", "/_/doc?doc=" + ADDRESS, dict(host="evil:8445"))]
        for origin in ("https://evil.example", "null", f"http://{TS}:8445", f"https://{TS}:8446", ENTRY + "/x", ""):
            cases.append(("POST", "/_/tick", dict(origin=origin, data=body(action=0, word="Merge"))))
        cases.append(("POST", "/_/tick", dict(origin=None, data=body(action=0, word="Merge"))))
        cases.append(("POST", "/_/tick", dict(host="rebound.attacker.example", origin="https://rebound.attacker.example",
                                              data=body(action=0, word="Merge"))))
        for method, target, kwargs in cases:
            with self.subTest(method=method, target=target, **{k: v for k, v in kwargs.items() if k != "data"}):
                res, _ = self.call(method, target, **kwargs)
                self.assertEqual(res.status, 403)
        self.assertEqual(StubHub.seen, [])

    def test_a_refused_request_never_reaches_the_hub(self):
        for method, target, data in (("GET", "/agentview/other.md", None), ("GET", "/_/index.json", None),
                                     ("GET", "/_/open?key=x", None), ("GET", "/_/live", None),
                                     ("POST", "/_/save", body(text="x")), ("POST", "/_/jump", body()),
                                     ("POST", "/_/tick", b'{"doc": "other.md"}'),
                                     ("POST", "/_/comment", body(op="reply", body="x", tell=True))):
            with self.subTest(method=method, target=target):
                res, _ = self.call(method, target, data)
                self.assertIn(res.status, (403, 404))
        self.assertEqual(StubHub.seen, [])

    def test_the_local_names_reach_the_desk_too_but_a_post_still_needs_its_own_origin(self):
        res, _ = self.call("GET", PAGE, host=f"127.0.0.1:{self.port}", origin=None)
        self.assertEqual(res.status, 200)
        res, _ = self.call("POST", "/_/tick", body(action=0, word="Merge"), host=f"127.0.0.1:{self.port}",
                           origin=f"http://127.0.0.1:{self.port}")
        self.assertEqual(res.status, 200)
        res, _ = self.call("POST", "/_/tick", body(action=0, word="Merge"), host=f"127.0.0.1:{self.port}", origin=ENTRY)
        self.assertEqual(res.status, 403)

    def test_the_guards_of_agentviews_own_routes_are_as_they_were(self):
        for method, target, kwargs in (("GET", "/api/roster", dict(host="rebound.attacker.example")),
                                       ("POST", "/api/paste_done", dict(origin="https://evil.example", data=b"{}")),
                                       ("POST", "/api/paste_done", dict(data=b"{}")),            # the page's X-Fleet is missing
                                       ("POST", "/api/jump", dict(data=b"{}"))):
            with self.subTest(target=target):
                res, _ = self.call(method, target, **kwargs)
                self.assertEqual(res.status, 403)

    def test_the_desk_route_sends_the_phone_to_the_page(self):
        res, _ = self.call("GET", "/desk")
        self.assertEqual((res.status, res.getheader("Location")), (302, PAGE))

    def test_the_event_stream_is_passed_on_as_it_comes(self):
        res, _ = self.call("GET", f"/_/live?doc={ADDRESS.replace('/', '%2F')}", read=False)
        self.assertEqual(res.status, 200)
        self.assertEqual(res.getheader("Content-Type"), "text/event-stream")
        self.assertIsNone(res.getheader("Set-Cookie"))
        self.assertEqual(res.fp.readline(), b"retry: 2000\n")             # before the hub has ended the stream
        StubHub.stream_gate.set()

    def test_a_quiet_stream_is_held_open_past_the_timeout_of_a_press(self):
        with mock.patch.object(deskrelay, "ASK_TIMEOUT", 0.3):
            res, _ = self.call("GET", f"/_/live?doc={ADDRESS.replace('/', '%2F')}", read=False)
            self.assertEqual(res.fp.readline(), b"retry: 2000\n")
            time.sleep(1.0)                                   # longer than ASK_TIMEOUT, shorter than the hub's keepalive
            StubHub.stream_gate.set()
            self.assertEqual((res.fp.readline(), res.fp.readline()), (b"\n", b"data: late\n"))

    def test_a_hub_that_is_not_there_is_a_503_not_a_hang(self):
        self.stub.shutdown()
        self.stub.server_close()
        res, _ = self.call("GET", PAGE)
        self.assertEqual(res.status, 503)
        self.assertEqual(self.hub.resets, 1)

    def test_a_reason_sheaf_wrote_in_more_than_latin_1_is_still_answered(self):
        def locate():
            raise deskrelay.Refused(503, "sheaf open failed: " + "x" * 190 + "\u2026 and more")
        self.hub.desk = locate
        res, _ = self.call("GET", PAGE)
        self.assertEqual(res.status, 503)

    def test_a_hub_slower_than_the_press_timeout_is_a_504_and_the_hub_is_not_forgotten(self):
        with mock.patch.object(deskrelay, "ASK_TIMEOUT", 0.3), \
                mock.patch.object(StubHub, "do_POST", lambda self: time.sleep(1.5)):
            res, _ = self.call("POST", "/_/tick", body(action=0, word="Merge"))
        self.assertEqual(res.status, 504)
        self.assertEqual(self.hub.resets, 0)

    def test_a_body_that_never_comes_is_given_up_on(self):
        with mock.patch.object(deskrelay, "READ_TIMEOUT", 0.3):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            self.addCleanup(conn.close)
            conn.putrequest("POST", "/_/tick", skip_host=True)
            for k, v in (("Host", f"{TS}:8445"), ("Origin", ENTRY), ("Content-Length", "500")):
                conn.putheader(k, v)
            conn.endheaders()
            self.assertEqual(conn.getresponse().status, 408)


class TheHubsOps(unittest.TestCase):
    @staticmethod
    def sheaf_python():
        """The interpreter of the `sheaf` the relay runs (`deskcmd.SHEAF`, found on PATH): the one its script names on
        its first line. (None, why) when there is none to ask."""
        exe = deskrelay.deskcmd.SHEAF
        if not exe:
            return None, "sheaf is not on PATH here, so the relay would not find it either"
        try:
            first = Path(exe).read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
        except OSError as why:
            return None, f"{exe} cannot be read: {why}"
        if not first.startswith("#!") or not Path(first[2:].strip()).is_file():
            return None, f"{exe} does not start with the path of its Python (first line: {first[:80]!r})"
        return first[2:].strip(), ""

    def test_the_relays_comment_ops_are_the_ones_of_the_hub_the_desk_runs_on(self):
        # COMMENT_OPS is a copy of sheaf's hub/handler.py OPS: a sixth op added there must fail here, not be
        # refused by the relay without anyone noticing
        python, why = self.sheaf_python()
        if python is None:
            self.skipTest(why)
        got = subprocess.run([python, "-I", "-c", "from sheafmd.hub.handler import OPS; print(*OPS)"],
                             capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(tuple(got.stdout.split()), deskrelay.COMMENT_OPS)

    def test_a_sheaf_that_is_not_there_says_why_it_skips(self):
        with mock.patch.object(deskrelay.deskcmd, "SHEAF", None):
            self.assertEqual(self.sheaf_python()[0], None)
            self.assertIn("not on PATH", self.sheaf_python()[1])
        with mock.patch.object(deskrelay.deskcmd, "SHEAF", str(Path(__file__))):
            self.assertIn("does not start with", self.sheaf_python()[1])



class HubLock(unittest.TestCase):
    """`SheafHub` asks `sheaf` where the hub is and for a sign-in: each can take a minute. What it has
    kept is never behind that wait, and devices that ask while it runs share the one answer."""

    def hub(self, locate=None, sign_in=None):
        hub = deskrelay.SheafHub()
        for name, fn in (("_locate", locate), ("_sign_in", sign_in)):
            if fn:
                patcher = mock.patch.object(deskrelay.SheafHub, name, fn if name == "_locate" else staticmethod(fn))
                patcher.start()
                self.addCleanup(patcher.stop)
        return hub

    def in_threads(self, count, call):
        out, errs = [], []

        def run():
            try:
                out.append(call())
            except BaseException as err:
                errs.append(err)
        threads = [threading.Thread(target=run, daemon=True) for _ in range(count)]
        for t in threads:
            t.start()
        return threads, out, errs

    def test_what_is_kept_is_answered_while_the_hub_is_being_signed_in_to(self):
        gate, started = threading.Event(), threading.Event()
        self.addCleanup(gate.set)

        def sign_in(port):
            started.set()
            gate.wait(10)
            return "sheaf_4242=new"
        hub = self.hub(locate=lambda self_: DESK._replace(port=4242), sign_in=sign_in)
        self.assertEqual(hub.desk().port, 4242)
        (t,), out, _ = self.in_threads(1, lambda: hub.cookie())
        self.assertTrue(started.wait(5))
        began = time.monotonic()
        self.assertEqual(hub.desk().port, 4242)                    # the desk is kept: no wait for the sign-in
        self.assertLess(time.monotonic() - began, 1.0)
        gate.set()
        t.join(5)
        self.assertEqual(out, ["sheaf_4242=new"])

    def test_devices_asking_while_sheaf_open_runs_share_that_one_run(self):
        gate, runs = threading.Event(), []
        self.addCleanup(gate.set)

        def locate(self_):
            runs.append(1)
            gate.wait(10)
            raise deskrelay.Refused(503, "the desk's hub could not be found: slow")
        hub = self.hub(locate=locate)
        first, out, errs = self.in_threads(1, hub.desk)
        while not runs:
            time.sleep(0.01)
        more, _, more_errs = self.in_threads(4, hub.desk)                      # these ask while the first run is going
        threads = first + more
        time.sleep(0.3)
        gate.set()
        for t in threads:
            t.join(5)
        errs += more_errs
        self.assertEqual((len(runs), len(errs)), (1, 5))     # not five runs, not five waits one after the other
        self.assertTrue(all(isinstance(e, deskrelay.Refused) and e.status == 503 for e in errs))

    def test_a_failed_run_is_not_kept_and_the_next_request_tries_again(self):
        answers = [deskrelay.Refused(503, "down"), DESK]

        def locate(self_):
            got = answers.pop(0)
            if isinstance(got, Exception):
                raise got
            return got
        hub = self.hub(locate=locate)
        with self.assertRaises(deskrelay.Refused):
            hub.desk()
        self.assertEqual(hub.desk(), DESK)

    def test_a_reset_while_a_run_is_going_is_not_undone_by_its_late_answer(self):
        gate, started, runs = threading.Event(), threading.Event(), []
        self.addCleanup(gate.set)

        def locate(self_):
            runs.append(1)
            started.set()
            if len(runs) == 1:
                gate.wait(10)
            return DESK._replace(port=4000 + len(runs))
        hub = self.hub(locate=locate)
        (t,), out, _ = self.in_threads(1, hub.desk)
        self.assertTrue(started.wait(5))
        hub.reset()                                                   # a 503 elsewhere: what was asked is out of date
        gate.set()
        t.join(5)
        self.assertEqual(hub.desk().port, 4002)                       # the late answer was not kept; it asked again

    def test_a_device_that_joined_a_run_before_a_reset_does_not_take_that_runs_late_answer(self):
        gate, started, runs = threading.Event(), threading.Event(), []
        self.addCleanup(gate.set)

        def locate(self_):
            runs.append(1)
            n = len(runs)
            started.set()
            if n == 1:
                gate.wait(10)
            return DESK._replace(port=4000 + n)
        hub = self.hub(locate=locate)
        (leader,), led, _ = self.in_threads(1, hub.desk)
        self.assertTrue(started.wait(5))
        (follower,), followed, _ = self.in_threads(1, hub.desk)      # joins the first run
        time.sleep(0.2)
        hub.reset()                                                   # the hub moved: that run's answer is out of date
        gate.set()
        leader.join(5)
        follower.join(5)
        self.assertEqual([d.port for d in followed], [4002])          # it asked again; it did not take 4001
        self.assertEqual(len(runs), 2)

    def test_a_run_that_failed_is_every_waiting_devices_answer_even_after_a_reset(self):
        # the first device to be told 503 resets the hub; the others, waking after it, take the same failure
        # rather than each starting a run of its own that can take a minute
        gate, runs = threading.Event(), []
        self.addCleanup(gate.set)

        def locate(self_):
            runs.append(1)
            gate.wait(10)
            raise deskrelay.Refused(503, "the desk's hub could not be found: down")
        hub = self.hub(locate=locate)
        first, _, errs = self.in_threads(1, hub.desk)
        while not runs:
            time.sleep(0.01)
        more, _, more_errs = self.in_threads(3, hub.desk)
        time.sleep(0.2)
        hub.reset()                                                   # what the first 503 does
        gate.set()
        for t in first + more:
            t.join(5)
        errs += more_errs
        self.assertEqual((len(runs), len(errs)), (1, 4))
        self.assertTrue(all(isinstance(e, deskrelay.Refused) and e.status == 503 for e in errs))

    def test_a_device_sent_round_again_by_resets_that_keep_coming_gives_up_with_a_503(self):
        # each run a device joins is reset before it ends, over and over: it asks again three times, then is told 503
        class Watched(threading.Event):
            def __init__(self):
                super().__init__()
                self.waited = threading.Event()

            def wait(self, timeout=None):
                self.waited.set()
                return super().wait(timeout)
        hub = self.hub(locate=lambda self_: self.fail("a follower starts no run of its own"))

        def run_begun():
            flight = deskrelay._Flight(hub._generation)
            flight.done = Watched()
            with hub._lock:
                hub._flights["desk"] = flight
            return flight
        flight = run_begun()
        (t,), out, errs = self.in_threads(1, hub.desk)
        rounds = 0
        while rounds < 10 and flight.done.waited.wait(1):
            rounds += 1
            hub.reset()                                               # the hub moved again: this run is out of date
            nxt = run_begun()
            flight.done.set()
            flight = nxt
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(rounds, 3)
        self.assertEqual((out, len(errs)), ([], 1))
        self.assertTrue(isinstance(errs[0], deskrelay.Refused) and errs[0].status == 503)


    def test_a_late_503_for_an_older_run_does_not_reset_again(self):
        hub = self.hub(locate=lambda self_: DESK)
        hub.reset(0)                                                  # the first 503 for the run of generation 0
        hub.reset(0)                                                  # a follower of that run, told the same 503 late
        self.assertEqual(hub._generation, 1)
        hub.reset(1)                                                  # a 503 for the current generation does count
        self.assertEqual(hub._generation, 2)

    def test_a_device_told_the_run_went_out_of_date_carries_the_old_generation(self):
        hub = self.hub(locate=lambda self_: self.fail("a follower starts no run of its own"))
        flight = deskrelay._Flight(hub._generation)
        hub._flights["desk"] = flight
        (t,), out, errs = self.in_threads(1, hub.desk)
        time.sleep(0.2)
        for _ in range(3):
            hub.reset()
            with hub._lock:
                hub._flights["desk"] = deskrelay._Flight(hub._generation)
            flight.done.set()
            flight = hub._flights["desk"]
            time.sleep(0.2)
        flight.done.set()
        t.join(5)
        self.assertEqual(len(errs), 1)
        before = hub._generation
        hub.reset(errs[0].generation)                                 # what serve() does with that 503
        self.assertEqual(hub._generation, before)                     # it saw an older generation: no bump

    def test_a_leader_whose_run_went_out_of_date_asks_again_instead_of_returning_it(self):
        gate, started, runs = threading.Event(), threading.Event(), []
        self.addCleanup(gate.set)

        def locate(self_):
            runs.append(1)
            n = len(runs)
            started.set()
            if n == 1:
                gate.wait(10)
            return DESK._replace(port=4000 + n)
        hub = self.hub(locate=locate)
        (t,), out, errs = self.in_threads(1, hub.desk)
        self.assertTrue(started.wait(5))
        hub.reset()                                                   # the hub moved while `sheaf open` ran
        gate.set()
        t.join(5)
        self.assertEqual(([d.port for d in out], errs, len(runs)), ([4002], [], 2))   # not the former port 4001

    def test_a_refusal_a_nested_run_already_tagged_keeps_its_generation(self):
        hub = self.hub()

        def make():
            raise deskrelay.Refused(503, "inner", generation=7)       # the desk run inside a cookie run, later than it
        with self.assertRaises(deskrelay.Refused) as caught:
            hub._ask("cookie", make)
        self.assertEqual(caught.exception.generation, 7)


class SharedFailureThroughServe(unittest.TestCase):
    """The real `SheafHub` behind `serve()`: the request path resets the hub on a 503, not the test by hand."""
    setUp = Relayed.setUp
    call = Relayed.call

    def test_requests_sharing_one_failed_run_reset_the_hub_once_and_start_no_second_run(self):
        gate, runs = threading.Event(), []
        self.addCleanup(gate.set)

        def locate(self_):
            runs.append(1)
            gate.wait(10)
            raise deskrelay.Refused(503, "the desk's hub could not be found: down")
        hub = deskrelay.SheafHub()
        patcher = mock.patch.object(deskrelay.SheafHub, "_locate", locate)
        patcher.start()
        self.addCleanup(patcher.stop)
        again = mock.patch.object(deskrelay, "HUB", hub)
        again.start()
        self.addCleanup(again.stop)
        got = []
        # EventSource reconnects and page loads arrive while the run is going
        threads = [threading.Thread(target=lambda: got.append(self.call("GET", PAGE)[0].status), daemon=True) for _ in range(5)]
        for t in threads:
            t.start()
            time.sleep(0.05)
        time.sleep(0.3)
        gate.set()
        for t in threads:
            t.join(10)
        self.assertEqual((sorted(got), len(runs), hub._generation), ([503] * 5, 1, 1))

    def test_reconnects_arriving_as_a_run_fails_start_one_new_run_and_do_not_reset_it(self):
        gates, runs = [threading.Event(), threading.Event()], []
        for g in gates:
            self.addCleanup(g.set)

        def locate(self_):
            runs.append(1)
            gates[len(runs) - 1].wait(10)
            raise deskrelay.Refused(503, "the desk's hub could not be found: down")
        hub = deskrelay.SheafHub()
        for patcher in (mock.patch.object(deskrelay.SheafHub, "_locate", locate), mock.patch.object(deskrelay, "HUB", hub)):
            patcher.start()
            self.addCleanup(patcher.stop)
        got = []
        spawn = lambda: threading.Thread(target=lambda: got.append(self.call("GET", PAGE)[0].status), daemon=True)
        first = [spawn() for _ in range(3)]
        for t in first:
            t.start()
        time.sleep(0.4)
        gates[0].set()                                                # the run fails: its followers wake one by one
        later = [spawn() for _ in range(3)]                           # EventSource reconnects keep arriving
        for t in later:
            t.start()
            time.sleep(0.02)
        time.sleep(0.4)
        gates[1].set()
        for t in first + later:
            t.join(10)
        self.assertEqual((sorted(got), len(runs), hub._generation), ([503] * 6, 2, 2))   # one run, one reset, per failure

    def test_a_dead_hub_found_after_another_request_reset_is_still_forgotten(self):
        dead = socket.socket()
        dead.bind(("127.0.0.1", 0))
        port = dead.getsockname()[1]
        dead.close()                                                  # nothing listens there
        hub, runs = deskrelay.SheafHub(), []

        def locate(self_):
            runs.append(1)
            if len(runs) == 1:
                hub.reset()                                           # another request's 503 lands while this one looks
            return DESK._replace(port=port)
        for patcher in (mock.patch.object(deskrelay.SheafHub, "_locate", locate), mock.patch.object(deskrelay, "HUB", hub)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assertEqual(self.call("GET", PAGE)[0].status, 503)
        self.assertEqual((len(runs), hub._generation), (2, 2))        # found in generation 1, failed there, reset from there


class StreamCap(unittest.TestCase):
    def test_one_client_holds_so_many_streams_and_no_more(self):
        streams = deskrelay.Streams(per_client=2, total=10)
        streams.take("100.1.1.1")
        streams.take("100.1.1.1")
        with self.assertRaises(deskrelay.Refused) as caught:
            streams.take("100.1.1.1")
        self.assertEqual(caught.exception.status, 429)
        streams.take("100.2.2.2")                                    # another device is not held back by the first
        streams.drop("100.1.1.1")
        streams.take("100.1.1.1")                                    # a stream that ended frees its place

    def test_the_streams_of_all_clients_together_have_a_cap(self):
        streams = deskrelay.Streams(per_client=5, total=3)
        for client in ("a", "b", "c"):
            streams.take(client)
        with self.assertRaises(deskrelay.Refused) as caught:
            streams.take("d")
        self.assertEqual(caught.exception.status, 429)

    def test_dropping_more_than_was_taken_is_harmless(self):
        streams = deskrelay.Streams(per_client=1, total=1)
        streams.drop("nobody")
        streams.take("a")
        with self.assertRaises(deskrelay.Refused):
            streams.take("b")


class WhereTheHubIs(unittest.TestCase):
    def test_a_malformed_answer_of_sheaf_open_is_a_503_and_not_an_exception(self):
        for said in (f"opened http://127.0.0.1:4242/agentview/%ff/{deskrelay.deskfile.NAME}\n",
                     f"opened http://127.0.0.1:4242/%c3%28/{deskrelay.deskfile.NAME}\n"):
            with self.subTest(said=said), mock.patch.object(deskrelay.deskcmd, "page", return_value=said):
                with self.assertRaises(deskrelay.Refused) as caught:
                    deskrelay.SheafHub()._locate()
                self.assertEqual(caught.exception.status, 503)


class StreamsThroughTheRelay(Relayed):
    LIVE = f"/_/live?doc={ADDRESS.replace('/', '%2F')}"

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(deskrelay, "STREAMS", deskrelay.Streams(per_client=2, total=10))
        patcher.start()
        self.addCleanup(patcher.stop)

    def open_stream(self, **kwargs):
        res, _ = self.call("GET", self.LIVE, read=False, **kwargs)
        return res

    def test_a_client_past_its_cap_is_told_to_wait_and_the_hub_is_not_asked(self):
        first, second = self.open_stream(), self.open_stream()
        self.assertEqual((first.status, second.status), (200, 200))
        asked = len(StubHub.seen)
        self.assertEqual(self.open_stream().status, 429)
        self.assertEqual(len(StubHub.seen), asked)
        self.assertEqual(self.call("GET", PAGE)[0].status, 200)       # the page itself is not a stream

    def test_the_refusal_of_a_stream_past_the_cap_says_when_to_try_again(self):
        self.open_stream(), self.open_stream()
        res = self.open_stream()
        self.assertEqual(res.status, 429)
        self.assertEqual(res.getheader("Retry-After"), str(deskrelay.RETRY_AFTER))
        self.assertGreater(deskrelay.RETRY_AFTER, 0)

    def test_a_place_is_free_again_when_a_stream_ends(self):
        first, second = self.open_stream(), self.open_stream()
        StubHub.stream_gate.set()
        for res in (first, second):
            res.read()                                                 # the hub ended it, the relay let go
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            res = self.open_stream()
            if res.status == 200:
                break
            res.read()
            time.sleep(0.05)
        self.assertEqual(res.status, 200)

    def test_a_place_is_free_again_when_the_hub_does_not_answer(self):
        self.stub.shutdown()
        self.stub.server_close()
        for _ in range(4):                                             # more than the cap: each failed one let go
            self.assertEqual(self.open_stream().status, 503)

    def test_the_client_is_the_address_the_proxy_saw_and_not_one_the_caller_wrote(self):
        h = mock.Mock(client_address=("127.0.0.1", 5555))
        h.headers = {"X-Forwarded-For": "6.6.6.6, 100.64.0.9"}
        self.assertEqual(deskrelay.client_of(h), "100.64.0.9")        # the last hop is the one our own proxy appended
        h.headers = {"X-Forwarded-For": "not an address"}
        self.assertEqual(deskrelay.client_of(h), "127.0.0.1")
        h.headers = {}
        self.assertEqual(deskrelay.client_of(h), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
