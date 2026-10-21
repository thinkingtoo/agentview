"""The word next to a session's name while it works (ticket 21): what it is
doing, said in one word ("reviewing", "testing", "editing"), where the tile
had only the green of moving. A tile that is stuck or asks for the person says
that instead, and a session at rest has no word.

Through `roster()` with fake providers. The provider's facts are what a Claude
session hands over: `doing` (the call in flight, said out loud), `doingTool`
(that call's tool), `toolFor`, `shellCpu`, `quietFor`, `subQuiet`, `bgTasks`.
Names and texts are invented.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from test_columns import Base, session


def ago(minutes):
    return int(time.time() * 1000 - minutes * 60000)


def calling(tool, doing, **over):
    """Busy, with a call in flight that has CPU under it: moving."""
    return dict(status="busy", quietFor=0.5, toolFor=0.5, shellCpu=True,
                doing=doing, doingTool=tool, **over)


class Word(Base):
    def word(self, **over):
        return self.tile(session("a", **over))["activity"]

    def test_a_command_that_runs_a_review_is_reviewing(self):
        self.assertEqual(self.word(**calling("Bash", "Run the Codex review on the branch")), "reviewing")
        self.assertEqual(self.word(**calling("Skill", "Running /code-review")), "reviewing")

    def test_a_command_that_runs_the_tests_is_testing(self):
        for doing in ("Run the unit tests", "Running pytest tests/test_maple.py", "Run the suite on t-compute"):
            with self.subTest(doing=doing):
                self.assertEqual(self.word(**calling("Bash", doing)), "testing")

    def test_other_commands_say_what_kind_of_work_or_running(self):
        for doing, word in (("Build the docs site", "building"), ("Push the branch to origin", "pushing"),
                            ("Merge origin/dev into the branch", "merging"),
                            ("Install the package dependencies", "installing"),
                            ("Show working tree status", "running")):
            with self.subTest(doing=doing):
                self.assertEqual(self.word(**calling("Bash", doing)), word)

    def test_the_tool_says_it_for_files_and_the_web(self):
        for tool, doing, word in (("Edit", "Editing review-notes.md", "editing"),
                                  ("Write", "Writing test_maple.py", "editing"),
                                  ("Read", "Reading fleet.py", "reading"),
                                  ("Grep", "Searching for build", "reading"),
                                  ("WebFetch", "Fetching docs.example.com", "researching"),
                                  ("Agent", "Running Opus bug hunt", "delegating")):
            with self.subTest(tool=tool):
                self.assertEqual(self.word(**calling(tool, doing)), word)

    def test_a_session_writing_with_no_call_in_flight_is_thinking(self):
        self.assertEqual(self.word(status="busy", quietFor=0.1), "thinking")

    def test_a_session_whose_subagent_writes_is_delegating(self):
        self.assertEqual(self.word(status="busy", quietFor=12.0, subQuiet=0.2), "delegating")

    def test_a_folded_codex_review_run_is_reviewing(self):
        self.assertEqual(self.word(status="idle", updatedAt=ago(30), quietFor=29.0,
                                   bgTasks=[{"label": "codex review", "since": 2.0, "run": True}]),
                         "reviewing")

    def test_an_idle_session_waiting_on_its_own_job_is_waiting(self):
        self.assertEqual(self.word(status="idle", updatedAt=ago(30),
                                   bgTasks=[{"label": "Watch for the port forward", "since": 30.0}]),
                         "waiting")

    def test_a_session_at_rest_or_stuck_has_no_word(self):
        self.assertEqual(self.word(status="idle", updatedAt=ago(50)), "")
        self.assertEqual(self.word(status="busy", quietFor=40.0), "")       # Hung says it
        self.assertEqual(self.word(status="waiting", waitingFor="input needed", updatedAt=ago(2),
                                   asking={"kind": "question", "questions": []}), "")


if __name__ == "__main__":
    unittest.main()
