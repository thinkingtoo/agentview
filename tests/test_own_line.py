"""The two lines a card shows, and which sessions count as wanting you.

`did` and `ask` come from the session itself, written by a Stop hook as it
finishes. When there is none -- a session that was already running before
the hook existed, or a stop where Claude Code discarded the block -- the
page falls back to reading the ask out of the last thing it said.

The fallback fills the words and does not raise the count. Extraction can
see a question; it cannot tell one that stops the session from one that
offers to do more. A tab that says (6) has to mean six.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import lines


class OwnLine(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_what_the_session_wrote_is_what_the_card_shows(self):
        lines.write("s1", did="Design settled, nothing written yet.",
                    ask="", n=4, root=self.root)
        got = fleet.own_line("s1", "idle", asked=("", 0), root=self.root)
        self.assertEqual(got["did"], "Design settled, nothing written yet.")
        self.assertEqual(got["n"], 4)
        self.assertTrue(got["blocked"])

    def test_a_session_that_wants_nothing_is_not_blocked(self):
        lines.write("s1", did="Tutto pushato su dev.", ask="", n=0, root=self.root)
        got = fleet.own_line("s1", "idle", asked=("", 0), root=self.root)
        self.assertEqual(got["did"], "Tutto pushato su dev.")
        self.assertFalse(got["blocked"])

    def test_with_no_line_the_ask_is_read_from_what_it_said(self):
        got = fleet.own_line("s1", "idle",
                             asked=fleet.ask_from("What do you want to do in it?"), root=self.root)
        self.assertEqual(got["ask"], "What do you want to do in it?")
        self.assertEqual(got["n"], 1)
        self.assertEqual(got["did"], "")

    def test_a_read_ask_does_not_raise_the_count(self):
        # Extraction sees a question. Whether it stops the session is a thing
        # only the session knows, and it says so by writing a line.
        got = fleet.own_line("s1", "idle",
                             asked=fleet.ask_from("Want me to update the README too?"), root=self.root)
        self.assertEqual(got["n"], 1)
        self.assertFalse(got["blocked"])

    def test_a_session_back_at_work_shows_neither(self):
        lines.write("s1", did="x", ask="y", n=1, root=self.root)
        got = fleet.own_line("s1", "busy", asked=("", 0), root=self.root)
        self.assertEqual((got["did"], got["ask"], got["n"]), ("", "", 0))
        self.assertFalse(got["blocked"])

    def test_going_back_to_work_forgets_the_line(self):
        # The prompt that restarted it is the answer to what it asked. A need
        # kept past that point makes the page lie at the next stop.
        lines.write("s1", did="x", ask="y", n=1, root=self.root)
        fleet.own_line("s1", "busy", asked=("", 0), root=self.root)
        self.assertEqual(lines.read("s1", self.root), {})


class TheHooksOwnTurn(unittest.TestCase):
    """A line written while the session is busy is the hook's, not a stale one.

    Blocking a stop puts the session back to work to write its line, so for a
    few seconds it is busy *and* holding the freshest line there is. Dropping
    on status alone deleted both lines the fleet wrote the first time this
    ran.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_a_line_written_after_it_went_busy_is_kept(self):
        lines.write("s1", did="Fatto.", ask="", n=0, root=self.root, at=2000)
        got = fleet.own_line("s1", "busy", asked=("", 0), root=self.root,
                             since=1000_000)          # went busy at t=1000s
        self.assertEqual(got["did"], "Fatto.")

    def test_a_line_from_the_last_stop_is_dropped(self):
        # The prompt that restarted it is the answer to what it asked.
        lines.write("s1", did="x", ask="y", n=1, root=self.root, at=500)
        got = fleet.own_line("s1", "busy", asked=("", 0), root=self.root,
                             since=1000_000)
        self.assertEqual(got["n"], 0)
        self.assertEqual(lines.read("s1", self.root), {})

    def test_with_no_moment_to_compare_a_busy_session_keeps_nothing(self):
        lines.write("s1", did="x", ask="", n=0, root=self.root, at=500)
        self.assertEqual(fleet.own_line("s1", "busy", asked=("", 0),
                                        root=self.root)["did"], "")


class WhileWorking(unittest.TestCase):
    """A busy row, mid-turn, with no call in flight."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_between_calls_it_says_the_last_thing_it_said(self):
        # Live on the page: a session generating text, no tool outstanding,
        # printed the user's own prompt back at them. Its own running
        # commentary is the better answer to "where is this now".
        got = fleet.own_line("s1", "busy", asked=("", 0), root=self.root,
                             said="Now I'll widen it to every unkeyed clip.")
        self.assertEqual(got["doing"], "Now I'll widen it to every unkeyed clip.")

    def test_a_call_in_flight_still_wins(self):
        got = fleet.own_line("s1", "busy", asked=("", 0), root=self.root,
                             said="Now I'll widen it.", doing="Editing fleet.py")
        self.assertEqual(got["doing"], "Editing fleet.py")

    def test_a_stopped_session_is_doing_nothing(self):
        got = fleet.own_line("s1", "idle", asked=("", 0), root=self.root,
                             said="All done.", doing="Editing fleet.py")
        self.assertEqual(got["doing"], "")
