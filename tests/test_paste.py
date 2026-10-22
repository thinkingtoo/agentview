"""A Paste: a titled text a session leaves on its card, through the three things
that can be seen of it -- the `paste` command (what it prints and returns), the
roster and the routes of the page.

A fake provider stands behind the roster and the store is a throwaway under a
temp state directory. The command runs as a process of its own, as a session
runs it, with `XDG_STATE_HOME` pointing at that directory.
"""
import contextlib
import io
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
import vault
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
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                                   # Never the real keyring, whatever a text turns out to hold.
                                   "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + str(self.tmp / "no-bus")})

    def make(self, title, text, session="a"):
        got = self.run_command("create", session, "--title", title, self.write(text))
        self.assertEqual(got.returncode, 0, got.stderr)
        return got.stdout.strip()

    def withdraw(self, session, pid):
        return self.run_command("withdraw", session, pid)

    # -- what the page does
    base = property(lambda self: f"http://127.0.0.1:{self.httpd.server_port}")

    def get(self, path, headers=None):
        try:
            req = urllib.request.Request(self.base + path, headers=headers or {})
            with urllib.request.urlopen(req, timeout=10) as r:
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
        return self.get("/api/paste_text?id=" + urllib.parse.quote(pid), {"X-Fleet": "1"})

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

    def test_copy_and_done_are_not_fooled_by_a_slow_read_of_the_record(self):
        # The poll gives up on a slow read and says "absent"; a change must not.
        pid = self.make("t", "text")
        with mock.patch.object(lines, "read_bounded", lambda path, limit: None):
            self.assertEqual(self.post("/api/paste_copied", {"id": pid}), 200)
        self.assertEqual([p["copied"] for p in self.pastes()], [True])
        with mock.patch.object(lines, "read_bounded", lambda path, limit: None):
            self.assertEqual(self.post("/api/paste_done", {"id": pid}), 200)
        self.assertEqual(self.pastes(), [])
        self.assertEqual(sorted(p.name for p in paste.store().iterdir() if p.suffix in (".json", ".txt")), [])

    def test_a_copy_that_joins_an_old_read_cannot_bring_a_done_paste_back(self):
        pid = self.make("t", "text")
        old = paste._record(pid)                  # what a poll read before the done
        self.assertEqual(self.post("/api/paste_done", {"id": pid}), 200)
        with mock.patch.object(lines, "read_bounded", lambda path, limit: json.dumps(old).encode()):
            self.post("/api/paste_copied", {"id": pid})
        self.assertEqual(self.pastes(), [])
        self.assertEqual(sorted(p.name for p in paste.store().iterdir() if p.suffix in (".json", ".txt")), [])

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

    def test_a_creator_stalled_between_its_two_writes_does_not_lose_its_text_to_a_sweep(self):
        real = lines.write_atomic
        swept = []

        def stalled(path, data, *a, **k):
            if str(path).endswith(".json") and not swept:
                # the creator sleeps here past the sweep age; the roster poll sweeps meanwhile
                for stored in paste.store().glob("*.txt"):
                    self.aged(stored, 3600)
                paste.sweep()
                swept.append(True)
            return real(path, data, *a, **k)

        src = self.tmp / "in.txt"
        src.write_text("the text")
        with mock.patch("lines.write_atomic", stalled):
            pid = paste.create("a", "t", str(src))
        self.assertTrue(swept)
        self.assertEqual(paste.text(pid), b"the text")

    def test_a_sweep_finding_the_lock_taken_leaves_an_old_orphan_for_the_next_poll(self):
        root = paste.store()
        root.mkdir(parents=True, exist_ok=True)
        orphan = root / ("0" * 16 + ".txt")
        orphan.write_text("left by a crash")
        self.aged(orphan, 3600)
        with paste._changing(root):
            paste.sweep()
            self.assertTrue(orphan.exists())
        paste.sweep()
        self.assertFalse(orphan.exists())

    def test_a_sweep_does_not_hang_on_a_lock_that_is_a_fifo(self):
        root = paste.store()
        root.mkdir(parents=True, exist_ok=True)
        os.mkfifo(root / ".lock")
        (root / ("0" * 16 + ".txt")).write_text("x")
        for call in (paste.sweep, lambda: self.assertRaises(OSError, paste._changing(root).__enter__)):
            done = threading.Thread(target=call, daemon=True)
            done.start()
            done.join(5)
            self.assertFalse(done.is_alive())

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

    def test_the_sweep_does_not_follow_links(self):
        root = paste.store()
        root.mkdir(parents=True, exist_ok=True)
        lone = root / ("3" * 16 + ".txt")
        lone.write_text("orphan")
        (root / ("3" * 16 + ".json")).symlink_to(self.tmp / "nowhere")   # a record that is a dangling link
        stray = root / "x.y.tmp"
        stray.symlink_to(self.tmp / "nowhere")
        os.utime(lone, (1, 1))
        os.utime(stray, (1, 1), follow_symlinks=False)
        paste.sweep()
        self.assertTrue(lone.exists())            # its record is there, whatever it points at
        self.assertFalse(os.path.lexists(stray))  # an old stray link goes, the target is not touched

    def test_a_fresh_text_with_no_record_is_left_for_the_create_that_is_writing_it(self):
        paste.store().mkdir(parents=True, exist_ok=True)
        young = paste.store() / ("2" * 16 + ".txt")
        young.write_text("being made")
        self.roster()
        self.assertTrue(young.exists())

