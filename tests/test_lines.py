"""The per-session line a session writes about itself when it stops.

Two fields and a count: where the work stands (`did`), and the one thing it
is blocked on (`ask`), or how many things there are (`n`). The file is
written by a Stop hook running inside the session, and read by the page.
"""
import contextlib
import json
import os
import resource
import signal
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lines


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_a_session_with_no_line_reads_empty(self):
        self.assertEqual(lines.read("abc", self.root), {})

    def test_what_a_session_wrote_comes_back(self):
        lines.write("abc", did="Design settled, nothing written yet.",
                    ask="", n=4, root=self.root)
        got = lines.read("abc", self.root)
        self.assertEqual(got["did"], "Design settled, nothing written yet.")
        self.assertEqual(got["n"], 4)
        self.assertEqual(got["ask"], "")

    def test_a_single_ask_keeps_its_own_words(self):
        # The whole point of the rule of one: one blocked question is short
        # enough to answer from the page.
        lines.write("abc", did="Corpus definito.",
                    ask="Aspetto solo la tua riga sul corpus", n=1,
                    root=self.root)
        self.assertEqual(lines.read("abc", self.root)["ask"],
                         "Aspetto solo la tua riga sul corpus")

    def test_a_file_nested_deeper_than_json_can_read_reads_as_no_line(self):
        # Nothing the hook writes looks like this, but the folder is anyone's to
        # write in, and "never raises" is what keeps the page up.
        depth = 70000
        (self.root / "abc.json").write_text(
            '{"ask": ' + "[" * depth + "]" * depth + ', "n": 1, "at": 1}', encoding="utf-8")
        self.assertEqual(lines.read("abc", self.root), {})
        self.assertEqual(lines.fresh("abc", self.root), {})

    def test_a_damaged_file_reads_as_no_line(self):
        # A hook killed mid-write must never take the page down with it.
        (self.root / "abc.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(lines.read("abc", self.root), {})

    def test_a_line_is_dropped_when_the_session_goes_back_to_work(self):
        # A need written at the last stop is answered by the prompt that
        # restarted it. Keeping it would make the page lie.
        lines.write("abc", did="x", ask="y", n=1, root=self.root)
        lines.drop("abc", self.root)
        self.assertEqual(lines.read("abc", self.root), {})

    def test_dropping_a_line_that_is_not_there_is_quiet(self):
        lines.drop("nobody", self.root)

    def test_lines_of_dead_sessions_are_forgotten(self):
        lines.write("alive", did="x", ask="", n=0, root=self.root)
        lines.write("dead", did="x", ask="", n=0, root=self.root)
        lines.forget({"alive"}, self.root)
        self.assertEqual(lines.read("dead", self.root), {})
        self.assertNotEqual(lines.read("alive", self.root), {})

    def test_a_session_id_cannot_escape_the_directory(self):
        # The id arrives from a hook payload. It names a file.
        lines.write("../../evil", did="x", ask="", n=0, root=self.root)
        self.assertFalse((self.root.parent.parent / "evil.json").exists())


class WhatIsKept(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_a_line_is_clipped_rather_than_wrapped(self):
        # A model handed a paragraph instead of a line would push every card
        # below it off the screen.
        lines.write("abc", did="x" * 400, ask="", n=0, root=self.root)
        self.assertLessEqual(len(lines.read("abc", self.root)["did"]), lines.LIMIT)

    def test_a_count_that_is_not_a_number_reads_as_none_wanted(self):
        (self.root / "abc.json").write_text(
            json.dumps({"did": "x", "ask": "", "n": "four", "at": 1}), encoding="utf-8")
        self.assertEqual(lines.read("abc", self.root)["n"], 0)


class HandWritten(unittest.TestCase):
    """The folder is anyone's to write in. Whatever is at a session's path, the
    page's poll neither waits on it, nor raises, nor reads without end: one such
    file would otherwise hold the lock every poll takes, until a restart."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    @contextlib.contextmanager
    def guarded(self, seconds=5, megabytes=400):
        """Fail, rather than hang or eat the machine, if reading does either."""
        def hung(*_):
            raise AssertionError(f"still reading after {seconds} s")
        old = signal.signal(signal.SIGALRM, hung)
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        with open("/proc/self/statm") as fh:
            size = int(fh.read().split()[0]) * resource.getpagesize()
        resource.setrlimit(resource.RLIMIT_AS, (size + megabytes * 1024 * 1024, hard))
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            resource.setrlimit(resource.RLIMIT_AS, (soft, hard))
            signal.signal(signal.SIGALRM, old)

    def test_a_pipe_where_the_line_should_be_reads_as_no_line(self):
        os.mkfifo(self.root / "abc.json")
        with self.guarded():
            self.assertEqual(lines.read("abc", self.root), {})
            self.assertEqual(lines.fresh("abc", self.root), {})

    def test_a_pipe_where_the_turn_should_be_reads_as_no_turn(self):
        os.mkfifo(self.root / "abc.turn")
        with self.guarded():
            self.assertEqual(lines.current_turn("abc", self.root), "")

    def test_a_file_that_has_no_end_reads_as_nothing(self):
        for name in ("abc.json", "abc.turn"):
            (self.root / name).symlink_to("/dev/zero")
        with self.guarded():
            self.assertEqual(lines.read("abc", self.root), {})
            self.assertEqual(lines.current_turn("abc", self.root), "")

    def test_a_file_far_larger_than_any_line_reads_as_no_line(self):
        record = {"did": "x", "ask": "y", "n": 1, "at": 1, "pad": "z" * lines.MAX_BYTES}
        (self.root / "abc.json").write_text(json.dumps(record), encoding="utf-8")
        with self.guarded():
            self.assertEqual(lines.read("abc", self.root), {})
        # A whole line followed by more than a line can be is not one either.
        (self.root / "abc.json").write_text(
            json.dumps({"did": "x", "ask": "y", "n": 1, "at": 1}) + " " * (lines.MAX_BYTES + 1), encoding="utf-8")
        with self.guarded():
            self.assertEqual(lines.read("abc", self.root), {})

    def test_a_link_to_a_terminal_does_not_make_it_the_polls_terminal(self):
        # A process that leads its own session and has none (the service) takes a
        # terminal it merely opens, and is sent SIGHUP when that terminal closes.
        child = (
            "import os, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import lines\n"
            "os.setsid()\n"
            "master, slave = os.openpty()\n"
            "name = os.ttyname(slave)\n"
            "os.close(slave)\n"
            "root = sys.argv[2]\n"
            "os.symlink(name, root + '/abc.json')\n"
            "os.symlink(name, root + '/abc.turn')\n"
            "assert lines.read('abc', root) == {} and lines.current_turn('abc', root) == ''\n"
            "try:\n"
            "    os.close(os.open('/dev/tty', os.O_RDONLY))\n"
            "except OSError:\n"
            "    sys.exit(0)\n"
            "sys.exit(7)\n")
        done = subprocess.run([sys.executable, "-B", "-c", child, str(Path(lines.__file__).parent), str(self.root)],
                              capture_output=True, timeout=30)
        self.assertEqual(done.returncode, 0, "the process took a terminal it only opened")

    def test_a_pipe_is_refused_at_once_and_not_after_the_time_bound(self):
        # The time bound would hide a read that waits on the pipe: the answer is the
        # same, only half a second late and with a thread left waiting for ever.
        for name in ("abc.json", "abc.turn"):
            os.mkfifo(self.root / name)
        for call in (lines.read, lines.current_turn):
            t0 = time.monotonic()
            call("abc", self.root)
            self.assertLess(time.monotonic() - t0, lines.READ_BUDGET / 2)
        self.assertEqual(lines._reading, {})

    def test_only_the_bound_is_read_of_a_larger_file(self):
        (self.root / "big").write_bytes(b"0123456789" * 100)
        self.assertEqual(lines._small_bytes(self.root / "big", 10), b"0123456789")
        self.assertEqual(lines._plain_bytes(self.root / "big", 10), b"0123456789")

    def test_a_file_that_cannot_be_read_is_none_and_not_a_raise(self):
        self.assertIsNone(lines._plain_bytes("/proc/self/mem", 10))
        self.assertIsNone(lines._plain_bytes(str(self.root) + "/a\0b", 10))
        self.assertIsNone(lines._plain_bytes(self.root / "missing", 10))

    def test_a_run_of_openers_inside_the_bound_reads_as_no_line(self):
        # No closer: this is the file json gives up on with a stack overflow on the Python
        # that runs the service, where a file with its closers parses.
        (self.root / "abc.json").write_text('{"ask": ' + "[" * 60000, encoding="utf-8")
        self.assertEqual(lines.read("abc", self.root), {})

    def test_reading_leaves_no_file_open(self):
        (self.root / "abc.json").write_text(json.dumps({"did": "x", "ask": "y", "n": 1, "at": 1}), encoding="utf-8")
        (self.root / "abc.turn").write_text("0123abcd", encoding="utf-8")
        os.mkfifo(self.root / "fifo.json")
        (self.root / "dir.json").mkdir()
        before = len(os.listdir("/proc/self/fd"))
        with self.guarded():
            for _ in range(60):
                for sid in ("abc", "fifo", "dir", "missing"):
                    lines.read(sid, self.root)
                    lines.current_turn(sid, self.root)
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_a_turn_that_is_not_text_reads_as_no_turn(self):
        (self.root / "abc.turn").write_bytes(b"\xff\xfe")
        self.assertEqual(lines.current_turn("abc", self.root), "")

    def test_a_file_that_cannot_be_read_reads_as_no_line(self):
        # /proc/self/mem is a plain file as far as stat can say, and refuses to be read from 0.
        for name in ("abc.json", "abc.turn"):
            (self.root / name).symlink_to("/proc/self/mem")
        with self.guarded():
            self.assertEqual((lines.read("abc", self.root), lines.current_turn("abc", self.root)), ({}, ""))

    def test_a_file_of_8_gigabytes_is_not_read_whole(self):
        try:
            with open(self.root / "abc.json", "wb") as fh:
                fh.truncate(8 << 30)
        except OSError:
            self.skipTest("no sparse files here")
        with self.guarded():
            self.assertEqual(lines.read("abc", self.root), {})

    def test_a_value_nested_deep_inside_the_bound_is_no_ask(self):
        depth = 30000        # 60 KB: under the bound, so json reads it (or an older Python stops at its limit)
        (self.root / "abc.json").write_text(
            '{"ask": ' + "[" * depth + "]" * depth + ', "n": 1, "at": 1}', encoding="utf-8")
        got = lines.read("abc", self.root)
        self.assertEqual(got.get("ask", ""), "")

    def test_what_the_hook_writes_is_far_below_the_bound(self):
        lines.write("abc", did="\u00e9" * 400, ask="\U0001f600" * 400, n=1, root=self.root)
        self.assertLess((self.root / "abc.json").stat().st_size, lines.MAX_BYTES // 4)
        self.assertEqual(lines.read("abc", self.root)["n"], 1)

    def test_a_directory_where_the_line_should_be_reads_as_no_line(self):
        (self.root / "abc.json").mkdir()
        (self.root / "abc.turn").mkdir()
        with self.guarded():
            self.assertEqual((lines.read("abc", self.root), lines.current_turn("abc", self.root)), ({}, ""))

    def test_json_that_is_not_an_object_reads_as_no_line(self):
        for body in ("[]", '"text"', "5", "null", "true"):
            with self.subTest(body=body):
                (self.root / "abc.json").write_text(body, encoding="utf-8")
                self.assertEqual(lines.read("abc", self.root), {})

    def test_a_count_of_true_is_not_one_thing_left(self):
        (self.root / "abc.json").write_text(json.dumps({"did": "x", "ask": "y", "n": True, "at": 1}), encoding="utf-8")
        self.assertEqual(lines.read("abc", self.root)["n"], 0)


class FilesystemThatStopsAnswering(unittest.TestCase):
    """A link into a network mount, or a mount on the name itself, whose server has
    gone away. No flag keeps open, read or close from waiting on it, and the poll
    that reads the file holds the lock every poll takes. The read is bounded in
    time instead: a file that does not answer reads as no line, the wait is paid
    once, and a read still out is never asked a second time behind itself.

    The stand-in is `lines._plain_bytes` held on an event, for the files whose name
    starts with "stuck"; a real FUSE mount held the same way was run once by hand.
    """

    BUDGET = 1.0
    REAL_BUDGET = lines.READ_BUDGET       # taken at import, before any test patches it

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)
        def hung(*_):
            raise AssertionError("still reading after 20 s")
        self.addCleanup(signal.signal, signal.SIGALRM, signal.signal(signal.SIGALRM, hung))
        self.addCleanup(signal.alarm, 0)
        signal.alarm(20)
        self.release = threading.Event()
        self.addCleanup(self.settle)            # cleanups run last-added first: release, then settle
        self.addCleanup(self.release.set)       # nothing is left waiting on the folder when it goes
        self.calls = []
        real = lines._plain_bytes

        def plain(path, limit):
            name = Path(path).name
            self.calls.append(name)
            if name.startswith("stuck"):
                self.release.wait(30)
            elif name.startswith("slow"):
                time.sleep(0.1)
            elif name.startswith("boom"):
                raise MemoryError("invented")
            return real(path, limit)

        for sid in ("stuck", "fine", "slow", "boom"):       # written before anything is held
            (self.root / f"{sid}.turn").write_text("0123abcd", encoding="utf-8")
            lines.write(sid, did="Notes page built.", ask='Run "make test".', n=1, root=self.root)
        for patch in (mock.patch.object(lines, "_plain_bytes", plain),
                      mock.patch.object(lines, "READ_BUDGET", self.BUDGET)):
            patch.start()
            self.addCleanup(patch.stop)

    def settle(self):
        """Wait for the reads still out to finish (they end when `release` is set)."""
        end = time.monotonic() + 10
        while lines._reading and time.monotonic() < end:
            time.sleep(0.01)

    def timed(self, call, *args):
        t0 = time.monotonic()
        got = call(*args, self.root)
        return got, time.monotonic() - t0

    def test_a_line_that_does_not_answer_reads_as_no_line_after_the_budget(self):
        got, took = self.timed(lines.read, "stuck")
        self.assertEqual(got, {})
        self.assertGreaterEqual(took, self.BUDGET * 0.8, "a read was given up on before its budget")
        self.assertLess(took, 5)

    def test_a_turn_that_does_not_answer_reads_as_no_turn(self):
        got, took = self.timed(lines.current_turn, "stuck")
        self.assertEqual(got, "")
        self.assertLess(took, 5)
        self.assertEqual(lines.fresh("stuck", self.root), {})

    def test_the_wait_is_paid_once_and_no_second_read_piles_up_behind_it(self):
        before = threading.active_count()
        self.timed(lines.read, "stuck")
        for _ in range(6):
            got, took = self.timed(lines.read, "stuck")
            self.assertEqual(got, {})
            self.assertLess(took, self.BUDGET / 2, "the next poll waited again on a read still out")
        self.assertEqual(self.calls.count("stuck.json"), 1)
        self.assertLessEqual(threading.active_count() - before, 1)

    def test_a_session_that_answers_is_read_while_another_is_stuck(self):
        self.timed(lines.read, "stuck")
        got, took = self.timed(lines.read, "fine")
        self.assertEqual(got["ask"], 'Run "make test".')
        self.assertLess(took, self.BUDGET / 2)
        self.assertEqual(lines.current_turn("fine", self.root), "0123abcd")

    def test_a_read_that_comes_back_late_is_made_again_by_the_next_poll(self):
        self.assertEqual(lines.read("stuck", self.root), {})
        self.release.set()
        self.settle()
        self.assertEqual(lines._reading, {}, "a finished read stays on the list")
        self.assertEqual(lines.read("stuck", self.root)["n"], 1)
        self.assertEqual(self.calls.count("stuck.json"), 2)

    def test_two_readers_of_one_slow_file_share_the_one_read(self):
        out = []
        threads = [threading.Thread(target=lambda: out.append(lines.read("slow", self.root))) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual([got.get("n") for got in out], [1, 1])
        self.assertEqual(self.calls.count("slow.json"), 1)

    def test_a_read_that_raises_reads_as_no_line_and_says_nothing(self):
        heard = []
        with mock.patch.object(threading, "excepthook", heard.append):
            self.assertEqual(lines.read("boom", self.root), {})
            self.settle()
        self.assertEqual(heard, [])
        self.assertEqual(lines._reading, {})

    def test_no_thread_to_be_had_reads_as_no_line(self):
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("can't start new thread")):
            self.assertEqual(lines.read("fine", self.root), {})
            self.assertEqual(lines.current_turn("fine", self.root), "")
        self.assertEqual(lines._reading, {})
        self.assertEqual(lines.read("fine", self.root)["n"], 1)

    def test_the_budget_is_a_fraction_of_a_second(self):
        # Setup patched it for the other tests. A wait is paid once per file that
        # does not answer, inside a poll that is due every three seconds and gives
        # a provider two.
        self.assertTrue(0.05 <= self.REAL_BUDGET <= 1.0, self.REAL_BUDGET)

    def test_a_read_is_off_the_list_before_a_reader_is_told_it_is_done(self):
        # Otherwise a reader coming in at that moment is handed a read made before its
        # call, and a line written in between is not seen.
        seen = []

        class Done(threading.Event):
            def set(self):
                seen.append(dict(lines._reading))
                super().set()

        class Read(lines._Read):
            def __init__(self):
                super().__init__()
                self.done = Done()

        with mock.patch.object(lines, "_Read", Read):
            self.assertEqual(lines.read("fine", self.root)["n"], 1)
        self.assertEqual(seen, [{}])

    def test_a_fast_read_does_not_wait_for_its_budget(self):
        got, took = self.timed(lines.read, "fine")
        self.assertEqual(got["n"], 1)
        self.assertLess(took, self.BUDGET / 2)


class WhatIsOpened(unittest.TestCase):
    """The file judged is the file read, and it is the one the name led to."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_a_link_to_a_plain_file_is_followed(self):
        lines.write("real", did="x", ask="Run it.", n=1, root=self.root)
        (self.root / "abc.json").symlink_to(self.root / "real.json")
        self.assertEqual(lines.read("abc", self.root)["ask"], "Run it.")

    def test_the_name_is_not_opened_a_second_time_after_it_was_judged(self):
        # The name is swapped for a pipe between the open and the read: a read by
        # name would wait on the pipe, and a judgement of the name would refuse it.
        lines.write("abc", did="x", ask="Run it.", n=1, root=self.root)
        target = str(self.root / "abc.json")
        real_open = os.open

        def open_then_swap(path, *args, **kwargs):
            fd = real_open(path, *args, **kwargs)
            if str(path) == target:
                os.unlink(target)
                os.mkfifo(target)
            return fd

        with mock.patch.object(os, "open", open_then_swap):
            got = lines.read("abc", self.root)
        self.assertEqual(got.get("ask"), "Run it.")


class WhoWroteIt(unittest.TestCase):
    """A line read out of a transcript is not a line the session declared.

    Extraction can see a question. It cannot tell one that stops the session
    from one that offers to do more, so it must never reach the count.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_a_line_remembers_who_wrote_it(self):
        lines.write("a", did="x", n=1, by="session", root=self.root)
        lines.write("b", ask="y", n=1, by="read", root=self.root)
        self.assertEqual(lines.read("a", self.root)["by"], "session")
        self.assertEqual(lines.read("b", self.root)["by"], "read")

    def test_an_unknown_writer_is_not_trusted(self):
        (self.root / "c.json").write_text(
            json.dumps({"did": "x", "n": 3, "at": 1, "by": "whoever"}), encoding="utf-8")
        self.assertEqual(lines.read("c", self.root)["by"], "read")

    def test_an_empty_object_is_not_a_line(self):
        # `{}` parses. It says nothing, and treating it as a line suppresses
        # the fallback and makes the hook think the session answered.
        (self.root / "d.json").write_text("{}", encoding="utf-8")
        self.assertEqual(lines.read("d", self.root), {})

    def test_a_failed_write_says_so(self):
        # Fail-open is right. Reporting success for a write that did not
        # happen is not: `team-line` printed "line written" over nothing.
        self.assertIsNone(lines.write("e", did="x", root=self.root / "nope" / "deeper" / "\0bad"))

    def test_two_writers_do_not_share_a_temporary_file(self):
        seen = set()
        real = lines._tmp_for
        lines._tmp_for = lambda p: seen.add(str(real(p))) or real(p)
        try:
            lines.write("f", did="1", root=self.root)
            lines.write("f", did="2", root=self.root)
        finally:
            lines._tmp_for = real
        self.assertEqual(len(seen), 2, seen)
        self.assertEqual(lines.read("f", self.root)["did"], "2")


class Turns(unittest.TestCase):
    """Which turn a line belongs to.

    Freshness used to be a timestamp compared against the peer file's last
    status change, which only proved the line was written somewhere inside a
    working stretch. A session that went idle, busy and idle again between
    two polls kept a line from the stretch before. A turn has an identity;
    a moment does not.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_a_session_with_no_turn_yet_has_none(self):
        self.assertEqual(lines.current_turn("s1", self.root), "")

    def test_each_prompt_starts_a_turn_of_its_own(self):
        first = lines.begin_turn("s1", self.root)
        second = lines.begin_turn("s1", self.root)
        self.assertTrue(first and second)
        self.assertNotEqual(first, second)
        self.assertEqual(lines.current_turn("s1", self.root), second)

    def test_a_new_turn_forgets_the_last_line(self):
        # The prompt that restarted the session is the answer to what it
        # asked. This is the deterministic clear that the busy-poll
        # heuristic was standing in for.
        lines.begin_turn("s1", self.root)
        lines.write("s1", did="x", ask="y", n=1, root=self.root)
        lines.begin_turn("s1", self.root)
        self.assertEqual(lines.read("s1", self.root), {})

    def test_a_line_is_stamped_with_the_turn_it_was_written_in(self):
        turn = lines.begin_turn("s1", self.root)
        lines.write("s1", did="x", root=self.root)
        self.assertEqual(lines.read("s1", self.root)["turn"], turn)

    def test_only_this_turn_s_line_is_fresh(self):
        lines.begin_turn("s1", self.root)
        lines.write("s1", did="from the last turn", root=self.root)
        # A prompt whose clear never ran -- the hook was not installed, or
        # the write lost the race with it.
        lines._turn_file("s1", self.root).write_text("newturn", encoding="utf-8")
        self.assertEqual(lines.fresh("s1", self.root), {})
        self.assertNotEqual(lines.read("s1", self.root), {})

    def test_with_no_turns_tracked_at_all_a_line_still_shows(self):
        # Sessions older than the hook. Degrading to "any line is current"
        # is what the page did before, and it heals at their next prompt.
        lines.write("s1", did="x", root=self.root)
        self.assertEqual(lines.fresh("s1", self.root)["did"], "x")

    def test_turns_of_dead_sessions_are_forgotten(self):
        lines.begin_turn("gone", self.root)
        lines.forget({"alive"}, self.root)
        self.assertEqual(lines.current_turn("gone", self.root), "")
