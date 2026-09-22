"""One poll across providers: who answered, who failed, and what the click does.

A single provider must not be able to take the page down, and a provider
that misses a round must not make everything you had read come back as
`ready` when it returns.
"""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import seen
from providers.base import Provider
from test_providers import Fake, minimal


class Broken(Provider):
    name = "broken"
    capabilities = frozenset()

    def live(self):
        raise RuntimeError("sqlite is locked")


class Slow(Provider):
    name = "slow"
    capabilities = frozenset()
    gate = threading.Event()

    def live(self):
        self.gate.wait(10)
        return []


class Round(unittest.TestCase):
    def test_a_provider_that_raises_does_not_take_the_others_down(self):
        rows = fleet.sessions(providers=[Broken(), Fake([minimal()])])
        self.assertEqual([r["key"] for r in rows], ["fake:s1"])
        self.assertEqual(fleet.ROUND["answered"], {"fake"})
        self.assertIn("sqlite is locked", fleet.ROUND["failed"]["broken"])

    def test_a_provider_that_stalls_is_reported_within_the_budget(self):
        slow = Slow()
        fleet.LIVE_BUDGET, was = 0.2, fleet.LIVE_BUDGET
        try:
            t = time.perf_counter()
            rows = fleet.sessions(providers=[slow, Fake([minimal()])])
            self.assertLess(time.perf_counter() - t, 1.5)
        finally:
            fleet.LIVE_BUDGET = was
            slow.gate.set()
        self.assertEqual([r["key"] for r in rows], ["fake:s1"])
        self.assertIn("slow", fleet.ROUND["failed"])
        self.assertEqual(fleet.ROUND["answered"], {"fake"})

    def test_a_provider_that_returns_nonsense_is_a_failed_provider(self):
        class Odd(Provider):
            name = "odd"
            def live(self):
                return {"not": "a list"}
        fleet.sessions(providers=[Odd()])
        self.assertIn("odd", fleet.ROUND["failed"])


class Forgetting(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "seen.json"
        seen.mark("claude:a", 100, self.path)
        seen.mark("codex:b", 100, self.path)

    def test_a_failed_providers_marks_survive_the_round(self):
        # Codex missed this poll: none of its sessions are live, and none of
        # its marks may go.
        seen.forget({"claude:a"}, self.path, answered={"claude"})
        self.assertEqual(seen.load(self.path), {"claude:a": 100, "codex:b": 100})

    def test_an_answering_providers_dead_sessions_are_forgotten(self):
        seen.forget({"claude:a"}, self.path, answered={"claude", "codex"})
        self.assertEqual(seen.load(self.path), {"claude:a": 100})


class Migration(unittest.TestCase):
    def test_bare_ids_become_claude_keys_once(self):
        path = Path(tempfile.mkdtemp()) / "seen.json"
        seen.mark("abc", 100, path)
        seen.mark("codex:def", 200, path)
        seen.migrate("claude", path)
        self.assertEqual(seen.load(path), {"claude:abc": 100, "codex:def": 200})
        before = path.stat().st_mtime_ns
        seen.migrate("claude", path)                    # idempotent, no rewrite
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_config_assign_and_lines_are_migrated_too(self):
        cfg = Path(tempfile.mkdtemp()) / "config.json"
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
        path = Path(tempfile.mkdtemp()) / "seen.json"
        seen.store, was = (lambda: path), seen.store
        try:
            fleet.look("fake:s1")
        finally:
            seen.store = was
        self.assertEqual(seen.load(path), {"fake:s1": 777})

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