# Built in pieces: no secret scanner should take this file for a leak.
TOKEN = "gh" + "p_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"
SECRET_TEXT = "Hoi Sven, jouw nieuwe toegang:\n" + TOKEN + "\n\"quoted\" \\ tab\there\n"


class FakeVault:
    """The keyring, in memory. Records every call, by id: never the text."""
    Unavailable, Unsure = vault.Unavailable, vault.Unsure

    def __init__(self):
        self.items, self.calls, self.stores = {}, [], {}
        self.down = None            # a reason: every call raises Unavailable(reason)
        self.fail_delete = False
        self.put_times_out = False  # the item is kept, then the reply never comes
        self.put_refused = None     # a reason: only `put` raises a plain Unavailable

    def _call(self, op, pid=None):
        self.calls.append((op, pid))
        if self.down:
            raise vault.Unavailable(self.down)

    # An item belongs to a store, as in the real keyring: a call for another store sees nothing.
    def put(self, pid, text, store):
        self._call("put", pid)
        if self.put_refused:
            raise vault.Unavailable(self.put_refused)
        self.items[pid] = text
        self.stores[pid] = store
        if self.put_times_out:
            raise vault.Unsure("the keyring cannot be reached (timeout)")

    def get(self, pid, store):
        self._call("get", pid)
        return self.items.get(pid) if self.stores.get(pid) == store else None

    def delete(self, pid, store):
        self._call("delete", pid)
        if self.fail_delete:
            raise vault.Unavailable("the keyring cannot be reached (test)")
        if self.stores.get(pid) != store:
            return False
        return self.items.pop(pid, None) is not None

    def ids(self, store):
        self._call("ids")
        return sorted(p for p in self.items if self.stores.get(p) == store)


