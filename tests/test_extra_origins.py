"""AGENTVIEW_EXTRA_ORIGINS: a name in front of the server, such as `tailscale serve`, let in
by an explicit list. Host and Origin must both name the same entry, scheme, host and port
compared exactly; the X-Fleet header is still needed on a POST. Unset, nothing extra passes.

A POST body is never JSON, so a request the guard lets through answers 400 and one it
refuses answers 403. A GET answers from a stub page.
"""
import http.client
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server

TS = "tiroir-xps-15-7590.tail23d36e.ts.net"
ENTRY = f"https://{TS}:8445"


class ExtraOrigins(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(server, "page", lambda: "<html></html>")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_port

    def env(self, value):
        patcher = mock.patch.dict(os.environ, {"AGENTVIEW_EXTRA_ORIGINS": value})
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, method, host, origin=None, fleet="1"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        headers = {"Host": host}
        if origin is not None:
            headers["Origin"] = origin
        if fleet is not None:
            headers["X-Fleet"] = fleet
        conn.request(method, "/" if method == "GET" else "/api/paste_done",
                     body=None if method == "GET" else b"not json", headers=headers)
        return conn.getresponse().status

    def test_unset_lets_nothing_extra_in(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("AGENTVIEW_EXTRA_ORIGINS", None)
            self.assertEqual(self.request("GET", f"{TS}:8445"), 403)
            self.assertEqual(self.request("POST", f"{TS}:8445", origin=ENTRY), 403)

    def test_an_entry_opens_its_own_host_and_origin(self):
        self.env(ENTRY)
        self.assertEqual(self.request("GET", f"{TS}:8445"), 200)
        self.assertEqual(self.request("GET", f"{TS.upper()}:8445"), 200)
        self.assertEqual(self.request("POST", f"{TS}:8445", origin=ENTRY), 400)
        self.assertEqual(self.request("POST", f"{TS}:8445"), 400)

    def test_the_local_names_still_pass(self):
        self.env(ENTRY)
        self.assertEqual(self.request("GET", f"127.0.0.1:{self.port}"), 200)
        self.assertEqual(self.request("POST", f"localhost:{self.port}",
                                      origin=f"http://localhost:{self.port}"), 400)

    def test_a_near_miss_is_refused(self):
        self.env(ENTRY)
        for host in (TS, f"{TS}:8446", f"{TS}:443", f"{TS}.attacker.example:8445",
                     f"x.{TS}:8445", "rebound.attacker.example"):
            with self.subTest(host=host):
                self.assertEqual(self.request("GET", host), 403)
        for origin in (f"http://{TS}:8445", f"https://{TS}", f"https://{TS}:8446",
                       f"https://{TS}.attacker.example:8445", f"https://{TS}:8445/x",
                       f"https://u@{TS}:8445", "null"):
            with self.subTest(origin=origin):
                self.assertEqual(self.request("POST", f"{TS}:8445", origin=origin), 403)

    def test_host_and_origin_must_name_the_same_entry(self):
        self.env(f"{ENTRY}, https://other.example")
        self.assertEqual(self.request("POST", f"{TS}:8445", origin="https://other.example"), 403)
        self.assertEqual(self.request("POST", "other.example", origin=ENTRY), 403)
        self.assertEqual(self.request("POST", f"127.0.0.1:{self.port}", origin=ENTRY), 403)
        self.assertEqual(self.request("POST", f"{TS}:8445",
                                      origin=f"http://127.0.0.1:{self.port}"), 403)
        self.assertEqual(self.request("POST", "other.example", origin="https://other.example"), 400)

    def test_the_default_port_may_be_left_out(self):
        self.env(f"https://{TS}")
        self.assertEqual(self.request("GET", TS), 200)
        self.assertEqual(self.request("GET", f"{TS}:443"), 200)
        self.assertEqual(self.request("POST", TS, origin=f"https://{TS}:443"), 400)
        self.assertEqual(self.request("GET", f"{TS}:8445"), 403)

    def test_the_fleet_header_is_still_needed(self):
        self.env(ENTRY)
        self.assertEqual(self.request("POST", f"{TS}:8445", origin=ENTRY, fleet=None), 403)

    def test_a_malformed_entry_opens_nothing(self):
        self.env(f"{TS}:8445, https://{TS}:8445/path, ftp://{TS}:8445, https://:8445, https://{TS}:x")
        self.assertEqual(self.request("GET", f"{TS}:8445"), 403)
        self.assertEqual(self.request("GET", ":8445"), 403)


if __name__ == "__main__":
    unittest.main()
