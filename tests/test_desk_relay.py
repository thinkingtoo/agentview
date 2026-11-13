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
            plan = self.ok("POST", f"/_/{route}", body(action=0, word="Merge"))
            self.assertEqual((plan.target, plan.stream), (f"/_/{route}", False))

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

    def reset(self):
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


if __name__ == "__main__":
    unittest.main()
