"""The Stop hook that makes a session say where it left things.

It gets one chance per stop. Claude Code sets `stop_hook_active` on the
second call so a hook cannot hold a session open in a loop, and it discards
the block outright on turns that end without re-invoking the model -- so
this must always leave something behind, and must never be the reason a
session fails to stop.
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
        text = ("\n".join([
            '{"type":"assistant","message":{"content":[{"type":"text","text":"first"}]}}',
            '{"type":"user","message":{"content":"a prompt"}}',
            '{"type":"assistant","message":{"content":[{"type":"text","text":"last"}]}}',
        ]))
        self.assertEqual(stop_line.last_said(text), "last")

    def test_a_subagent_never_speaks_for_the_session(self):
        text = ("\n".join([
            '{"type":"assistant","message":{"content":[{"type":"text","text":"mine"}]}}',
            '{"type":"assistant","isSidechain":true,'
            '"message":{"content":[{"type":"text","text":"a subagent"}]}}',
        ]))
        self.assertEqual(stop_line.last_said(text), "mine")

    def test_a_half_line_at_the_start_of_a_tail_is_skipped(self):
        # The hook reads the end of the file, so the first line is usually cut.
        text = ('pe":"text","text":"cut in half"}]}}\n'
                '{"type":"assistant","message":{"content":[{"type":"text","text":"whole"}]}}')
        self.assertEqual(stop_line.last_said(text), "whole")


class Deciding(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_a_session_ending_on_a_question_is_left_alone(self):
        # Its ask is already readable. Paying a turn to rewrite a line that
        # is right is the wrong half of the cost.
        got = stop_line.decide({"session_id": "s1"},
                               "What do you want to do in it?", root=self.root)
        self.assertEqual(got["action"], "write")
        self.assertEqual(got["n"], 1)
        self.assertEqual(lines.read("s1", self.root)["ask"],
                         "What do you want to do in it?")

    def test_a_session_ending_on_nothing_readable_is_asked(self):
        # Janusz's shape: an ask with no question mark in it.
        got = stop_line.decide(
            {"session_id": "s1"},
            "Dis-moi : presse-papiers, brouillon Gmail, ou tu le copies toi-même.",
            root=self.root)
        self.assertEqual(got["action"], "block")
        self.assertIn("s1", got["reason"])

    def test_the_second_call_never_blocks_again(self):
        # `stop_hook_active` is Claude Code's guard against a hook holding a
        # session open forever. Honour it or the session never stops.
        got = stop_line.decide({"session_id": "s1", "stop_hook_active": True},
                               "Nothing to ask here.", root=self.root)
        self.assertEqual(got["action"], "pass")

    def test_a_line_the_session_wrote_is_not_overwritten(self):
        lines.write("s1", did="Fatto tutto.", ask="", n=0, root=self.root)
        got = stop_line.decide({"session_id": "s1", "stop_hook_active": True},
                               "Anything at all?", root=self.root)
        self.assertEqual(got["action"], "pass")
        self.assertEqual(lines.read("s1", self.root)["did"], "Fatto tutto.")

    def test_a_payload_with_no_session_does_nothing(self):
        self.assertEqual(stop_line.decide({}, "x?", root=self.root)["action"], "pass")

    def test_the_instruction_names_the_command_to_run(self):
        got = stop_line.decide({"session_id": "s1"}, "Done.", root=self.root)
        self.assertIn("--did", got["reason"])
        self.assertIn("--n", got["reason"])


class TheWriter(unittest.TestCase):
    """The command the session is told to run. If this is wrong every line
    is lost in silence, so it gets a test of its own."""

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
