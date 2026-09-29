"""The hook that starts a turn.

It runs when you press enter. Two jobs: forget the line from the turn before
-- your prompt is the answer to whatever it asked -- and tell the session, in
one short paragraph, to say where it leaves things before the turn ends.

Nothing here blocks and nothing here is an error. That is the whole point:
a Stop hook that blocks is rendered to you as `Stop hook error:` in every
session, at every stop, and no setting changes that.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "hooks"))
import lines
import turn_line


class Starting(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_a_prompt_starts_a_turn(self):
        turn_line.begin({"session_id": "s1", "prompt": "do the thing"}, root=self.root)
        self.assertTrue(lines.current_turn("s1", self.root))

    def test_a_prompt_forgets_the_line_before_it(self):
        lines.write("s1", did="x", ask="Which first?", n=1, root=self.root)
        turn_line.begin({"session_id": "s1", "prompt": "the second one"}, root=self.root)
        self.assertEqual(lines.read("s1", self.root), {})

    def test_the_session_is_told_what_to_run(self):
        got = turn_line.begin({"session_id": "s1", "prompt": "go"}, root=self.root)
        said = got["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(got["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("team-line", said)
        self.assertIn("s1", said)
        self.assertIn("--n", said)

    def test_the_instruction_stays_short(self):
        # It is injected on every turn of every session on this machine, so
        # its size is what every turn pays. Measured the way it is injected:
        # with a real session id (36 characters), and a writer path of fixed
        # length so the number does not depend on where the checkout lives.
        # With "s1" and whatever path the checkout had, this passed at 697 in
        # the main checkout and failed at 703 in any worktree, while the real
        # injection was 731. That size was approved on 2026-09-25 (n counts
        # what is left for the user); the ceiling leaves room for one more
        # sentence and no more.
        sid = "00000000-0000-4000-8000-000000000000"
        with mock.patch.object(turn_line, "WRITER", Path("/home/alice/Projects/agentview/hooks/team-line")):
            said = turn_line.begin({"session_id": sid, "prompt": "go"},
                                   root=self.root)["hookSpecificOutput"]["additionalContext"]
        self.assertLess(len(said), 750, len(said))
        self.assertGreater(len(said), 700, "the budget was 700 before 2026-09-25; if the text got "
                                          "shorter, tighten the ceiling above to match")

    def test_the_size_does_not_depend_on_where_the_checkout_lives(self):
        sizes = set()
        for where in ("/a/hooks/team-line", "/home/alice/Projects/agentview-wt-06/hooks/team-line"):
            with mock.patch.object(turn_line, "WRITER", Path(where)):
                said = turn_line.begin({"session_id": "s1", "prompt": "go"},
                                       root=self.root)["hookSpecificOutput"]["additionalContext"]
            sizes.add(len(said) - len(where))
        self.assertEqual(len(sizes), 1)

    def test_a_payload_with_no_session_does_nothing(self):
        self.assertEqual(turn_line.begin({"prompt": "go"}, root=self.root), {})

    def test_it_never_blocks(self):
        got = turn_line.begin({"session_id": "s1", "prompt": "go"}, root=self.root)
        self.assertNotIn("decision", got)
        self.assertNotIn("continue", got)
