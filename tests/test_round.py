"""The key migration, and what the click does.

The round itself (who answered, who failed, what is forgotten and swept) is
`tests/test_poll.py`.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import marks
from test_providers import Fake, minimal


class Migration(unittest.TestCase):
    def test_config_assign_and_lines_are_migrated_too(self):
        cfg = Path(tempfile.mkdtemp()) / "config.json"
        self.addCleanup(shutil.rmtree, cfg.parent, True)
        cfg.write_text(json.dumps({"assign": {"abc": "maple", "codex:x": "pmd"},
                                   "lines": {"abc": "my words"}, "pinned": ["maple"]}))
        fleet.CONFIG, was = cfg, fleet.CONFIG
        try:
            self.assertEqual(fleet.migrate_keys(), ["assign", "lines"])
            got = json.loads(cfg.read_text())
            self.assertEqual(got["assign"], {"claude:abc": "maple", "codex:x": "pmd"})
            self.assertEqual(got["lines"], {"claude:abc": "my words"})
            self.assertEqual(got["pinned"], ["maple"])   # project keys are untouched
            self.assertEqual(fleet.migrate_keys(), [])
        finally:
            fleet.CONFIG = was


class Click(unittest.TestCase):
    """The browser sends `provider:id`; the server resolves it."""

    def setUp(self):
        self.fake = Fake([minimal(pid=4242, updatedAt=777)])
        fleet._providers, self.was = (lambda: [self.fake]), fleet._providers
        self.addCleanup(setattr, fleet, "_providers", self.was)

    def test_a_key_resolves_to_its_provider_and_live_session(self):
        p, s = fleet.find("fake:s1")
        self.assertIs(p, self.fake)
        self.assertEqual(s["pid"], 4242)

    def test_an_unknown_provider_or_session_is_none(self):
        self.assertIsNone(fleet.find("nope:s1"))
        self.assertIsNone(fleet.find("fake:s2"))
        self.assertIsNone(fleet.find("just-a-pid"))
        self.assertIsNone(fleet.find(4242))

    def test_looking_marks_the_session_read_whatever_happens_next(self):
        path = Path(tempfile.mkdtemp()) / "marks.json"
        self.addCleanup(shutil.rmtree, path.parent, True)
        marks.store, was = (lambda: path), marks.store
        try:
            fleet.look("fake:s1")
        finally:
            marks.store = was
        self.assertEqual(marks.load(path), {"fake:s1": {"seen": 777}})

    def test_a_provider_without_jump_says_so_instead_of_guessing(self):
        self.fake.capabilities = {"status"}
        p, s = fleet.find("fake:s1")
        done = fleet.jump_to(p, s)
        self.assertFalse(done["ok"])
        self.assertIn("fake", done["reason"])

    def test_a_providers_own_jump_wins_over_the_pid(self):
        self.fake.jump = lambda s: {"ok": True, "reason": "", "ran": ["custom"]}
        p, s = fleet.find("fake:s1")
        self.assertEqual(fleet.jump_to(p, s)["ran"], ["custom"])

    def test_without_a_pid_there_is_nothing_to_jump_to(self):
        self.fake._sessions = [minimal()]
        p, s = fleet.find("fake:s1")
        done = fleet.jump_to(p, s)
        self.assertFalse(done["ok"])
        self.assertIn("pid", done["reason"])


if __name__ == "__main__":
    unittest.main()
