"""The provider contract, seen from the core.

A provider hands over facts about its live sessions -- five required fields,
the rest optional -- and the core turns them into the row the page draws.
Nothing a conforming provider sends, or leaves out, may make `roster()` throw.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
from providers.base import Provider

# Every field index.html reads off a member, as of 2026-09-22 -- the page
# indexes them without guards, so a missing one is a blank row or a crash.
PAGE_FIELDS = {
    "key", "provider", "id", "flag", "status", "name", "reportsTo", "title",
    "suggestion", "routine", "prompt", "pid", "n", "boss", "ask", "waitingFor",
    "updatedAt", "tmux", "team", "startedAt", "said", "quietFor", "overridden",
    "kind", "doing", "did", "cwd", "canJump", "blocked", "toolFor", "branch",
    "bg", "assigned", "project", "extras",
}


class Fake(Provider):
    name = "fake"
    capabilities = {"jump", "branch", "waiting", "name", "status"}

    def __init__(self, sessions=(), caps=None):
        self._sessions = list(sessions)
        if caps is not None:
            self.capabilities = set(caps)

    def live(self):
        return [dict(s) for s in self._sessions]


def minimal(**over):
    base = {"id": "s1", "cwd": "/home/alice/Projects/maple", "status": "idle",
            "updatedAt": 1790000000000}
    base.update(over)
    return base


class Normalization(unittest.TestCase):
    def rows(self, *sessions, caps=None):
        return fleet.sessions(providers=[Fake(sessions, caps)])

    def test_a_minimal_session_carries_every_field_the_page_reads(self):
        row = self.rows(minimal())[0]
        # `reportsTo` and `overridden` are laid on by `roster()`, below.
        self.assertEqual(PAGE_FIELDS - set(row), {"reportsTo", "overridden"})
        self.assertEqual(row["key"], "fake:s1")
        self.assertEqual(row["provider"], "fake")
        self.assertEqual(row["project"], "maple")

    def test_and_roster_does_not_explode_on_it(self):
        rows = self.rows(minimal())
        real = fleet.sessions
        fleet.sessions = lambda providers=None: rows
        try:
            blocks = fleet.roster()
        finally:
            fleet.sessions = real
        self.assertEqual(blocks[0]["members"][0]["key"], "fake:s1")
        self.assertIn("overridden", blocks[0]["members"][0])
        self.assertIn("reportsTo", blocks[0]["members"][0])

    def test_defaults_are_the_empty_kind_of_each_field(self):
        row = self.rows(minimal())[0]
        self.assertEqual(row["name"], "")
        self.assertEqual(row["branch"], "")
        self.assertEqual(row["team"], [])
        self.assertEqual(row["extras"], {})
        self.assertIsNone(row["pid"])
        self.assertIsNone(row["quietFor"])
        self.assertIsNone(row["toolFor"])
        self.assertFalse(row["canJump"])
        self.assertFalse(row["blocked"])
        self.assertEqual(row["n"], 0)

    def test_the_provider_name_is_stamped_by_the_core(self):
        # A provider that lies about its own name would break the key.
        row = self.rows(minimal(provider="claude"))[0]
        self.assertEqual(row["provider"], "fake")
        self.assertEqual(row["key"], "fake:s1")

    def test_a_session_without_an_id_is_dropped_not_crashed_on(self):
        rows = self.rows(minimal(id=""), minimal(id="ok"))
        self.assertEqual([r["id"] for r in rows], ["ok"])

    def test_an_unknown_status_reads_as_idle(self):
        self.assertEqual(self.rows(minimal(status="?"))[0]["status"], "idle")

    def test_said_is_shaped_by_the_core(self):
        # The provider hands over the raw last message; the core makes the
        # one line the card shows, the same way it does for Claude.
        row = self.rows(minimal(said="Imported 412 works.\n\nMerge them?"))[0]
        self.assertEqual(row["said"], "Merge them?")
        self.assertEqual(row["ask"], "Merge them?")
        self.assertEqual(row["n"], 1)
        self.assertFalse(row["blocked"])     # the fallback never raises the count

    def test_extras_are_bounded_and_sorted(self):
        many = {f"k{i:02d}": "v" * 100 for i in range(20)}
        row = self.rows(minimal(extras=many))[0]
        self.assertEqual(list(row["extras"]), [f"k{i:02d}" for i in range(8)])
        self.assertTrue(all(len(v) <= 40 for v in row["extras"].values()))

    def test_extras_that_are_not_strings_are_stringified_or_dropped(self):
        row = self.rows(minimal(extras={"cost": 0.42, "bad": None, 3: "x"}))[0]
        self.assertEqual(row["extras"], {"cost": "0.42"})


class Capabilities(unittest.TestCase):
    def rows(self, *sessions, caps):
        return fleet.sessions(providers=[Fake(sessions, caps)])

    def test_without_jump_a_session_is_never_clickable_to_jump(self):
        import os
        row = self.rows(minimal(pid=os.getpid(), canJump=True), caps={"status"})[0]
        self.assertFalse(row["canJump"])

    def test_with_jump_the_provider_may_say_so_itself(self):
        row = self.rows(minimal(pid=1, canJump=True), caps={"jump"})[0]
        self.assertTrue(row["canJump"])

    def test_without_waiting_a_waiting_status_does_not_alarm(self):
        row = self.rows(minimal(status="waiting", waitingFor="input needed",
                                updatedAt=int(time.time() * 1000) - 600000),
                        caps={"status"})[0]
        self.assertIsNone(row["flag"])
        self.assertEqual(row["status"], "waiting")

    def test_with_waiting_it_does(self):
        row = self.rows(minimal(status="waiting", waitingFor="input needed",
                                updatedAt=int(time.time() * 1000) - 600000),
                        caps={"waiting"})[0]
        self.assertEqual(row["flag"], "waiting")


if __name__ == "__main__":
    unittest.main()
