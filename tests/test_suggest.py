import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet

SHELVES = ["/home/alice", "/home/alice/Projects",
           "/home/alice/Projects/clients"]
P = "/home/alice/Projects"


class Suggest(unittest.TestCase):
    def test_the_project_a_session_keeps_touching_is_the_guess(self):
        paths = [f"{P}/claude-team/fleet.py"] * 9 + [f"{P}/maple/x.md"] * 2
        self.assertEqual(fleet.suggest_project(paths, SHELVES), "claude-team")

    def test_it_says_nothing_when_no_project_leads(self):
        # Guessing wrong quietly is worse than not guessing: you would never
        # know to look.
        paths = [f"{P}/claude-team/a.py"] * 4 + [f"{P}/maple/b.md"] * 4
        self.assertIsNone(fleet.suggest_project(paths, SHELVES))

    def test_a_handful_of_mentions_is_not_evidence(self):
        self.assertIsNone(fleet.suggest_project([f"{P}/maple/b.md"] * 2, SHELVES))

    def test_config_and_scratch_paths_do_not_vote(self):
        # This is exactly what drowned the real answer for one session.
        paths = ["/home/alice/.claude/plans/a.md"] * 15 + [f"{P}/maple/b.md"] * 4
        self.assertEqual(fleet.suggest_project(paths, SHELVES), "maple")
