"""The Stop hook, after it stopped blocking.

It used to block: return `decision: block` so Claude Code re-invoked the
model for one extra turn in which the session wrote its line. That worked,
and it cost an extra turn per stop and printed the instruction into every
session's terminal under the heading `Stop hook error:` -- which is Claude
Code's own rendering of any Stop-hook block, with no setting to change it.

Now the session is asked at the start of the turn instead, and this hook only
checks. It writes an unverified fallback when the session did not, records
the miss so the misses are countable, and never interrupts anything.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "hooks"))
import lines
import stop_line


class LastSaid(unittest.TestCase):
    def test_the_newest_thing_the_session_said(self):
        text = "\n".join([
            '{"type":"assistant","message":{"content":[{"type":"text","text":"first"}]}}',
            '{"type":"user","message":{"content":"a prompt"}}',
            '{"type":"assistant","message":{"content":[{"type":"text","text":"last"}]}}',
        ])
        self.assertEqual(stop_line.last_said(text), "last")

    def test_a_subagent_never_speaks_for_the_session(self):
        text = "\n".join([
            '{"type":"assistant","message":{"content":[{"type":"text","text":"mine"}]}}',
            '{"type":"assistant","isSidechain":true,'
            '"message":{"content":[{"type":"text","text":"a subagent"}]}}',
        ])
        self.assertEqual(stop_line.last_said(text), "mine")

    def test_a_half_line_at_the_start_of_a_tail_is_skipped(self):
        text = ('pe":"text","text":"cut in half"}]}}\n'
                '{"type":"assistant","message":{"content":[{"type":"text","text":"whole"}]}}')
        self.assertEqual(stop_line.last_said(text), "whole")


class Checking(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_nothing_ever_blocks(self):
        # The one property this file exists to hold. A block is rendered to
        # the user as an error, in every session, at every stop.
        for said in ("", "Done.", "What do you want to do in it?",
                     "Dis-moi : A, B, ou C."):
            for payload in ({"session_id": "s1"},
                            {"session_id": "s1", "stop_hook_active": True},
                            {}):
                got = stop_line.decide(payload, said, root=self.root)
                self.assertNotIn("decision", got)
                self.assertNotEqual(got.get("action"), "block")

    def test_a_session_that_wrote_its_own_line_is_left_alone(self):
        lines.begin_turn("s1", self.root)
        lines.write("s1", did="Fatto tutto.", root=self.root)
        got = stop_line.decide({"session_id": "s1"}, "Anything at all?", root=self.root)
        self.assertEqual(got["action"], "pass")
        self.assertEqual(lines.read("s1", self.root)["did"], "Fatto tutto.")

    def test_a_line_from_a_previous_turn_does_not_count_as_written(self):
        lines.begin_turn("s1", self.root)
        lines.write("s1", did="stale", root=self.root)
        lines.begin_turn("s1", self.root)
        got = stop_line.decide({"session_id": "s1"},
                               "What do you want to do in it?", root=self.root)
        self.assertEqual(got["action"], "write")

    def test_a_missing_line_falls_back_to_what_it_said(self):
        got = stop_line.decide({"session_id": "s1"},
                               "What do you want to do in it?", root=self.root)
        self.assertEqual(got["action"], "write")
        wrote = lines.read("s1", self.root)
        self.assertEqual(wrote["ask"], "What do you want to do in it?")
        # Unverified, and it says so: a read ask never reaches the count.
        self.assertEqual(wrote["by"], "read")

    def test_a_miss_with_nothing_readable_is_recorded(self):
        # Janusz's shape: an ask with no question mark in it. Nothing to
        # show, and worth counting -- the misses are how you know whether
        # the instruction is being followed.
        got = stop_line.decide(
            {"session_id": "s1"},
            "Dis-moi : presse-papiers, brouillon Gmail, ou tu le copies toi-même.",
            root=self.root)
        self.assertEqual(got["action"], "miss")

    def test_a_payload_with_no_session_does_nothing(self):
        self.assertEqual(stop_line.decide({}, "x?", root=self.root)["action"], "pass")


class TheWriter(unittest.TestCase):
    """The command the session is told to run."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.env = dict(os.environ)
        os.environ["XDG_STATE_HOME"] = self.dir.name
        self.addCleanup(lambda: os.environ.clear() or os.environ.update(self.env))

    def run_writer(self, *argv):
        import subprocess
        return subprocess.run(
            [sys.executable, str(HERE.parent / "hooks" / "team-line"), *argv],
            capture_output=True, text=True)

    def test_a_session_writes_its_own_two_fields(self):
        got = self.run_writer("s9", "--did", "Design settled.", "--n", "4")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(lines.read("s9")["did"], "Design settled.")
        self.assertEqual(lines.read("s9")["n"], 4)

    def test_words_are_kept_only_when_there_is_one_thing_to_say(self):
        self.run_writer("s9", "--did", "x", "--n", "4", "--ask", "the first one")
        self.assertEqual(lines.read("s9")["ask"], "")
        self.run_writer("s8", "--did", "x", "--n", "1", "--ask", "the only one")
        self.assertEqual(lines.read("s8")["ask"], "the only one")

    def test_it_carries_the_turn_it_was_run_in(self):
        turn = lines.begin_turn("s7")
        self.run_writer("s7", "--did", "x", "--n", "0")
        self.assertEqual(lines.read("s7")["turn"], turn)

    def test_a_write_that_did_not_land_is_reported_as_a_failure(self):
        got = self.run_writer("../../escape", "--did", "x", "--n", "0")
        self.assertNotEqual(got.returncode, 0)
