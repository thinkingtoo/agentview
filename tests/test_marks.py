"""What you did with a session, one store: seen, read, pinned (`marks.py`).

Spec `docs/specs/2026-10-25-marks.md`. The facts stay apart in one record per
key; the lock covers every write; the old `seen.json` and `finished.json` are
imported once and never touched.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import log  # noqa: E402
import marks  # noqa: E402


class Dir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = self.tmp / "marks.json"


class Facts(Dir):
    def test_a_missing_file_loads_empty(self):
        self.assertEqual(marks.load(self.path), {})

    def test_seen_is_ready_until_the_stop_is_marked(self):
        state = marks.load(self.path)
        self.assertTrue(marks.ready("fake:a", 100, state))
        marks.mark("fake:a", 100, False, self.path)
        state = marks.load(self.path)
        self.assertFalse(marks.ready("fake:a", 100, state))
        self.assertTrue(marks.ready("fake:a", 200, state))

    def test_no_stop_is_never_ready(self):
        self.assertFalse(marks.ready("fake:a", None, marks.load(self.path)))
        self.assertFalse(marks.ready("fake:a", 0, marks.load(self.path)))

    def test_mark_without_read_leaves_the_handover_unread(self):
        marks.mark("fake:a", 100, False, self.path)
        state = marks.load(self.path)
        self.assertEqual(state, {"fake:a": {"seen": 100}})
        self.assertFalse(marks.is_read("fake:a", 100, state))

    def test_mark_with_read_writes_both_stops_in_one_record(self):
        marks.mark("fake:a", 100, True, self.path)
        state = marks.load(self.path)
        self.assertEqual(state, {"fake:a": {"seen": 100, "read": 100}})
        self.assertTrue(marks.is_read("fake:a", 100, state))
        self.assertFalse(marks.is_read("fake:a", 200, state))

    def test_a_later_stop_is_unread_and_ready_again(self):
        marks.mark("fake:a", 100, True, self.path)
        marks.mark("fake:a", 200, False, self.path)
        state = marks.load(self.path)
        self.assertEqual(state["fake:a"], {"seen": 200, "read": 100})
        self.assertTrue(marks.ready("fake:a", 300, state))
        self.assertFalse(marks.is_read("fake:a", 200, state))

    def test_no_stop_leaves_the_tmp_file_names_out_of_the_directory(self):
        marks.mark("fake:a", 100, True, self.path)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["marks.json"])

    def test_the_temp_file_name_carries_pid_and_thread(self):
        names = []
        real = Path.replace
        with mock.patch.object(Path, "replace", lambda self_, t: (names.append(self_.name), real(self_, t))[1]):
            marks.mark("fake:a", 100, True, self.path)
        self.assertTrue(names)
        for name in names:
            self.assertIn(f".{os.getpid()}.{threading.get_ident()}.", name)

    def test_a_mark_without_a_key_or_stop_writes_nothing(self):
        marks.mark("fake:a", 0, True, self.path)
        marks.mark("", 100, True, self.path)
        marks.mark("fake:a", None, False, self.path)
        self.assertFalse(self.path.exists() and marks.load(self.path))

    def test_a_pin_lands_in_the_same_file_as_the_marks(self):
        marks.mark("fake:a", 100, True, self.path)
        marks.pin("fake:a", True, self.path)
        marks.pin("fake:b", True, self.path)
        on_disk = json.loads(self.path.read_text())
        self.assertEqual(on_disk, {"fake:a": {"seen": 100, "read": 100, "pinned": True},
                                   "fake:b": {"pinned": True}})
        state = marks.load(self.path)
        self.assertTrue(marks.pinned("fake:a", state))
        self.assertFalse(marks.pinned("fake:c", state))

    def test_unpin_removes_the_field_and_an_empty_record(self):
        marks.mark("fake:a", 100, False, self.path)
        marks.pin("fake:a", True, self.path)
        marks.pin("fake:b", True, self.path)
        marks.pin("fake:a", False, self.path)
        marks.pin("fake:b", False, self.path)
        marks.pin("fake:never", False, self.path)
        self.assertEqual(marks.load(self.path), {"fake:a": {"seen": 100}})

    def test_the_other_facts_survive_a_pin_and_a_mark(self):
        marks.pin("fake:a", True, self.path)
        marks.mark("fake:a", 100, True, self.path)
        self.assertEqual(marks.load(self.path), {"fake:a": {"seen": 100, "read": 100, "pinned": True}})

    def test_load_holds_every_session_with_any_mark(self):
        marks.mark("fake:a", 100, False, self.path)
        marks.pin("fake:b", True, self.path)
        self.assertEqual(set(marks.load(self.path)), {"fake:a", "fake:b"})

    def test_forget_drops_exactly_the_keys_given(self):
        for key in ("fake:a", "fake:b", "codex:a"):
            marks.mark(key, 100, True, self.path)
            marks.pin(key, True, self.path)
        marks.forget({"fake:b"}, self.path)
        self.assertEqual(set(marks.load(self.path)), {"fake:a", "codex:a"})
        marks.forget({"claude:x"}, self.path)
        self.assertEqual(set(marks.load(self.path)), {"fake:a", "codex:a"})

    def test_forget_with_nothing_to_drop_does_not_rewrite(self):
        marks.mark("fake:a", 100, False, self.path)
        before = self.path.stat().st_mtime_ns
        marks.forget({"fake:zz"}, self.path)
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_junk_in_the_file_is_left_out(self):
        self.path.write_text(json.dumps({
            "fake:ok": {"seen": 1, "read": 2, "pinned": True},
            "fake:bool": {"seen": True, "read": "x", "pinned": "yes"},
            "fake:str": "nope", "fake:empty": {}}))
        self.assertEqual(marks.load(self.path), {"fake:ok": {"seen": 1, "read": 2, "pinned": True}})

    def test_writes_never_raise(self):
        blocked = self.tmp / "file"
        blocked.write_text("x")
        path = blocked / "marks.json"
        marks.mark("fake:a", 100, True, path)
        marks.pin("fake:a", True, path)
        marks.forget({"fake:a"}, path)
        self.assertEqual(marks.load(path), {})

    def test_the_store_follows_xdg_state_home(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.tmp)}):
            self.assertEqual(marks.store(), self.tmp / "agentview" / "marks.json")


class OneLock(Dir):
    """The losing interleaving, forced: the click reads the file, is held at
    that point until the round has done its whole write (or a short timeout
    says it cannot, because the lock keeps it out), and only then writes. An
    unlocked pair loses the round's write every time; a locked pair never."""

    def interleave(self, click, round_):
        real = marks.load
        read = threading.Event()
        round_done = threading.Event()
        first = []

        def load(path=None):
            got = real(path)
            if threading.current_thread().name == "click" and not first:
                first.append(1)
                read.set()
                round_done.wait(0.5)
            return got

        def run_click():
            click()

        def run_round():
            read.wait(5)
            round_()
            round_done.set()

        with mock.patch.object(marks, "load", load):
            threads = [threading.Thread(target=run_click, name="click"),
                       threading.Thread(target=run_round, name="round")]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

    def test_a_mark_and_a_forget_of_another_key_both_land(self):
        marks.mark("fake:gone", 100, True, self.path)
        self.interleave(lambda: marks.mark("fake:live", 200, True, self.path),
                        lambda: marks.forget({"fake:gone"}, self.path))
        self.assertEqual(marks.load(self.path), {"fake:live": {"seen": 200, "read": 200}})

    def test_a_pin_and_a_forget_of_another_key_both_land(self):
        marks.mark("fake:gone", 100, True, self.path)
        self.interleave(lambda: marks.pin("fake:live", True, self.path),
                        lambda: marks.forget({"fake:gone"}, self.path))
        self.assertEqual(marks.load(self.path), {"fake:live": {"pinned": True}})

    def test_a_forget_and_a_mark_the_other_way_round_both_land(self):
        marks.mark("fake:gone", 100, True, self.path)
        real = marks.load
        read = threading.Event()
        done = threading.Event()

        def load(path=None):
            got = real(path)
            if threading.current_thread().name == "round" and not read.is_set():
                read.set()
                done.wait(0.5)
            return got

        def click():
            read.wait(5)
            marks.mark("fake:live", 200, True, self.path)
            done.set()
        with mock.patch.object(marks, "load", load):
            threads = [threading.Thread(target=lambda: marks.forget({"fake:gone"}, self.path),
                                        name="round"),
                       threading.Thread(target=click, name="click")]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(marks.load(self.path), {"fake:live": {"seen": 200, "read": 200}})

    def test_many_threads_all_land(self):
        def work(n):
            for i in range(10):
                marks.mark(f"fake:{n}-{i}", 100 + i, True, self.path)
                marks.pin(f"fake:{n}-{i}", True, self.path)
        threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        state = marks.load(self.path)
        self.assertEqual(len(state), 60)
        self.assertTrue(all(marks.pinned(k, state) and marks.is_read(k, r["seen"], state)
                            for k, r in state.items()))
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])


