"""`tiroir_origins` in config.json: tiroir pages that may raise a terminal pane.

A page served by a tiroir sends `POST /api/jump` or `/api/reopen` to 127.0.0.1 from the browser.
Chrome first sends a preflight `OPTIONS` carrying `Access-Control-Request-Private-Network`. An
origin on the list gets CORS and `Access-Control-Allow-Private-Network: true` on those two routes
and nothing else; any other origin is refused on both, and the Host must still be this server's.
"""
import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import server

TIROIR = "https://first.tiroir.example"
OTHER = "https://second.tiroir.example"
SID = "12345678-1234-1234-1234-123456789abc"


class TiroirOrigins(unittest.TestCase):
    def setUp(self):
        self.listed = [TIROIR]
        patcher = mock.patch.object(fleet, "read_config", lambda: {"tiroir_origins": self.listed})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_port

    def send(self, method, route, origin=None, host="same", fleet_header="1", body=None, extra=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        headers = {"Host": f"127.0.0.1:{self.port}" if host == "same" else host}
        if origin is not None:
            headers["Origin"] = origin
        if fleet_header is not None:
            headers["X-Fleet"] = fleet_header
        headers.update(extra or {})
        conn.request(method, route, body=body if body is not None else b"not json", headers=headers)
        resp = conn.getresponse()
        resp.read()
        return resp

    def preflight(self, route, origin=TIROIR, host="same"):
        return self.send("OPTIONS", route, origin=origin, host=host, fleet_header=None, extra={
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, x-fleet",
            "Access-Control-Request-Private-Network": "true"})

    # --- the preflight -------------------------------------------------------------------

    def test_an_allowed_origin_gets_cors_and_private_network(self):
        for route in ("/api/jump", "/api/reopen"):
            with self.subTest(route=route):
                resp = self.preflight(route)
                self.assertEqual(resp.status, 204)
                self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), TIROIR)
                self.assertEqual(resp.getheader("Access-Control-Allow-Private-Network"), "true")
                self.assertEqual(resp.getheader("Access-Control-Allow-Methods"), "POST")
                allowed = resp.getheader("Access-Control-Allow-Headers").lower()
                self.assertIn("x-fleet", allowed)
                self.assertIn("content-type", allowed)
                self.assertIn("Origin", resp.getheader("Vary"))

    def test_any_other_origin_is_refused_the_preflight(self):
        for origin in (OTHER, "http://first.tiroir.example", f"{TIROIR}:8443", f"{TIROIR}.evil.example",
                       f"https://x.{TIROIR[8:]}", f"{TIROIR}/x", "null", "*", "https://evil.example"):
            for route in ("/api/jump", "/api/reopen"):
                with self.subTest(origin=origin, route=route):
                    resp = self.preflight(route, origin=origin)
                    self.assertEqual(resp.status, 403)
                    self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))
                    self.assertIsNone(resp.getheader("Access-Control-Allow-Private-Network"))

    def test_a_preflight_with_no_origin_is_refused(self):
        resp = self.send("OPTIONS", "/api/jump", fleet_header=None)
        self.assertEqual(resp.status, 403)

    def test_the_list_opens_only_jump_and_reopen(self):
        for route in ("/api/name", "/api/restore", "/api/paste_done", "/api/log", "/api/jumpx",
                      "/api/reopen/../name", "/", "/api/paste_text"):
            with self.subTest(route=route):
                resp = self.preflight(route)
                self.assertEqual(resp.status, 403)
                self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))

    def test_the_preflight_still_needs_this_servers_host(self):
        for host in ("rebound.attacker.example", f"{TIROIR[8:]}:{self.port}", "127.0.0.1:1"):
            with self.subTest(host=host):
                self.assertEqual(self.preflight("/api/jump", host=host).status, 403)

    # --- the POST -----------------------------------------------------------------------

    def test_an_allowed_origin_can_jump(self):
        session = {"pid": 7, "name": "tarek"}
        with mock.patch.object(fleet, "find", return_value=("claude", session)) as find, \
                mock.patch.object(fleet, "jump_to", return_value={"ok": True, "did": "jumped"}), \
                mock.patch.object(fleet, "mark_seen"):
            resp = self.send("POST", "/api/jump", origin=TIROIR, body=b'{"key": "claude:abc"}')
        self.assertEqual(resp.status, 200)
        find.assert_called_once_with("claude:abc")
        self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), TIROIR)
        self.assertIn("Origin", resp.getheader("Vary"))

    def test_an_allowed_origin_can_reopen(self):
        with mock.patch.object(server, "reopen", return_value={"ok": True, "did": "jumped"}) as reopen:
            resp = self.send("POST", "/api/reopen", origin=TIROIR,
                             body=json.dumps({"id": SID}).encode())
        self.assertEqual(resp.status, 200)
        reopen.assert_called_once_with(SID)
        self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), TIROIR)

    def test_a_refusal_for_an_allowed_origin_is_still_readable_by_the_page(self):
        with mock.patch.object(fleet, "find", return_value=None):
            resp = self.send("POST", "/api/jump", origin=TIROIR, body=b'{"key": "claude:gone"}')
        self.assertEqual(resp.status, 404)
        self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), TIROIR)

    def test_any_other_origin_is_refused_the_post(self):
        with mock.patch.object(fleet, "find") as find, mock.patch.object(server, "reopen") as reopen:
            for origin in (OTHER, "http://first.tiroir.example", f"{TIROIR}:8443",
                           f"{TIROIR}.evil.example", "null", "https://evil.example"):
                for route, body in (("/api/jump", b'{"key": "claude:abc"}'),
                                    ("/api/reopen", json.dumps({"id": SID}).encode())):
                    with self.subTest(origin=origin, route=route):
                        resp = self.send("POST", route, origin=origin, body=body)
                        self.assertEqual(resp.status, 403)
                        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))
        find.assert_not_called()
        reopen.assert_not_called()

    def test_the_list_opens_no_other_route(self):
        for route in ("/api/name", "/api/restore", "/api/dismiss", "/api/paste_done", "/api/jumpx"):
            with self.subTest(route=route):
                resp = self.send("POST", route, origin=TIROIR)
                self.assertEqual(resp.status, 403)
                self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))

    def test_an_allowed_origin_still_needs_the_fleet_header_and_this_host(self):
        self.assertEqual(self.send("POST", "/api/jump", origin=TIROIR, fleet_header=None).status, 403)
        self.assertEqual(self.send("POST", "/api/jump", origin=TIROIR, host="rebound.evil.example").status, 403)

    def test_this_servers_own_origin_is_unchanged(self):
        own = f"http://127.0.0.1:{self.port}"
        resp = self.send("POST", "/api/jump", origin=own)
        self.assertEqual(resp.status, 400)  # let through, the body is not JSON
        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))

    # --- the list -------------------------------------------------------------------------

    def test_adding_a_tiroir_is_one_more_entry(self):
        self.assertEqual(self.preflight("/api/jump", origin=OTHER).status, 403)
        self.listed.append(OTHER)
        self.assertEqual(self.preflight("/api/jump", origin=OTHER).status, 204)
        self.assertEqual(self.preflight("/api/jump", origin=TIROIR).status, 204)

    def test_no_list_or_a_malformed_one_opens_nothing(self):
        for listed in ([], None, "https://first.tiroir.example", {"a": 1}, [5, None, "*", "tiroir.me",
                       "https://first.tiroir.example/path", "ftp://first.tiroir.example", ""]):
            self.listed = listed
            with self.subTest(listed=listed):
                self.assertEqual(self.preflight("/api/jump").status, 403)
                self.assertEqual(self.send("POST", "/api/jump", origin=TIROIR).status, 403)

    def test_the_example_config_documents_the_key(self):
        example = json.loads((Path(__file__).resolve().parent.parent / "config.example.json").read_text())
        self.assertEqual(example["tiroir_origins"], [])


if __name__ == "__main__":
    unittest.main()
