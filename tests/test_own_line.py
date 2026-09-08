"""The two lines a card shows, and which sessions count as wanting you.

`did` and `ask` come from the session itself, written inside the turn it was
already having. A line belongs to the turn it was written in: the prompt that
starts the next turn forgets it, and anything that survives that is
recognised by its turn rather than by its age.

When there is none -- a session running since before the hooks existed, or a
turn where the session did not write one -- the page falls back to reading
the ask out of the last thing it said. That fallback fills the words and
never raises the count: extraction can see a question, but it cannot tell one
that stops a session from one that offers to do more, and a tab that says (6)
has to mean six.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import lines


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)


class OwnLine(Base):
    def test_what_the_session_wrote_is_what_the_card_shows(self):
        lines.begin_turn("s1", self.root)
        lines.write("s1", did="Design settled, nothing written yet.", n=4,
                    root=self.root)
        got = fleet.own_line("s1", "idle", ("", 0), root=self.root)
        self.assertEqual(got["did"], "Design settled, nothing written yet.")
        self.assertEqual(got["n"], 4)
        self.assertTrue(got["blocked"])

    def test_a_session_that_wants_nothing_is_not_blocked(self):
        lines.write("s1", did="Tutto pushato su dev.", n=0, root=self.root)
        got = fleet.own_line("s1", "idle", ("", 0), root=self.root)
        self.assertEqual(got["did"], "Tutto pushato su dev.")
        self.assertFalse(got["blocked"])

    def test_with_no_line_the_ask_is_read_from_what_it_said(self):
        got = fleet.own_line("s1", "idle",
                             fleet.ask_from("What do you want to do in it?"),
                             root=self.root)
        self.assertEqual(got["ask"], "What do you want to do in it?")
        self.assertEqual(got["n"], 1)
        self.assertEqual(got["did"], "")

    def test_a_read_ask_does_not_raise_the_count(self):
        got = fleet.own_line("s1", "idle",
                             fleet.ask_from("Want me to update the README too?"),
                             root=self.root)
        self.assertEqual(got["n"], 1)
        self.assertFalse(got["blocked"])


class WhoIsBelieved(Base):
    """The hook writes what it read into the same file the session writes."""

    def test_a_line_the_session_declared_is_blocked(self):
        lines.write("s1", did="x", ask="Which first?", n=1, by="session",
                    root=self.root)
        self.assertTrue(fleet.own_line("s1", "idle", ("", 0), root=self.root)["blocked"])

    def test_a_line_read_out_of_the_transcript_is_not(self):
        lines.write("s1", ask="Want me to update the README too?", n=1,
                    by="read", root=self.root)
        got = fleet.own_line("s1", "idle", ("", 0), root=self.root)
        self.assertEqual(got["ask"], "Want me to update the README too?")
        self.assertFalse(got["blocked"])


class WhichTurn(Base):
    """Freshness is decided, not guessed."""

    def test_a_line_from_a_previous_turn_is_not_shown(self):
        # The case timestamps could not catch: a session that went idle,
        # busy and idle again between two polls kept the earlier line.
        lines.begin_turn("s1", self.root)
        lines.write("s1", did="from the turn before", ask="stale", n=1,
                    root=self.root)
        lines.begin_turn("s1", self.root)
        lines.write("s1", did="", ask="", n=0, root=self.root)
        got = fleet.own_line("s1", "idle", ("", 0), root=self.root)
        self.assertEqual(got["did"], "")
        self.assertFalse(got["blocked"])

    def test_a_line_written_while_still_working_is_this_turn_s(self):
        # The session writes its line as the last thing it does, before the
        # turn ends. It is busy at that moment and the line is current.
        lines.begin_turn("s1", self.root)
        lines.write("s1", did="Two files patched, tests green.", root=self.root)
        got = fleet.own_line("s1", "busy", ("", 0), root=self.root,
                             doing="Editing fleet.py")
        self.assertEqual(got["did"], "Two files patched, tests green.")
        self.assertEqual(got["doing"], "Editing fleet.py")


class WhileWorking(Base):
    """A busy row, mid-turn."""

    def test_between_calls_it_says_the_last_thing_it_said(self):
        got = fleet.own_line("s1", "busy", ("", 0), root=self.root,
                             said="Now I'll widen it to every unkeyed clip.")
        self.assertEqual(got["doing"], "Now I'll widen it to every unkeyed clip.")

    def test_a_call_in_flight_still_wins(self):
        got = fleet.own_line("s1", "busy", ("", 0), root=self.root,
                             said="Now I'll widen it.", doing="Editing fleet.py")
        self.assertEqual(got["doing"], "Editing fleet.py")

    def test_a_stopped_session_is_doing_nothing(self):
        got = fleet.own_line("s1", "idle", ("", 0), root=self.root,
                             said="All done.", doing="Editing fleet.py")
        self.assertEqual(got["doing"], "")
