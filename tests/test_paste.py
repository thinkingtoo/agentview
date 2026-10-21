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
import time
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
import finished
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
                 "blank": self.write(b" \n\t\n", "b"), "bom only": self.write(b"\xef\xbb\xbf \n", "m"), "oversized": self.write(b"x" * (paste.MAX_BYTES + 1), "o"),
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

    def test_a_record_that_never_answers_does_not_stop_the_roster(self):
        self.make("t", "text")
        real, started = lines._plain_bytes, time.monotonic()

        def stalled(path, limit):
            if str(path).endswith(".json") and "pastes" in str(path):
                time.sleep(3)
            return real(path, limit)
        with mock.patch("lines._plain_bytes", stalled), mock.patch("lines.READ_BUDGET", 0.2):
            self.assertEqual(self.pastes(), [])
        self.assertLess(time.monotonic() - started, 2.5)

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

    def test_done_that_cannot_remove_the_paste_says_so_and_it_stays(self):
        pid = self.make("t", "text")
        os.chmod(paste.store(), 0o500)          # a folder that cannot be changed
        self.addCleanup(os.chmod, paste.store(), 0o700)
        if os.access(paste.store(), os.W_OK):
            self.skipTest("this user can write anywhere")
        self.assertEqual(self.post("/api/paste_done", {"id": pid}), 500)
        self.assertNotEqual(self.withdraw("a", pid).returncode, 0)
        self.assertEqual([p["id"] for p in self.pastes()], [pid])

    def test_a_done_that_fails_half_way_leaves_a_paste_that_can_be_ticked_again(self):
        pid = self.make("t", "text")
        real = Path.unlink

        def failing(path, *a, **k):
            if path.suffix == ".txt":
                raise PermissionError(1, "Operation not permitted")
            return real(path, *a, **k)
        with mock.patch.object(Path, "unlink", failing):
            self.assertEqual(self.post("/api/paste_done", {"id": pid}), 500)
        self.assertEqual([p["id"] for p in self.pastes()], [pid])      # still on the card, not hidden
        self.assertEqual(self.post("/api/paste_done", {"id": pid}), 200)
        self.assertEqual(self.pastes(), [])
        self.assertEqual(sorted(p.name for p in paste.store().iterdir() if p.suffix in (".json", ".txt")), [])

    def test_copy_racing_done_never_leaves_a_paste_without_its_text(self):
        ids = [self.make(f"t{i}", f"text {i}") for i in range(40)]
        threads = [threading.Thread(target=f, args=(pid,)) for pid in ids for f in (paste.copied, paste.done)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.pastes(), [])
        self.assertEqual(sorted(p.name for p in paste.store().iterdir() if p.suffix in (".json", ".txt")), [])

    def test_pruning_the_lines_of_gone_sessions_leaves_the_pastes(self):
        pid = self.make("t", "text", session="gone")
        lines.forget(set())
        self.assertEqual(self.text_of(pid)[1], b"text")


class Other(Fake):
    """A second provider whose sessions can have the same bare id as a Fake's."""
    name = "other"