class Secrets(Case):
    def setUp(self):
        super().setUp()
        self.vault = FakeVault()
        patch = mock.patch.object(paste, "vault", self.vault)
        patch.start()
        self.addCleanup(patch.stop)
        self.stderr = io.StringIO()
        redirect = contextlib.redirect_stderr(self.stderr)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        self.inputs = []

    def command(self, *args):
        """The command, in this process so that the fake keyring answers it."""
        out, err = io.StringIO(), io.StringIO()
        code = paste.main([str(a) for a in args], out, err)
        self.stderr.write(err.getvalue())
        return code, out.getvalue().strip(), err.getvalue()

    def leave(self, title, text, *flags, session="a"):
        path = self.write(text, f"in{len(self.inputs)}.txt")
        self.inputs.append(path)
        return self.command("create", session, "--title", title, *flags, path)

    def everything_else(self):
        """Every byte under the temp directory except the files the session wrote."""
        return b"".join(p.read_bytes() for p in sorted(self.tmp.rglob("*"))
                        if p.is_file() and p not in self.inputs)

    def log_text(self):
        log_file = self.tmp / "events.jsonl"
        return log_file.read_text() if log_file.exists() else ""

    def assert_no_leak(self, *secrets):
        gathered = (self.everything_else().decode("utf-8", "replace") + self.stderr.getvalue()
                    + self.log_text() + json.dumps(self.vault.calls) + self.get("/api/roster")[1].decode())
        for secret in secrets:
            self.assertNotIn(secret, gathered)

    def test_a_marked_secret_goes_to_the_keyring_and_nowhere_in_the_store(self):
        code, pid, err = self.leave("New login", "just a word\n", "--secret")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.vault.items, {pid: "just a word\n"})
        self.assertEqual(self.store_bytes().count(b"just a word"), 0)
        self.assert_no_leak("just a word")

    def test_an_unmarked_text_with_a_token_is_handled_as_a_secret(self):
        code, pid, err = self.leave("New login", SECRET_TEXT)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.vault.items, {pid: SECRET_TEXT})
        self.assertTrue(self.pastes()[0]["secret"])
        self.assertNotIn(TOKEN.encode(), self.store_bytes())
        self.assert_no_leak(TOKEN, "Hoi Sven, jouw")

    def test_the_roster_never_carries_a_secrets_text_not_even_the_first_line(self):
        self.leave("New login", SECRET_TEXT)
        self.leave("Second", "plain first line\nthen " + TOKEN, "--secret")
        raw = self.get("/api/roster")[1].decode()
        for word in ("Hoi Sven", "toegang", TOKEN, "plain first line"):
            self.assertNotIn(word, raw)
        self.assertEqual([(p["secret"], p["first"]) for p in self.pastes()], [(True, ""), (True, "")])

    def test_a_secret_record_that_somehow_holds_a_first_line_still_shows_none(self):
        _, pid, _ = self.leave("New login", SECRET_TEXT)
        record = paste.store() / f"{pid}.json"
        data = json.loads(record.read_text())
        record.write_text(json.dumps({**data, "first": "Hoi Sven, jouw"}))
        self.assertEqual(self.pastes()[0]["first"], "")

    def test_a_plain_paste_never_touches_the_keyring_even_when_it_is_down(self):
        self.vault.down = "no keyring"
        code, pid, err = self.leave("Plain", "Hoi Sven,\nhet voorstel staat klaar. Het wachtwoord: zie de kluis.\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.vault.calls, [])
        self.assertEqual(self.text_of(pid)[0], 200)
        self.assertFalse(self.pastes()[0]["secret"])

    def test_the_text_comes_from_the_keyring_byte_identical_and_copying_does_not_touch_it(self):
        _, pid, _ = self.leave("New login", SECRET_TEXT)
        status, body = self.text_of(pid)
        self.assertEqual((status, body), (200, SECRET_TEXT.encode()))
        before = list(self.vault.calls)
        self.assertEqual(self.post("/api/paste_copied", {"id": pid}), 200)
        self.assertEqual(self.vault.calls, before)
        self.assertTrue(self.pastes()[0]["copied"])
        self.assertEqual(self.text_of(pid)[1], SECRET_TEXT.encode())

    def test_the_text_of_a_secret_when_the_keyring_is_down_is_an_error_not_a_missing_paste(self):
        _, pid, _ = self.leave("New login", SECRET_TEXT)
        self.vault.down = "the keyring is locked"
        self.assertEqual(self.text_of(pid)[0], 500)
        self.assertEqual([p["id"] for p in self.pastes()], [pid])      # still listed

    def test_done_deletes_the_keyring_item_and_the_record(self):
        _, pid, _ = self.leave("New login", SECRET_TEXT)
        self.assertEqual(self.post("/api/paste_done", {"id": pid}), 200)
        self.assertEqual((self.vault.items, self.pastes()), ({}, []))
        self.assertEqual(self.text_of(pid)[0], 404)

    def test_withdraw_deletes_the_keyring_item_and_the_record(self):
        _, pid, _ = self.leave("New login", SECRET_TEXT)
        self.assertEqual(self.command("withdraw", "a", pid)[0], 0)
        self.assertEqual((self.vault.items, self.pastes()), ({}, []))

    def test_a_plain_paste_done_does_not_call_the_keyring(self):
        _, pid, _ = self.leave("Plain", "just text")
        self.assertEqual(self.post("/api/paste_done", {"id": pid}), 200)
        self.assertEqual(self.vault.calls, [])

    def test_when_the_keyring_delete_fails_the_record_stays_and_done_says_it_failed(self):
        _, pid, _ = self.leave("New login", SECRET_TEXT)
        self.vault.fail_delete = True
        self.assertEqual(self.post("/api/paste_done", {"id": pid}), 500)
        code, _, err = self.command("withdraw", "a", pid)
        self.assertNotEqual(code, 0)
        self.assertIn("keyring", err)
        self.assertEqual([p["id"] for p in self.pastes()], [pid])
        self.assertIn(pid, self.vault.items)
        self.assertEqual(self.text_of(pid)[1], SECRET_TEXT.encode())     # nothing was half lost
        self.vault.fail_delete = False
        self.assertEqual(self.post("/api/paste_done", {"id": pid}), 200)
        self.assertEqual((self.vault.items, self.pastes()), ({}, []))
        self.assert_no_leak(TOKEN)

    def test_a_done_cut_short_after_the_keyring_delete_leaves_a_card_that_says_it_cannot_be_read(self):
        _, pid, _ = self.leave("New login", SECRET_TEXT)
        real = Path.unlink

        def failing(path, *a, **k):
            if path.suffix == ".json":
                raise PermissionError(1, "Operation not permitted")
            return real(path, *a, **k)
        with mock.patch.object(Path, "unlink", failing):
            self.assertEqual(self.post("/api/paste_done", {"id": pid}), 500)
        self.assertEqual(self.vault.items, {})
        self.assertEqual([p["id"] for p in self.pastes()], [pid])        # on the card, not hidden
        self.assertEqual(self.text_of(pid)[0], 404)                      # and it cannot be read
        self.assertEqual(self.post("/api/paste_done", {"id": pid}), 200)  # a tick finishes it
        self.assertEqual(self.pastes(), [])

    def test_a_keyring_that_cannot_be_reached_makes_the_command_fail_and_write_nothing(self):
        for reason in ("the keyring is locked", "the keyring cannot be reached (ServiceUnknown)"):
            self.vault.down = reason
            for flags in (("--secret",), ()):
                text = "pw " + TOKEN if not flags else "just a word"
                code, out, err = self.leave("New login", text, *flags)
                self.assertNotEqual(code, 0)
                self.assertEqual(out, "")
                self.assertIn(reason, err)
                self.assertNotIn(TOKEN, err)
                self.assertEqual([p for p in self.state.rglob("*") if p.is_file()], [])   # not even the lock
        self.assertEqual(self.pastes(), [])

    def test_a_keyring_that_goes_away_between_the_probe_and_the_put_makes_no_paste(self):
        def put(pid, text, store):
            self.vault.calls.append(("put", pid))
            raise vault.Unavailable("the keyring cannot be reached (test)")
        self.vault.put = put
        code, out, err = self.leave("New login", SECRET_TEXT)
        self.assertNotEqual(code, 0)
        self.assertEqual((out, self.vault.items, self.pastes(), self.store_bytes()), ("", {}, [], b""))
        self.assertEqual([p for p in self.state.rglob("*.txt")] + [p for p in self.state.rglob("*.json")], [])
        self.assert_no_leak(TOKEN)

    def test_a_record_that_cannot_be_written_takes_its_keyring_item_back(self):
        real = lines.write_atomic
        with mock.patch("lines.write_atomic", lambda path, text: False if str(path).endswith(".json") else real(path, text)):
            code, out, err = self.leave("New login", SECRET_TEXT)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.vault.items, {})
        self.assertEqual(self.pastes(), [])
        self.assert_no_leak(TOKEN)

    def test_a_keyring_item_that_cannot_be_taken_back_is_named_so_it_is_not_silent(self):
        real = lines.write_atomic
        self.vault.fail_delete = True
        with mock.patch("lines.write_atomic", lambda path, text: False if str(path).endswith(".json") else real(path, text)):
            code, out, err = self.leave("New login", SECRET_TEXT)
        self.assertNotEqual(code, 0)
        (pid,) = self.vault.items
        self.assertIn(pid, err)
        self.assertIn("sweep", err)
        self.assert_no_leak(TOKEN)

    def test_a_secret_paste_stays_on_a_gone_sessions_card_and_the_file_sweep_leaves_it_alone(self):
        """Tickets 02 and 03 meet: the card of a session that left holds a secret, masked; the
        roster poll's file sweep (old texts, old temp files) touches neither keyring nor record,
        and nothing of it is ever on disk; withdraw with the provider takes the keyring item."""
        code, pid, _ = self.leave("Token", "sk-test-" + "ab12" * 8, "--provider", "fake")
        self.assertEqual(code, 0)
        self.fake._sessions = []
        for prune in (lines.forget, seen.forget):
            prune(set())
        old = time.time() - 10 * paste.SWEEP_AFTER
        stray = paste.store() / "dead.tmp"
        stray.write_text("x")
        os.utime(stray, (old, old))
        self.vault.calls.clear()
        got = json.loads(self.get("/api/roster")[1])
        self.assertEqual(self.vault.calls, [])                  # the poll never asks the keyring
        self.assertFalse(stray.exists())                        # the file sweep did its work
        (card,) = got["kept"]
        (shown,) = card["pastes"]
        self.assertEqual((shown["id"], shown["secret"], shown["first"]), (pid, True, ""))
        self.assertNotIn(b"sk-test-", json.dumps(got).encode())
        self.assertEqual(sorted(self.vault.items), [pid])       # the item is still there
        self.assertEqual(self.text_of(pid)[1], ("sk-test-" + "ab12" * 8).encode())
        self.assertEqual(list(paste.store().glob("*.txt")), [])
        self.assertNotIn(b"sk-test-", self.everything_else())
        code, _, _ = self.command("withdraw", "a", "--provider", "other", pid)   # not its provider
        self.assertEqual((code, sorted(self.vault.items)), (1, [pid]))
        code, _, _ = self.command("withdraw", "a", "--provider", "fake", pid)
        self.assertEqual((code, self.vault.items), (0, {}))
        self.assertEqual(json.loads(self.get("/api/roster")[1])["kept"], [])

    def test_sweep_removes_keyring_items_no_record_points_at_and_names_records_without_an_item(self):
        _, kept, _ = self.leave("Kept", SECRET_TEXT)
        _, lost, _ = self.leave("Lost", SECRET_TEXT)
        self.vault.items.pop(lost)
        self.vault.items["f" * 16] = "stray"
        self.vault.stores["f" * 16] = paste._scope(paste.store())
        code, out, err = self.command("sweep")
        self.assertEqual(code, 0, err)
        self.assertIn("f" * 16, out)
        self.assertIn(lost, out)
        self.assertNotIn(kept, out)
        self.assertEqual(list(self.vault.items), [kept])
        self.assertEqual(self.command("withdraw", "a", lost)[0], 0)
        self.assertEqual(self.command("sweep"), (0, "", ""))             # nothing left to say once clean

    def test_sweep_keeps_the_item_of_a_record_it_could_not_read_in_time(self):
        code, pid, _ = self.leave("Token", "sk-test-" + "cd34" * 8)
        self.assertEqual(code, 0)
        with mock.patch.object(lines, "read_bounded", lambda path, limit: None):
            stray, lost = paste.sweep_keyring()
        self.assertEqual((stray, lost, sorted(self.vault.items)), ([], [], [pid]))
        self.assertEqual(self.text_of(pid)[1], ("sk-test-" + "cd34" * 8).encode())

    def test_the_note_to_delete_the_input_file_is_printed_when_the_record_read_is_slow(self):
        with mock.patch.object(lines, "read_bounded", lambda path, limit: None):
            code, pid, err = self.leave("Token", "sk-test-" + "ef56" * 8)
        self.assertEqual(code, 0)
        self.assertIn("delete it", err)

    def test_sweep_in_another_store_leaves_this_stores_items_alone(self):
        _, pid, _ = self.leave("Kept", SECRET_TEXT)
        other = self.tmp / "another-store"
        stray, lost = paste.sweep_keyring(other)
        self.assertEqual((stray, lost), ([], []))
        self.assertEqual(list(self.vault.items), [pid])
        self.assertEqual(self.text_of(pid)[1], SECRET_TEXT.encode())

    def test_the_command_says_when_it_kept_a_secret_so_the_file_can_go(self):
        code, pid, err = self.leave("New login", SECRET_TEXT)
        self.assertIn("delete", err)
        self.assertIn("in0.txt", err)
        self.assertNotIn(TOKEN, err)
        _, _, plain_err = self.leave("Plain", "just text")
        self.assertEqual(plain_err, "")

    def test_the_text_of_a_paste_is_refused_without_the_header_or_for_a_foreign_host(self):
        _, pid, _ = self.leave("New login", SECRET_TEXT)
        path = "/api/paste_text?id=" + pid
        self.assertEqual(self.get(path)[0], 403)
        self.assertEqual(self.get(path, {"X-Fleet": "1", "Host": "evil.example"})[0], 403)
        self.assertEqual(self.get(path, {"X-Fleet": "1", "Host": f"127.0.0.1:{self.httpd.server_port}"})[0], 200)
        self.assertEqual(self.get(path, {"X-Fleet": "1", "Host": f"localhost:{self.httpd.server_port}"})[0], 200)

    def test_sweep_with_the_keyring_down_fails_and_removes_nothing(self):
        self.leave("Kept", SECRET_TEXT)
        self.vault.down = "the keyring is locked"
        self.assertNotEqual(self.command("sweep")[0], 0)
        self.assertEqual(len(self.pastes()), 1)

    def test_a_put_whose_reply_is_lost_leaves_no_orphan_item(self):
        self.vault.put_times_out = True
        code, _, err = self.leave("Token", SECRET_TEXT)
        self.assertNotEqual(code, 0)
        self.assertIn("no Paste was made", err)
        self.assertEqual((self.vault.items, self.pastes()), ({}, []))

    def test_a_put_whose_reply_is_lost_and_cannot_be_taken_back_names_the_item(self):
        self.vault.put_times_out = self.vault.fail_delete = True
        code, _, err = self.leave("Token", SECRET_TEXT)
        self.assertNotEqual(code, 0)
        (pid,) = self.vault.items
        self.assertIn(pid, err)
        self.assertIn("sweep", err)
        self.assertNotIn(TOKEN, err)
        self.vault.fail_delete = self.vault.put_times_out = False
        self.assertEqual(self.command("sweep")[0], 0)           # the orphan is findable and goes
        self.assertEqual(self.vault.items, {})

    def test_a_put_the_keyring_refused_outright_makes_no_second_call_and_names_no_item(self):
        self.vault.put_refused = "the keyring is locked"
        code, _, err = self.leave("Token", SECRET_TEXT)
        self.assertNotEqual(code, 0)
        self.assertNotIn("sweep", err)
        self.assertIn(("put", None), [(op, None) for op, _ in self.vault.calls])      # it got as far as the put
        self.assertNotIn("delete", [op for op, _ in self.vault.calls])

    def test_a_title_that_looks_like_a_secret_is_refused_marked_or_not(self):
        for flags in ((), ("--secret",)):
            code, out, err = self.leave("password=" + "Tr0ub4dor&3x", "text", *flags)
            self.assertNotEqual(code, 0)
            self.assertIn("title", err)
            self.assertNotIn("Tr0ub4dor", err)
        code, _, err = self.leave(TOKEN, "text")
        self.assertNotEqual(code, 0)
        self.assertNotIn(TOKEN, err)
        self.assertEqual((self.vault.calls, self.pastes(), self.store_bytes()), ([], [], b""))

    def test_a_token_in_a_long_title_is_caught_before_the_title_is_clipped(self):
        # Clipped at 80 the token would be cut in two and no longer look like one.
        for lead in (60, 75, 90, 200):
            title = "Token for Sven " + "x" * lead + " " + TOKEN
            self.assertTrue(paste.credentials.looks_secret(title))
            self.assertFalse(paste.credentials.looks_secret(paste._clip(title, paste.TITLE_MAX)), lead)
            code, out, err = self.leave(title, "text")
            self.assertNotEqual(code, 0, lead)
            self.assertIn("title", err)
            self.assertNotIn(TOKEN[:12], err)
        self.assertEqual((self.vault.calls, self.pastes(), self.store_bytes()), ([], [], b""))

    def test_a_title_naming_the_secret_without_being_one_is_fine(self):
        self.assertEqual(self.leave("New login for the router", SECRET_TEXT)[0], 0)

    def test_nothing_of_the_text_is_in_a_log_an_error_or_a_temp_file(self):
        secrets_seen = (TOKEN, "toegang", "tab\there")
        _, pid, _ = self.leave("New login", SECRET_TEXT)
        self.text_of(pid)
        self.post("/api/paste_copied", {"id": pid})
        self.vault.fail_delete = True
        self.post("/api/paste_done", {"id": pid})
        self.command("withdraw", "a", pid)
        self.vault.fail_delete = False
        self.vault.down = "no"
        self.text_of(pid)
        self.leave("Another", SECRET_TEXT)
        self.assert_no_leak(*secrets_seen)

    def test_no_secret_text_reaches_a_subprocess(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("a subprocess")), \
                mock.patch("os.system", side_effect=AssertionError("a shell")):
            _, pid, _ = self.leave("New login", SECRET_TEXT)
            self.text_of(pid)
            self.post("/api/paste_done", {"id": pid})

    def test_the_command_in_a_process_of_its_own_fails_with_no_keyring_and_writes_nothing(self):
        if True:
            for text, flags in (("just a word", ["--secret"]), (SECRET_TEXT, [])):
                got = self.run_command("create", "a", "--title", "t", *flags, self.write(text, "real.txt"))
                self.assertNotEqual(got.returncode, 0)
                self.assertEqual(got.stdout, "")
                self.assertIn("keyring", got.stderr)
                self.assertNotIn(TOKEN, got.stderr)
                self.assertNotIn("just a word", got.stderr)
        self.assertEqual(self.store_bytes(), b"")


