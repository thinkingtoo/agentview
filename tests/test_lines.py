"""The per-session line a session writes about itself when it stops.

Two fields and a count: where the work stands (`did`), and the one thing it
is blocked on (`ask`), or how many things there are (`n`). The file is
written by a Stop hook running inside the session, and read by the page.
"""
import json
import sys
import unittest
from pathlib import Path
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