class Import(Dir):
    """The first load that finds no `marks.json` builds it from the two old
    files, and writes it at once. The old files are never written."""

    def old(self, seen=None, finished=None):
        if seen is not None:
            (self.tmp / "seen.json").write_text(seen if isinstance(seen, str) else json.dumps(seen))
        if finished is not None:
            (self.tmp / "finished.json").write_text(
                finished if isinstance(finished, str) else json.dumps(finished))
        return {p.name: p.read_bytes() for p in self.tmp.glob("*.json") if p.name != "marks.json"}

    def untouched(self, before):
        after = {p.name: p.read_bytes() for p in self.tmp.glob("*.json") if p.name != "marks.json"}
        self.assertEqual(after, before)

    def test_from_both_files(self):
        before = self.old({"fake:a": 100, "fake:b": 200},
                          {"read": {"fake:a": 100}, "pinned": ["fake:b", "fake:c"]})
        got = marks.load(self.path)
        self.assertEqual(got, {"fake:a": {"seen": 100, "read": 100},
                               "fake:b": {"seen": 200, "pinned": True},
                               "fake:c": {"pinned": True}})
        self.assertEqual(json.loads(self.path.read_text()), got)
        self.untouched(before)

    def test_from_the_seen_file_only(self):
        before = self.old(seen={"fake:a": 100})
        self.assertEqual(marks.load(self.path), {"fake:a": {"seen": 100}})
        self.untouched(before)

    def test_from_the_finished_file_only(self):
        before = self.old(finished={"read": {"fake:a": 100}, "pinned": ["fake:a"]})
        self.assertEqual(marks.load(self.path), {"fake:a": {"read": 100, "pinned": True}})
        self.untouched(before)

    def test_a_bare_id_gets_the_default_provider(self):
        before = self.old({"abc": 100, "codex:def": 200},
                          {"read": {"abc": 100}, "pinned": ["abc"]})
        self.assertEqual(marks.load(self.path), {
            "claude:abc": {"seen": 100, "read": 100, "pinned": True},
            "codex:def": {"seen": 200}})
        self.untouched(before)

    def test_a_corrupt_old_file_is_left_out_and_the_other_still_imports(self):
        before = self.old(seen="{not json", finished={"read": {"fake:a": 100}, "pinned": []})
        self.assertEqual(marks.load(self.path), {"fake:a": {"read": 100}})
        self.untouched(before)
        before = {}
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)
        (other / "seen.json").write_text(json.dumps({"fake:a": 100}))
        (other / "finished.json").write_text("[1, 2")
        self.assertEqual(marks.load(other / "marks.json"), {"fake:a": {"seen": 100}})

    def test_a_bare_id_and_its_prefixed_id_the_later_one_in_the_file_wins(self):
        """`seen.migrate` was a dict comprehension: the later key overwrote."""
        self.old('{"abc": 100, "claude:abc": 200}', '{"read": {"claude:abc": 50, "abc": 60}, "pinned": []}')
        self.assertEqual(marks.load(self.path), {"claude:abc": {"seen": 200, "read": 60}})
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)
        (other / "seen.json").write_text('{"claude:abc": 200, "abc": 100}')
        self.assertEqual(marks.load(other / "marks.json"), {"claude:abc": {"seen": 100}})

    def test_malformed_stops_are_left_out_booleans_too(self):
        self.old({"fake:a": True, "fake:b": "100", "fake:c": None, "fake:d": 5.5, "fake:e": 7},
                 {"read": {"fake:a": False, "fake:b": [1], "fake:c": 3},
                  "pinned": ["fake:p", 3, None, "fake:p"]})
        self.assertEqual(marks.load(self.path), {
            "fake:d": {"seen": 5.5}, "fake:e": {"seen": 7},
            "fake:c": {"read": 3}, "fake:p": {"pinned": True}})

    def test_no_old_file_at_all_loads_empty(self):
        self.assertEqual(marks.load(self.path), {})

    def test_it_happens_once(self):
        self.old({"fake:a": 100})
        marks.load(self.path)
        marks.forget({"fake:a"}, self.path)
        self.assertEqual(marks.load(self.path), {})            # not brought back from seen.json

    def test_marks_written_after_the_import_do_not_touch_the_old_files(self):
        before = self.old({"fake:a": 100}, {"read": {"fake:a": 100}, "pinned": []})
        marks.mark("fake:a", 300, True, self.path)
        marks.pin("fake:a", True, self.path)
        self.untouched(before)

    def test_an_unreadable_marks_file_loads_empty_and_is_not_rebuilt(self):
        before = self.old({"fake:a": 100})
        self.path.write_text("{broken")
        self.assertEqual(marks.load(self.path), {})
        self.assertEqual(self.path.read_text(), "{broken")
        self.untouched(before)

    def test_a_marks_file_that_is_not_an_object_loads_empty_and_is_not_rebuilt(self):
        self.old({"fake:a": 100})
        self.path.write_text("[1]")
        self.assertEqual(marks.load(self.path), {})
        self.assertEqual(self.path.read_text(), "[1]")

    def broken(self):
        return sorted(self.tmp.glob("marks.json.broken-*"))

    def test_a_write_on_an_unreadable_file_sets_it_aside_first(self):
        writes = {
            "mark": lambda: marks.mark("fake:a", 100, True, self.path),
            "pin": lambda: marks.pin("fake:a", True, self.path),
            "forget": lambda: marks.forget({"fake:zz"}, self.path),
        }
        for name, write in writes.items():
            for junk in ("{broken", "[1]", ""):
                with self.subTest(write=name, junk=junk):
                    for f in self.broken():
                        f.unlink()
                    self.path.write_text(junk)
                    write()
                    kept = self.broken()
                    self.assertEqual([f.read_text() for f in kept], [junk])
                    if name == "forget":
                        self.assertEqual(marks.load(self.path), {})
                    else:
                        self.assertEqual(list(marks.load(self.path)), ["fake:a"])

    def test_a_write_after_the_move_is_not_rebuilt_from_the_old_files(self):
        before = self.old({"fake:x": 100}, {"read": {"fake:x": 100}, "pinned": ["fake:x"]})
        self.path.write_text("{broken")
        marks.mark("fake:a", 100, False, self.path)
        self.assertEqual(marks.load(self.path), {"fake:a": {"seen": 100}})
        self.untouched(before)

    def test_a_forget_with_nothing_to_drop_does_not_let_the_next_load_rebuild(self):
        before = self.old({"fake:x": 100}, {"read": {"fake:x": 100}, "pinned": ["fake:x"]})
        self.path.write_text("{broken")
        marks.forget(set(), self.path)
        self.assertEqual(len(self.broken()), 1)
        self.assertEqual(marks.load(self.path), {})
        self.assertEqual(marks.load(self.path), {})
        self.untouched(before)

    def test_a_read_error_on_a_healthy_file_is_not_a_broken_file(self):
        marks.mark("fake:a", 100, True, self.path)
        real = Path.open

        def flaky(p, *a, **k):
            if p == self.path:
                raise OSError(24, "too many open files")
            return real(p, *a, **k)
        with mock.patch.object(Path, "open", flaky):
            marks.forget(set(), self.path)
            marks.mark("fake:b", 100, True, self.path)
            marks.pin("fake:a", True, self.path)
        self.assertEqual(self.broken(), [])
        self.assertEqual(marks.load(self.path), {"fake:a": {"seen": 100, "read": 100}})

    def test_a_failed_fresh_write_puts_the_broken_file_back_and_does_not_rebuild(self):
        before = self.old({"fake:x": 100})
        self.path.write_text("{broken")
        real = Path.open

        def full(p, *a, **k):
            if p.name.endswith(".tmp"):
                raise OSError(28, "no space left")
            return real(p, *a, **k)
        with mock.patch.object(Path, "open", full):
            marks.forget(set(), self.path)
        self.assertEqual(self.path.read_text(), "{broken")
        self.assertEqual(self.broken(), [])
        self.assertEqual(marks.load(self.path), {})
        self.untouched(before)

    def test_a_file_nobody_may_read_or_that_is_a_directory_or_too_deep_is_broken(self):
        real = Path.open
        cases = {
            "denied": lambda: self.path.write_text("{}"),
            "directory": lambda: self.path.mkdir(),
            "deep": lambda: self.path.write_text("[" * 200000),
        }
        for name, make in cases.items():
            with self.subTest(case=name):
                for f in self.broken():
                    if f.is_dir():
                        f.rmdir()
                    else:
                        f.unlink()
                if self.path.is_dir():
                    self.path.rmdir()
                else:
                    self.path.unlink(missing_ok=True)
                make()

                def denied(p, *a, **k):
                    if name == "denied" and p == self.path:
                        raise PermissionError(13, "denied")
                    return real(p, *a, **k)
                with mock.patch.object(Path, "open", denied):
                    marks.mark("fake:a", 100, True, self.path)
                self.assertEqual(len(self.broken()), 1)
                self.assertEqual(marks.load(self.path), {"fake:a": {"seen": 100, "read": 100}})

    def test_two_broken_files_in_one_second_are_both_kept(self):
        with mock.patch.object(marks.time, "strftime", return_value="T"):
            for junk in ("{one", "{two"):
                self.path.write_text(junk)
                marks.pin("fake:a", True, self.path)
        self.assertEqual(sorted(f.read_text() for f in self.broken()), ["{one", "{two"])

    def test_a_readable_file_is_never_set_aside(self):
        marks.mark("fake:a", 100, False, self.path)
        marks.pin("fake:a", True, self.path)
        marks.forget({"fake:zz"}, self.path)
        self.assertEqual(self.broken(), [])

    def test_a_file_that_cannot_be_set_aside_is_left_alone_and_nothing_raises(self):
        self.path.write_text("{broken")
        with mock.patch.object(Path, "replace", side_effect=PermissionError("no")):
            marks.mark("fake:a", 100, True, self.path)
            marks.pin("fake:a", True, self.path)
            marks.forget({"fake:a"}, self.path)
        self.assertEqual(self.path.read_text(), "{broken")
        self.assertEqual(self.broken(), [])

    def test_two_first_loads_at_once_import_once(self):
        self.old({"fake:a": 100})
        got = []
        starter = threading.Barrier(4)

        def first():
            starter.wait()
            got.append(marks.load(self.path))
        threads = [threading.Thread(target=first) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(got, [{"fake:a": {"seen": 100}}] * 4)

    def test_a_mark_that_races_the_first_load_is_not_lost(self):
        """The import runs under the lock: a writer that arrives first imports,
        then adds; it never writes over the import with a bare record."""
        self.old({"fake:a": 100})
        marks.mark("fake:b", 5, False, self.path)
        self.assertEqual(marks.load(self.path), {"fake:a": {"seen": 100}, "fake:b": {"seen": 5}})


def failing_open(*paths, errno=5):
    """`Path.open` raising a read error (EIO by default) for these paths."""
    real = Path.open
    names = {Path(p) for p in paths}

    def flaky(p, *a, **k):
        if p in names:
            raise OSError(errno, "input/output error")
        return real(p, *a, **k)
    return mock.patch.object(Path, "open", flaky)


class Logged(Dir):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(log, "LOG", self.tmp / "events.jsonl")
        patcher.start()
        self.addCleanup(patcher.stop)

    def skipped(self):
        if not log.LOG.exists():
            return []
        lines = [json.loads(l) for l in log.LOG.read_text().splitlines()]
        return [l for l in lines if l["kind"] == "marks_skipped"]


class PersistentReadError(Logged):
    """A read error that does not clear leaves the file alone, and a line in
    the log, once per state change and not once per poll (ticket 03)."""

    def test_skipped_writers_leave_one_line_and_write_nothing(self):
        marks.mark("fake:a", 100, True, self.path)
        before = self.path.read_bytes()
        with failing_open(self.path):
            for _ in range(3):
                marks.mark("fake:b", 100, True, self.path)
                marks.pin("fake:a", True, self.path)
                marks.forget({"fake:a"}, self.path)
        self.assertEqual(self.path.read_bytes(), before)
        lines = self.skipped()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["path"], str(self.path))

    def test_a_recovered_read_stops_logging_and_a_new_failure_logs_again(self):
        marks.mark("fake:a", 100, True, self.path)
        with failing_open(self.path):
            marks.mark("fake:b", 100, True, self.path)
        self.assertEqual(len(self.skipped()), 1)
        marks.mark("fake:b", 100, True, self.path)
        marks.pin("fake:b", True, self.path)
        self.assertEqual(len(self.skipped()), 1)
        self.assertIn("fake:b", marks.load(self.path))
        with failing_open(self.path):
            marks.mark("fake:c", 100, True, self.path)
        self.assertEqual(len(self.skipped()), 2)

    def test_a_readable_store_logs_nothing(self):
        marks.mark("fake:a", 100, True, self.path)
        marks.pin("fake:a", True, self.path)
        marks.forget({"fake:z"}, self.path)
        self.assertEqual(self.skipped(), [])


    def test_a_broken_file_that_cannot_be_set_aside_logs_once(self):
        self.path.write_text("{broken")
        with mock.patch.object(Path, "replace", side_effect=PermissionError("no")):
            marks.mark("fake:a", 100, True, self.path)
            marks.pin("fake:a", True, self.path)
        self.assertEqual(len(self.skipped()), 1)


