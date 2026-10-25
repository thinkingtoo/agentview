"""The Host check on every GET: a page on a rebound name must not read the roster.

The routes that would reach real stores are replaced, so a request the guard lets through
answers 200 from a stub and one it refuses answers 403 before any route runs.
"""
import http.client
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server

PATHS = ("/api/roster", "/api/search?q=x", "/api/paste_text?id=1", "/ticket/owner/repo/7", "/",
         "/index.html", "/nothing")


class GetGuard(unittest.TestCase):
    def setUp(self):
        for target, value in (("page", lambda: "<html></html>"),
                              ("found", lambda q, n: {"query": q, "results": []})):
            patcher = mock.patch.object(server, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_port

    def get(self, path, host="same"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}" if host == "same" else host})
        return conn.getresponse().status

    def test_a_foreign_host_is_refused_on_every_get(self):
        for path in PATHS:
            for host in ("rebound.attacker.example", f"rebound.attacker.example:{self.port}",
                         f"127.0.0.1:{self.port + 1}", "localhost"):
                with self.subTest(path=path, host=host):
                    self.assertEqual(self.get(path, host=host), 403)

    def test_the_roster_is_never_computed_for_a_foreign_host(self):
        with mock.patch.object(server.poll, "round", side_effect=AssertionError("ran")):
            self.assertEqual(self.get("/api/roster", host="rebound.attacker.example"), 403)

    def test_the_dashboard_polls_still_answer(self):
        for path in ("/", "/index.html", "/api/search?q=x"):
            for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"LOCALHOST:{self.port}"):
                with self.subTest(path=path, host=host):
                    self.assertEqual(self.get(path, host=host), 200)

    def test_the_roster_answers_for_a_local_host(self):
        # The round (`poll.round`) is what the route depends on; a stub stands in for it.
        data = {"flags": [], "providers": {}}
        with mock.patch.object(server.poll, "round", return_value=data), \
             mock.patch.object(server, "restorable", return_value=[]), \
             mock.patch.object(server, "closed_now", return_value=[]), \
             mock.patch.object(server, "coverage", return_value={}):
            for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
                with self.subTest(host=host):
                    self.assertEqual(self.get("/api/roster", host=host), 200)

    def test_on_port_80_the_portless_host_answers(self):
        self.httpd.server_port = 80
        for host in ("127.0.0.1", "localhost", "LocalHost"):
            with self.subTest(host=host):
                self.assertEqual(self.get("/", host=host), 200)
        self.assertEqual(self.get("/", host="evil.example"), 403)
        self.httpd.server_port = self.port

    def test_off_port_80_the_portless_host_is_refused(self):
        self.assertEqual(self.get("/", host="127.0.0.1"), 403)


if __name__ == "__main__":
    unittest.main()
