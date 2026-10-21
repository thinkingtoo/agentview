"""A Paste: a titled text a session leaves on its card, through the three things
that can be seen of it -- the `paste` command (what it prints and returns), the
roster and the routes of the page.

A fake provider stands behind the roster and the store is a throwaway under a
temp state directory. The command runs as a process of its own, as a session
runs it, with `XDG_STATE_HOME` pointing at that directory.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import fleet
import lines
import log
import paste
import seen
import server
from test_providers import Fake, minimal

REAL_STORE = lines.store          # before any test patches it
COMMAND = ROOT / "hooks" / "paste"
NASTY = "He said \"it's fine\"\\n\tTab\there\n\n\nafter blank lines\r\nCRLF \u00e9\u4e2d \\ end\n"


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "state"
        (self.tmp / "config.json").write_text("{}")
        self.fake = Fake([minimal(id="a", name="Ilse", cwd="/home/alice/Projects/maple", canJump=True)])
        for target, new in (("fleet.CONFIG", self.tmp / "config.json"),
                            ("fleet._providers", lambda: [self.fake]),
                            ("seen.store", lambda: self.tmp / "seen.json"),
                            ("lines.store", lambda: self.state / "agentview" / "lines"),
                            ("log.LOG", self.tmp / "events.jsonl"),
                            ("server.restorable", lambda live: None),
                            ("server.closed_now", lambda live: []),
                            ("server.coverage", lambda live: None),
                            ("providers.broken", lambda: {})):
            patch = mock.patch(target, new)
            patch.start()
            self.addCleanup(patch.stop)
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.state)})
        env.start()
        self.addCleanup(env.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    # -- what a session does
    def write(self, text, name="text.txt"):
        path = self.tmp / name
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return path

    def run_command(self, *args):
        return subprocess.run([sys.executable, str(COMMAND), *map(str, args)], capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, timeout=30,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})

    def make(self, title, text, session="a"):
        got = self.run_command("create", session, "--title", title, self.write(text))
        self.assertEqual(got.returncode, 0, got.stderr)
        return got.stdout.strip()

    def withdraw(self, session, pid):
        return self.run_command("withdraw", session, pid)

    # -- what the page does
    base = property(lambda self: f"http://127.0.0.1:{self.httpd.server_port}")

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as err:
            err.close()
            return err.code, b""

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, method="POST",
                                     data=json.dumps(body).encode(), headers={"X-Fleet": "1"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as err:
            err.close()
            return err.code

    def pastes(self, key="fake:a"):
        got = json.loads(self.get("/api/roster")[1])
        tiles = [t for c in got["columns"] for t in c["sessions"] if t["key"] == key]
        return tiles[0]["pastes"] if tiles else None

    def text_of(self, pid):
        return self.get("/api/paste_text?id=" + urllib.parse.quote(pid))

    def store_bytes(self):
        return b"".join(p.read_bytes() for p in sorted(self.state.rglob("*")) if p.is_file())


class Create(Case):
    def test_the_command_prints_an_id_and_the_card_lists_the_paste_without_its_text(self):
        pid = self.make("Message to Sven", "Hoi Sven,\nsecond line\n")
        self.assertRegex(pid, r"^[0-9a-f]{8,}$")
        self.assertEqual(self.pastes(), [{"id": pid, "title": "Message to Sven",
                                          "first": "Hoi Sven,", "secret": False, "copied": False}])
        self.assertNotIn(b"second line", self.get("/api/roster")[1])

    def test_a_session_with_no_paste_has_an_empty_list(self):
        self.assertEqual(self.pastes(), [])

    def test_several_pastes_on_one_session_show_in_the_order_they_were_made(self):
        ids = [self.make(t, f"text {t}") for t in ("one", "two", "three")]
        self.assertEqual([p["id"] for p in self.pastes()], ids)
        self.assertEqual([p["title"] for p in self.pastes()], ["one", "two", "three"])

    def test_a_paste_belongs_to_its_own_session_only(self):
        self.make("mine", "text", session="other")
        self.assertEqual(self.pastes(), [])

    def test_the_first_line_skips_leading_blank_lines(self):
        self.make("t", "\n\n  Dear Sven,\nbody")
        self.assertEqual(self.pastes()[0]["first"], "Dear Sven,")

    def test_the_first_line_is_clipped(self):
        self.make("t", "x" * 1000)
        self.assertLessEqual(len(self.pastes()[0]["first"]), 160)

    def test_a_missing_empty_blank_or_oversized_file_is_refused_and_nothing_is_written(self):
        cases = {"missing": self.tmp / "nope.txt", "empty": self.write(b"", "e"),
                 "blank": self.write(b" \n\t\n", "b"), "oversized": self.write(b"x" * (paste.MAX_BYTES + 1), "o"),
                 "not text": self.write(b"\xff\xfe\x00bin", "n"), "directory": self.tmp}
        for label, path in cases.items():
            got = self.run_command("create", "a", "--title", "t", path)
            self.assertNotEqual(got.returncode, 0, label)
            self.assertEqual(got.stdout, "", label)
            self.assertTrue(got.stderr.strip(), label)
        self.assertEqual(self.pastes(), [])
        self.assertEqual(self.store_bytes(), b"")

    def test_a_missing_title_or_a_bad_session_id_is_refused(self):
        path = self.write("text")
        for args in (("create", "a", "--title", "", path), ("create", "a", "--title", "  ", path),
                     ("create", "../x", "--title", "t", path), ("create", "", "--title", "t", path)):
            self.assertNotEqual(self.run_command(*args).returncode, 0, args)
        self.assertEqual(self.store_bytes(), b"")

    def test_a_long_title_is_clipped_to_one_line(self):
        self.make("a\nb " + "t" * 500, "text")
        title = self.pastes()[0]["title"]
        self.assertNotIn("\n", title)
        self.assertLessEqual(len(title), 80)

    def test_the_store_is_under_the_state_directory_beside_the_lines_and_nowhere_else(self):
        self.make("t", "text")
        found = [p for p in self.tmp.rglob("*") if p.is_file() and p.name != "config.json" and p.suffix != ".txt"]
        self.assertTrue(found)
        for p in found:
            self.assertTrue(str(p).startswith(str(self.state / "agentview")), p)
        self.assertEqual(paste.store().parent, lines.store().parent)

    def test_the_default_store_is_not_under_claude_or_a_synced_folder(self):
        home = Path.home()
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": ""}), mock.patch("lines.store", REAL_STORE):
            where = paste.store().resolve()
        self.assertEqual(where, (home / ".local" / "state" / "agentview" / "pastes").resolve())
        for banned in (home / ".claude", home / "Documents"):
            self.assertNotIn(banned.resolve(), where.parents)


class Text(Case):
    def test_the_full_text_comes_back_byte_identical(self):
        pid = self.make("t", NASTY)
        status, body = self.text_of(pid)
        self.assertEqual(status, 200)
        self.assertEqual(body, NASTY.encode("utf-8"))

    def test_a_leading_byte_order_mark_comes_back_too(self):
        pid = self.make("t", "\ufeffBOM first")
        self.assertEqual(self.text_of(pid)[1], "\ufeffBOM first".encode("utf-8"))

    def test_an_unknown_or_hostile_id_is_a_404_not_a_path(self):
        self.make("t", "text")
        for pid in ("", "nope", "../lines/x", "a/b", "%00"):
            self.assertEqual(self.text_of(pid)[0], 404, pid)


class Lifecycle(Case):
    def test_copy_marks_it_copied_and_keeps_it(self):
        pid = self.make("t", "text")
        self.assertEqual(self.post("/api/paste_copied", {"id": pid}), 200)
        self.assertEqual(self.post("/api/paste_copied", {"id": pid}), 200)
        self.assertEqual([p["copied"] for p in self.pastes()], [True])
        self.assertEqual(self.text_of(pid)[1], b"text")

    def test_done_removes_it_and_only_it(self):
        keep, gone = self.make("keep", "k"), self.make("gone", "g")
        self.assertEqual(self.post("/api/paste_done", {"id": gone}), 200)
        self.assertEqual([p["id"] for p in self.pastes()], [keep])
        self.assertEqual(self.text_of(gone)[0], 404)

    def test_withdraw_by_id_removes_it_and_only_for_its_own_session(self):
        pid = self.make("t", "text")
        wrong = self.withdraw("other", pid)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertEqual(len(self.pastes()), 1)
        right = self.withdraw("a", pid)
        self.assertEqual(right.returncode, 0, right.stderr)
        self.assertEqual(self.pastes(), [])

    def test_withdrawing_what_is_not_there_fails_loudly(self):
        got = self.withdraw("a", "deadbeef")
        self.assertNotEqual(got.returncode, 0)
        self.assertTrue(got.stderr.strip())

    def test_bad_input_to_the_routes_is_a_400_or_404(self):
        for route in ("/api/paste_copied", "/api/paste_done"):
            self.assertEqual(self.post(route, {}), 400)
            self.assertEqual(self.post(route, {"id": 5}), 400)
            self.assertEqual(self.post(route, {"id": "nope"}), 404)

    def test_pruning_the_lines_of_gone_sessions_leaves_the_pastes(self):
        pid = self.make("t", "text", session="gone")
        lines.forget(set())
        self.assertEqual(self.text_of(pid)[1], b"text")


if __name__ == "__main__":
    unittest.main()
