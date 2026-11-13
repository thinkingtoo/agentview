"""The poll the page makes: `/api/roster` carries `columns` and still carries
everything it carried before. A fake provider stands behind it and every
store is a throwaway; no real session is read and no real terminal is touched.
"""
import json
import shutil
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
import marks
import server
from test_providers import Fake, minimal


class Poll(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "config.json").write_text("{}")
        fake = Fake([minimal(id="a", name="Ilse", cwd="/home/alice/Projects/maple", canJump=True)])
        for target, new in (("fleet.CONFIG", tmp / "config.json"),
                            ("fleet._providers", lambda: [fake]),
                            ("marks.store", lambda: tmp / "marks.json"),
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

    def test_the_roster_has_columns_and_flags_and_no_blocks(self):
        got = self.poll()
        self.assertEqual([f["key"] for f in got["flags"]], ["fake:a"])
        self.assertEqual([t["key"] for c in got["columns"] for t in c["sessions"]], ["fake:a"])
        self.assertEqual(sorted(got), ["banners", "build", "chime", "closed", "columns", "counts",
                                       "flags", "kept", "merges", "merges_ring", "pastes", "providers", "restore", "saved"])
        self.assertNotIn("blocks", got)
        self.assertEqual(sorted(got["counts"]), ["moving", "needs", "otherStuck"])
        self.assertIsInstance(got["banners"], list)

    def test_the_page_is_served_with_a_query_on_it(self):
        # The server only has to not call a query a different path.
        base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        for path in ("/", "/?x=1", "/index.html?x=1"):
            with urllib.request.urlopen(base + path, timeout=10) as r:
                self.assertEqual(r.status, 200, path)
                self.assertIn(b'<main id="main" class="ov">', r.read(), path)

    def test_the_roster_names_the_build_of_the_page_it_serves(self):
        # The page compares this with the build baked into its own script and reloads on a difference.
        base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        with urllib.request.urlopen(base + "/", timeout=10) as r:
            html = r.read().decode()
        build = self.poll()["build"]
        self.assertRegex(build, r"^[0-9a-f]{12}$")
        self.assertIn(f'const BUILD = "{build}";', html)
        self.assertEqual(self.poll()["build"], build)

    def test_the_build_follows_index_html(self):
        before = server.build()
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)
        with mock.patch.object(server, "HERE", other):
            (other / "index.html").write_text("<html>other {{ZOOM}} {{HOME}} {{BUILD}}</html>")
            self.assertNotEqual(server.build(), before)

    def _desk(self, *whens):
        import deskfile
        f = deskfile.path()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(deskfile.SKELETON + "\n".join(
            f"- [ ] Merge o/r#{n}: x\n  - Pinned commit: {'a' * 40}\n  - Handed over by Ciro, {w}.\n"
            for n, w in enumerate(whens, 1)))

    def _post(self, route):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.httpd.server_address[1]}/api/{route}", method="POST",
            data=b"{}", headers={"X-Fleet": "1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)

    def test_the_roster_counts_the_desk_and_the_ring_is_spent_when_the_page_says_it_sounded(self):
        self.assertEqual((self.poll()["merges"], self.poll()["merges_ring"]), (0, None))
        self._desk("2020-01-01 09:00", "2020-01-02 09:00")
        first, again = self.poll(), self.poll()
        self.assertEqual(first["merges"], 2)
        self.assertIn("merge desk", first["merges_ring"].lower())
        self.assertEqual(again["merges_ring"], first["merges_ring"])    # nobody has heard it yet
        self.assertEqual(self._post("desk_rung"), {"ok": True})
        after = self.poll()
        self.assertEqual((after["merges"], after["merges_ring"]), (2, None))

    def test_the_merges_button_opens_the_desk_page(self):
        with mock.patch("desk.page", return_value="http://127.0.0.1:1/x") as page:
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.httpd.server_address[1]}/api/desk_page", method="POST",
                data=b"{}", headers={"X-Fleet": "1"})
            with urllib.request.urlopen(req, timeout=10) as r:
                self.assertEqual(json.load(r), {"ok": True, "url": "http://127.0.0.1:1/x"})
        page.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