class Staying(Case):
    """Ticket 02: a Paste outlives the card it was left on, is counted in the
    header, belongs to provider + id, and its leftovers are swept."""

    def roster(self):
        return json.loads(self.get("/api/roster")[1])

    def finish(self, key="fake:a"):
        """You read its handover, long after its stop: a pill, not a tile."""
        finished.mark_read(key, 1790000000000)

    def pills(self):
        return [p for c in self.roster()["columns"] for p in c["pills"]]

    def kept(self):
        return self.roster()["kept"]

    def test_a_paste_goes_from_live_to_finished_to_gone_and_is_listed_all_the_way(self):
        pid = self.make("Message to Sven", "Hoi Sven,\nsecond")
        self.assertEqual([p["id"] for p in self.pastes()], [pid])        # live: on its tile
        self.finish()
        (pill,) = self.pills()                                             # finished: on its pill
        self.assertEqual([p["id"] for p in pill["pastes"]], [pid])
        self.assertEqual(self.roster()["kept"], [])
        self.fake._sessions = []                                           # gone from the roster
        for prune in (lines.forget, seen.forget, finished.forget):         # everything the poll prunes with
            prune(set())
        got = self.roster()
        self.assertEqual(self.pills(), [])
        self.assertEqual([(k["session"], [p["id"] for p in k["pastes"]]) for k in got["kept"]], [("a", [pid])])
        self.assertEqual(self.text_of(pid)[1], b"Hoi Sven,\nsecond")

    def test_copy_and_done_work_on_the_paste_of_a_gone_session(self):
        keep, gone = self.make("keep", "k"), self.make("gone", "g")
        self.fake._sessions = []
        self.assertEqual(self.post("/api/paste_copied", {"id": keep}), 200)
        (card,) = self.kept()
        self.assertEqual([(p["id"], p["copied"]) for p in card["pastes"]], [(keep, True), (gone, False)])
        self.assertEqual(self.post("/api/paste_done", {"id": gone}), 200)
        self.assertEqual([p["id"] for p in self.kept()[0]["pastes"]], [keep])
        self.assertEqual(self.post("/api/paste_done", {"id": keep}), 200)
        self.assertEqual(self.kept(), [])

    def test_a_live_session_is_never_in_kept(self):
        self.make("t", "text")
        self.assertEqual(self.kept(), [])

    def test_the_header_count_is_every_waiting_paste_on_tiles_pills_and_gone_sessions(self):
        self.assertEqual(self.roster()["pastes"], 0)
        self.make("one", "1")
        self.make("two", "2")
        self.assertEqual(self.roster()["pastes"], 2)
        self.finish()
        self.make("three", "3", session="gone")
        self.assertEqual(self.roster()["pastes"], 3)
        self.fake._sessions = []
        self.assertEqual(self.roster()["pastes"], 3)
        self.post("/api/paste_done", {"id": self.make("four", "4")})
        self.assertEqual(self.roster()["pastes"], 3)

    def test_a_paste_changes_no_flag_and_no_count_of_the_chime(self):
        before = self.roster()
        self.make("t", "text")
        after = self.roster()
        self.assertEqual((after["flags"], after["counts"]), (before["flags"], before["counts"]))

    def test_a_paste_left_on_a_routine_is_kept_because_a_routine_has_no_card(self):
        self.fake._sessions = [minimal(id="r", name="Nightly", routine="nightly-report", cwd="/home/alice")]
        pid = self.make("t", "text", session="r")
        got = self.roster()
        self.assertEqual([(k["session"], [p["id"] for p in k["pastes"]]) for k in got["kept"]], [("r", [pid])])
        self.assertEqual(got["pastes"], 1)

    # -- identity
    def two_providers(self):
        self.other = Other([minimal(id="a", name="Olga", cwd="/home/alice/Projects/maple", canJump=True)])
        fleet._providers = lambda: [self.fake, self.other]
        self.addCleanup(setattr, fleet, "_providers", lambda: [self.fake])

    def tiles(self):
        return {t["key"]: [p["id"] for p in t["pastes"]]
                for c in self.roster()["columns"] for t in c["sessions"]}

    def test_a_paste_made_for_one_provider_does_not_show_on_the_other_with_the_same_bare_id(self):
        self.two_providers()
        mine = self.run_command("create", "a", "--provider", "other", "--title", "t", self.write("x"))
        self.assertEqual(mine.returncode, 0, mine.stderr)
        self.assertEqual(self.tiles(), {"fake:a": [], "other:a": [mine.stdout.strip()]})

    def test_a_paste_for_a_provider_with_no_such_session_is_kept_not_shown_on_another(self):
        self.two_providers()
        got = self.run_command("create", "a", "--provider", "third", "--title", "t", self.write("x"))
        self.assertEqual(self.tiles(), {"fake:a": [], "other:a": []})
        self.assertEqual([(k["provider"], k["session"]) for k in self.kept()], [("third", "a")])
        self.assertEqual(self.roster()["pastes"], 1)

    def test_a_paste_that_names_no_provider_still_shows_on_a_session_with_that_id(self):
        # Made before providers were named, or by a session that could not say.
        self.two_providers()
        pid = self.make("t", "text")
        self.assertEqual(self.tiles(), {"fake:a": [pid], "other:a": [pid]})

    def test_withdraw_needs_the_provider_it_was_made_for(self):
        pid = self.run_command("create", "a", "--provider", "other", "--title", "t", self.write("x")).stdout.strip()
        wrong = self.run_command("withdraw", "a", "--provider", "fake", pid)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertEqual(self.roster()["pastes"], 1)
        right = self.run_command("withdraw", "a", "--provider", "other", pid)
        self.assertEqual(right.returncode, 0, right.stderr)
        self.assertEqual(self.roster()["pastes"], 0)

    def test_a_bad_provider_name_is_refused(self):
        got = self.run_command("create", "a", "--provider", "../x", "--title", "t", self.write("x"))
        self.assertNotEqual(got.returncode, 0)
        self.assertEqual(self.store_bytes(), b"")

    # -- leftovers of a crash
    def aged(self, path, seconds):
        old = time.time() - seconds
        os.utime(path, (old, old))

    def test_an_old_text_with_no_record_is_swept_and_a_text_with_a_record_never(self):
        pid = self.make("t", "text")
        root = paste.store()
        orphan = root / ("0" * 16 + ".txt")
        orphan.write_text("left by a crash")
        stray = root / "a.b.tmp"
        stray.write_text("half")
        corrupt = root / ("1" * 16 + ".txt")                 # its record is there, if unreadable
        corrupt.write_text("kept")
        (root / ("1" * 16 + ".json")).write_text("{not json")
        for path in (orphan, stray, corrupt, root / f"{pid}.txt", root / f"{pid}.json"):
            self.aged(path, 3600)
        self.roster()
        self.assertEqual(sorted(p.name for p in root.iterdir() if p.name != ".lock"),
                         sorted([f"{pid}.txt", f"{pid}.json", "1" * 16 + ".txt", "1" * 16 + ".json"]))
        self.assertEqual(self.text_of(pid)[1], b"text")

    def test_a_fresh_text_with_no_record_is_left_for_the_create_that_is_writing_it(self):
        paste.store().mkdir(parents=True, exist_ok=True)
        young = paste.store() / ("2" * 16 + ".txt")
        young.write_text("being made")
        self.roster()
        self.assertTrue(young.exists())


if __name__ == "__main__":
    unittest.main()
