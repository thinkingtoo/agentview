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
    "key", "provider", "id", "flag", "status", "name", "title",
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
        # `overridden` is laid on by `members()`, below.
        self.assertEqual(PAGE_FIELDS - set(row), {"overridden"})
        self.assertEqual(row["key"], "fake:s1")
        self.assertEqual(row["provider"], "fake")
        self.assertEqual(row["project"], "maple")

    def test_and_roster_does_not_explode_on_it(self):
        rows = self.rows(minimal())
        real = fleet.sessions
        fleet.sessions = lambda providers=None: rows
        try:
            members = fleet.members()
            roster = fleet.roster()
        finally:
            fleet.sessions = real
        self.assertEqual(members[0]["key"], "fake:s1")
        self.assertIn("overridden", members[0])
        self.assertEqual([t["key"] for c in roster["columns"] for t in c["sessions"]], ["fake:s1"])

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


class Shared(unittest.TestCase):
    """The two small checks every provider field goes through: a time, and a
    whole number. One copy each, used by the reader and by the core."""

    def test_a_whole_number_is_one_and_a_bool_is_not(self):
        from providers import base
        for good in (0, 5, -3, 10 ** 30):
            self.assertEqual(base.whole_number(good), good)
        for junk in (True, False, 1.5, 2.0, "5", None, [5], float("nan")):
            with self.subTest(junk=junk):
                self.assertIsNone(base.whole_number(junk))

    def test_a_time_in_milliseconds_is_a_positive_number_below_the_year_5000(self):
        from providers import base
        self.assertEqual(base.milliseconds(1792263600000), 1792263600000)
        self.assertEqual(base.milliseconds(1792263600000.9), 1792263600000)
        for junk in (True, "tomorrow", None, [1], {"a": 1}, 0, -5, float("nan"), float("inf"),
                     base.MAX_MS, 10 ** 30, 10 ** 400):
            with self.subTest(junk=junk):
                self.assertIsNone(base.milliseconds(junk))

    def test_a_time_in_seconds_comes_back_in_milliseconds(self):
        from providers import base
        self.assertEqual(base.milliseconds(1792263600, seconds=True), 1792263600000)
        self.assertEqual(base.milliseconds(1792263600.5, seconds=True), 1792263600500)
        for junk in (True, "x", 0, -1, float("inf"), 10 ** 12, 10 ** 400):
            with self.subTest(junk=junk):
                self.assertIsNone(base.milliseconds(junk, seconds=True))

    def test_a_number_a_provider_cannot_mean_is_none_and_never_an_exception(self):
        # One bad value from one provider must not break the round for all of them.
        for junk in (float("nan"), float("inf"), float("-inf"), 10 ** 400, -(10 ** 400)):
            with self.subTest(junk=junk):
                self.assertIsNone(fleet._minutes(junk))
                self.assertIsNone(fleet._age(junk))
                self.assertEqual(fleet._int(junk), 0)
        self.assertEqual(fleet._minutes(3), 3.0)
        self.assertEqual(fleet._minutes(-3.5), -3.5)
        self.assertEqual(fleet._int(7.9), 7)
        self.assertEqual(fleet._int(2 ** 53), 2 ** 53)
        self.assertEqual(fleet._int(2 ** 53 + 1), 0)         # more than a float holds exactly

    def test_a_roster_survives_every_number_field_holding_one(self):
        for junk in (float("nan"), float("inf"), 10 ** 400):
            with self.subTest(junk=junk):
                row = minimal(quietFor=junk, subQuiet=junk, toolFor=junk, shellCpuAgo=junk,
                              updatedAt=junk, startedAt=junk, pid=junk, status="busy",
                              bgTasks=[{"label": "x", "since": junk}])
                got = fleet.roster(providers=[Fake([row])])
                self.assertEqual([f["key"] for f in got["flags"]], ["fake:s1"])

    def test_the_cut_of_what_an_error_says_has_one_number(self):
        import fleet
        from providers import base, claude
        self.assertEqual(fleet.FAILURE_LEN, base.FAILURE_LEN)
        self.assertFalse(hasattr(claude, "FAILURE_LEN"))


if __name__ == "__main__":
    unittest.main()
