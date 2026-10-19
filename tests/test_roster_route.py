"""The poll the page makes: `/api/roster` carries `columns` and still carries
everything it carried before. A fake provider stands behind it and every
store is a throwaway; no real session is read and no real terminal is touched.
"""
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import lines
import log
import seen
import server
from test_providers import Fake, minimal


class Poll(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "config.json").write_text("{}")
        fake = Fake([minimal(id="a", name="Ilse", cwd="/home/alice/Projects/maple", canJump=True)])
        for target, new in (("fleet.CONFIG", tmp / "config.json"),
                            ("fleet._providers", lambda: [fake]),
                            ("seen.store", lambda: tmp / "seen.json"),
                            ("lines.store", lambda: tmp / "lines"),
                            ("log.LOG", tmp / "events.jsonl"),
                            ("server.restorable", lambda live: None),
                            ("server.closed_now", lambda live: []),
                            ("server.coverage", lambda live: None),
                            ("providers.broken", lambda: {})):
            patch = mock.patch(target, new)
            patch.start()
            self.addCleanup(patch.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def poll(self):
        url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/roster"
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())

    def test_columns_arrive_beside_the_blocks_and_everything_else_stays(self):
        got = self.poll()
        self.assertEqual([m["key"] for b in got["blocks"] for m in b["members"]], ["fake:a"])
        self.assertEqual([t["key"] for c in got["columns"] for t in c["sessions"]], ["fake:a"])
        self.assertEqual(sorted(got), ["banners", "blocks", "chime", "closed", "columns", "counts",
                                       "hold", "providers", "restore", "saved"])
        self.assertEqual(sorted(got["counts"]), ["moving", "needs", "stuck"])
        self.assertIsInstance(got["banners"], list)

    def test_the_page_is_served_with_a_query_on_it(self):
        # `?view=blocks` is how the old block view stays reachable; the page
        # reads it, the server only has to not call it a different path.
        base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        for path in ("/", "/?view=blocks", "/index.html?view=blocks"):
            with urllib.request.urlopen(base + path, timeout=10) as r:
                self.assertEqual(r.status, 200, path)
                self.assertIn(b'<main id="main">', r.read(), path)


if __name__ == "__main__":
    unittest.main()