class ImportReadError(Logged):
    """An old file that fails to read for a reason other than "not there" makes
    no `marks.json` this round; the import retries once the read works
    (ticket 04)."""

    def setUp(self):
        super().setUp()
        (self.tmp / "seen.json").write_text(json.dumps({"fake:a": 100}))
        (self.tmp / "finished.json").write_text(
            json.dumps({"read": {"fake:a": 100}, "pinned": ["fake:b"]}))
        self.want = {"fake:a": {"seen": 100, "read": 100}, "fake:b": {"pinned": True}}

    def test_a_read_error_on_seen_writes_nothing_and_the_next_load_imports_all(self):
        with failing_open(self.tmp / "seen.json"):
            self.assertEqual(marks.load(self.path), {})
            self.assertFalse(self.path.exists())
        self.assertEqual(marks.load(self.path), self.want)

    def test_a_read_error_on_finished_writes_nothing_and_the_next_load_imports_all(self):
        with failing_open(self.tmp / "finished.json"):
            self.assertEqual(marks.load(self.path), {})
            self.assertFalse(self.path.exists())
        self.assertEqual(marks.load(self.path), self.want)

    def test_a_writer_does_not_start_the_file_without_the_old_records(self):
        with failing_open(self.tmp / "seen.json"):
            marks.mark("fake:c", 300, True, self.path)
            marks.pin("fake:c", True, self.path)
            marks.forget({"fake:z"}, self.path)
            self.assertFalse(self.path.exists())
        self.assertEqual(len(self.skipped()), 1)
        marks.mark("fake:c", 300, True, self.path)
        self.assertEqual(marks.load(self.path),
                         {**self.want, "fake:c": {"seen": 300, "read": 300}})

    def test_the_import_recovering_lets_the_next_failure_log_again(self):
        with failing_open(self.tmp / "seen.json"):
            marks.mark("fake:c", 300, True, self.path)
        self.assertEqual(len(self.skipped()), 1)
        marks.load(self.path)                      # imports; the file exists now
        with failing_open(self.path):
            marks.mark("fake:c", 300, True, self.path)
        self.assertEqual(len(self.skipped()), 2)

    def test_a_missing_old_file_still_counts_as_empty(self):
        (self.tmp / "seen.json").unlink()
        self.assertEqual(marks.load(self.path),
                         {"fake:a": {"read": 100}, "fake:b": {"pinned": True}})
        self.assertTrue(self.path.exists())


if __name__ == "__main__":
    unittest.main()