class Dbus(unittest.TestCase):
    """The Secret Service client against a stand-in for D-Bus, never the real keyring."""
    SECRET = "pw" + "-Zx9" + "-never-shown"

    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        self.bus_closed = 0

    def fake_connect(self, fail_with=None, locked=False, prompt="/", create_fails=None):
        calls = []
        secret = self.SECRET

        class Fake:
            def __init__(inner):
                inner.path = ""

            def get_object(inner, bus, path, introspect=True):
                inner.path = path
                return inner

            def close(inner):
                self.bus_closed += 1

        class Ifaces:
            String = staticmethod(lambda s, variant_level=0: s)
            Dictionary = staticmethod(lambda d, signature=None: d)
            Struct = staticmethod(lambda t, signature=None: t)
            ByteArray = staticmethod(lambda b: b)

            @staticmethod
            def Interface(obj, name):
                class I:
                    def OpenSession(i, kind, arg, timeout=None):
                        if fail_with:
                            raise fail_with
                        calls.append(("OpenSession", kind))
                        return "", "/session/1"

                    def ReadAlias(i, name, timeout=None):
                        return "/collection/login"

                    def Get(i, iface, prop, timeout=None):
                        return locked

                    def CreateItem(i, props, sec, replace, timeout=None):
                        if create_fails:
                            raise create_fails
                        calls.append(("CreateItem", sec[2]))
                        return "/item/1", prompt

                    def Dismiss(i, timeout=None):
                        calls.append(("Dismiss", obj.path))

                    def Close(i, timeout=None):
                        calls.append(("Close",))
                return I()
        return (lambda: (Ifaces, Fake())), calls

    def test_the_text_travels_in_the_message_and_the_session_is_closed(self):
        connect, calls = self.fake_connect()
        with mock.patch("vault._connect", connect), mock.patch("subprocess.Popen", side_effect=AssertionError("argv")):
            vault.put("a" * 16, self.SECRET, "s" * 16)
        self.assertIn(("CreateItem", self.SECRET.encode()), calls)
        self.assertEqual(calls[-1], ("Close",))

    def test_a_prompt_is_dismissed_and_the_text_refused(self):
        connect, calls = self.fake_connect(prompt="/prompt/7")
        with mock.patch("vault._connect", connect):
            with self.assertRaises(vault.Unavailable):
                vault.put("a" * 16, self.SECRET, "s" * 16)
        self.assertIn(("Dismiss", "/prompt/7"), calls)

    def test_a_backend_error_that_echoes_the_text_is_not_repeated(self):
        class Echo(Exception):
            pass
        connect, _ = self.fake_connect(fail_with=Echo("could not store " + self.SECRET))
        with mock.patch("vault._connect", connect):
            with self.assertRaises(vault.Unavailable) as caught:
                vault.put("a" * 16, self.SECRET, "s" * 16)
        self.assertNotIn(self.SECRET, str(caught.exception))
        self.assertNotIn(self.SECRET, repr(caught.exception.__cause__))

    def test_a_locked_keyring_is_unavailable_and_is_not_asked_to_unlock(self):
        connect, calls = self.fake_connect(locked=True)
        with mock.patch("vault._connect", connect):
            with self.assertRaises(vault.Unavailable) as caught:
                vault.put("a" * 16, self.SECRET, "s" * 16)
        self.assertIn("locked", str(caught.exception))
        self.assertNotIn("CreateItem", [c[0] for c in calls])

    def test_the_connection_is_closed_when_opening_the_session_fails(self):
        connect, _ = self.fake_connect(fail_with=RuntimeError("no session"))
        with mock.patch("vault._connect", connect):
            with self.assertRaises(vault.Unavailable):
                vault.put("a" * 16, self.SECRET, "s" * 16)
        self.assertEqual(self.bus_closed, 1)

    def test_a_create_that_gets_no_reply_is_unsure_not_merely_unavailable(self):
        connect, calls = self.fake_connect(create_fails=TimeoutError("no reply for " + self.SECRET))
        with mock.patch("vault._connect", connect):
            with self.assertRaises(vault.Unsure) as caught:
                vault.put("a" * 16, self.SECRET, "s" * 16)
        self.assertNotIn(self.SECRET, str(caught.exception))
        self.assertNotIn(self.SECRET, repr(caught.exception.__cause__))
        self.assertEqual((self.bus_closed, calls[-1]), (1, ("Close",)))

    def test_a_refusal_before_the_create_is_unavailable_and_not_unsure(self):
        connect, _ = self.fake_connect(locked=True)
        with mock.patch("vault._connect", connect):
            with self.assertRaises(vault.Unavailable) as caught:
                vault.put("a" * 16, self.SECRET, "s" * 16)
        self.assertNotIsInstance(caught.exception, vault.Unsure)

    def test_the_connection_is_closed_once_when_all_goes_well(self):
        connect, _ = self.fake_connect()
        with mock.patch("vault._connect", connect):
            vault.put("a" * 16, self.SECRET, "s" * 16)
        self.assertEqual(self.bus_closed, 1)

    def test_a_bus_that_is_not_there_is_unavailable(self):
        with mock.patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent/bus"}):
            with self.assertRaises(vault.Unavailable):
                vault.get("a" * 16, "s" * 16)


if __name__ == "__main__":
    unittest.main()
