"""Whether a session has a review agent running (ticket boss-track/20): a live subagent whose
meta file says it is not finished, whose transcript wrote in the last five minutes, and whose
description is a review's. The descriptions are invented in the shape of real ones.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import claude


class IsReview(unittest.TestCase):
    def test_what_a_review_agent_is_called(self):
        for text in ("Opus bug hunt on PR 39", "Standards review of ticket 03", "Delta check PR 136",
                     "Narrow Opus re-run on PR 125", "Codex review 2 (Opus) of ticket 24", "Opus re-review of fixes",
                     "Revue Standards du ticket 02", "Spec axis of PR 798", "Opus round 2 on PR 863", "Opus read of PR 149",
                     "Opus check of clean() fix", "Write a code review of PR 3", "Draft review summary",
                     "Re-review after port of fix", "Review the plan and write the migration"):
            with self.subTest(text):
                self.assertTrue(claude.is_review(text))

    def test_what_is_not(self):
        for text in ("Crawl lent et sitemaps", "Triage batch 3 tickets", "Fetch vision API pricing pages",
                     "Opus fallback implementation of the importer", "Codex parity for the reader",
                     "Build the import file for the batch", "Write sheaf public tickets from triage", "",
                     "Rerun failing tests", "Delta sync of shelves", "Re-read config and update docs",
                     "Reviewer onboarding notes", "Opus: fix the flaky test", "Codex fix round 2"):
            with self.subTest(text):
                self.assertFalse(claude.is_review(text))


class Reviewing(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.session = self.dir / "s1.jsonl"
        self.session.write_text("{}\n")
        self.now = time.time()

    def agent(self, name, description, finished=None, age_minutes=1.0, meta=True):
        folder = self.session.with_suffix("") / "subagents"
        folder.mkdir(parents=True, exist_ok=True)
        run = folder / f"agent-{name}.jsonl"
        run.write_text("{}\n")
        stamp = self.now - age_minutes * 60
        os.utime(run, (stamp, stamp))
        if meta:
            body = {"description": description, "requestShape": "background"}
            if finished is not None:
                body["finished"] = finished
            (folder / f"agent-{name}.meta.json").write_text(json.dumps(body))

    def reviewing(self):
        return claude._reviewing(claude._subagent_files(self.session, self.now), self.now)

    def test_a_live_review_agent_counts(self):
        self.agent("a", "Opus bug hunt on PR 39")
        self.assertTrue(self.reviewing())

    def test_a_finished_one_or_a_stale_one_does_not(self):
        self.agent("a", "Opus bug hunt on PR 39", finished=True)
        self.agent("b", "Opus bug hunt on PR 40", age_minutes=2971)
        self.assertFalse(self.reviewing())

    def test_a_live_agent_that_is_no_review_does_not(self):
        self.agent("a", "Crawl lent et sitemaps")
        self.assertFalse(self.reviewing())

    def test_one_review_among_other_live_agents_counts(self):
        self.agent("a", "Triage batch 3 tickets")
        self.agent("b", "Delta check PR 136")
        self.assertTrue(self.reviewing())

    def test_no_subagents_a_missing_meta_and_a_broken_one_do_not(self):
        self.assertFalse(self.reviewing())
        self.agent("a", "Opus bug hunt", meta=False)
        folder = self.session.with_suffix("") / "subagents"
        self.agent("b", "x")
        (folder / "agent-b.meta.json").write_text("{not json")
        (folder / "agent-c.jsonl").write_text("{}\n")
        (folder / "agent-c.meta.json").write_text(json.dumps(["Opus bug hunt"]))
        self.assertFalse(self.reviewing())

    def test_an_agent_of_a_workflow_run_is_looked_at_too(self):
        run = self.session.with_suffix("") / "subagents" / "workflows" / "r1"
        run.mkdir(parents=True)
        (run / "agent-w.jsonl").write_text("{}\n")
        (run / "agent-w.meta.json").write_text(json.dumps({"description": "Opus bug hunt on PR 39"}))
        self.assertTrue(self.reviewing())

    def test_only_the_freshest_dozen_are_opened(self):
        for i in range(claude.REVIEW_MAX):
            self.agent(f"n{i}", "Triage batch of tickets", age_minutes=0.5)
        self.agent("z", "Opus bug hunt on PR 39", age_minutes=9)
        self.assertFalse(self.reviewing())
        self.agent("y", "Opus bug hunt on PR 40", age_minutes=0.1)
        self.assertTrue(self.reviewing())

    def test_the_session_view_says_it(self):
        record = {"type": "assistant", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(self.now)),
                  "message": {"content": [{"type": "text", "text": "x"}]}}
        self.session.write_text(json.dumps(record) + "\n")
        self.assertFalse(claude.scan_session(self.session, self.now)["reviewing"])
        self.agent("a", "Opus bug hunt on PR 39")
        self.assertTrue(claude.scan_session(self.session, self.now)["reviewing"])

    def test_a_description_that_is_no_text_does_not_crash_it(self):
        self.agent("a", None)
        self.assertFalse(self.reviewing())


if __name__ == "__main__":
    unittest.main()
