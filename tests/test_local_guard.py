"""The guard on every POST: a local Origin compared exactly, and a Host that names this server.

The body is never JSON, so a request the guard lets through is answered 400 and one it
refuses is answered 403. No route runs, so no store is touched.
"""
import http.client
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server


class Guard(unittest.TestCase):
    def setUp(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_port

    def post(self, route="paste_done", origin=None, host="same", fleet="1"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        headers = {"Host": f"127.0.0.1:{self.port}" if host == "same" else host}
        if origin is not None:
            headers["Origin"] = origin
        if fleet is not None:
            headers["X-Fleet"] = fleet
        conn.request("POST", "/api/" + route, body=b"not json", headers=headers)
        return conn.getresponse().status

    def test_a_name_that_only_starts_like_localhost_is_refused(self):
        for origin in ("http://localhost.attacker.example", "http://127.0.0.1.attacker.example",
                       f"http://localhost.attacker.example:{self.port}", "http://127.0.0.1:1",
                       f"https://127.0.0.1:{self.port}", "null", "http://localhost@evil.example"):
            with self.subTest(origin=origin):
                self.assertEqual(self.post(origin=origin), 403)

    def test_the_right_origin_passes_on_127_and_on_localhost(self):
        for origin in (f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"):
            with self.subTest(origin=origin):
                self.assertEqual(self.post(origin=origin), 400)

    def test_no_origin_still_passes_with_the_header(self):
        self.assertEqual(self.post(), 400)

    def test_a_foreign_host_is_refused_on_every_route(self):
        for route in server.Handler.ROUTES:
            with self.subTest(route=route):
                self.assertEqual(self.post(route, host="rebound.attacker.example"), 403)
                self.assertEqual(self.post(route, host=f"rebound.attacker.example:{self.port}"), 403)
                self.assertEqual(self.post(route, host=f"127.0.0.1:{self.port + 1}"), 403)

    def test_the_right_host_passes(self):
        self.assertEqual(self.post(host=f"localhost:{self.port}"), 400)
        self.assertEqual(self.post(host=f"127.0.0.1:{self.port}"), 400)

    def test_the_fleet_header_is_still_needed(self):
        self.assertEqual(self.post(fleet=None), 403)
        self.assertEqual(self.post(fleet="0"), 403)

    def test_on_port_80_the_browser_leaves_the_port_out(self):
        self.httpd.server_port = 80  # the handler reads it; the socket stays where it is
        for host in ("127.0.0.1", "localhost", "127.0.0.1:80"):
            for origin in ("http://127.0.0.1", "http://localhost:80"):
                with self.subTest(host=host, origin=origin):
                    self.assertEqual(self.post(origin=origin, host=host), 400)
        self.assertEqual(self.post(origin="http://localhost.attacker.example", host="127.0.0.1"), 403)
        self.assertEqual(self.post(host="evil.example"), 403)
        self.httpd.server_port = self.port

    def test_off_port_80_a_portless_name_is_refused(self):
        self.assertEqual(self.post(origin="http://127.0.0.1", host="127.0.0.1"), 403)


if __name__ == "__main__":
    unittest.main()
