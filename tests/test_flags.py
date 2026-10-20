"""The roster's `flags`: what the chime and the server read now that the
roster carries no `blocks`.

One row per session on the machine, routines and pills included, because the
chime has always rung for a routine that stops to ask and the server forgets
a session's marks only when it is gone from the machine, not from the page.
The flag is the raw one the chime has always read; the tile may say less.
Names and texts are invented.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import lines
import seen
from test_columns import Base, session
from test_finished import HOUR, ago
from test_needs_you import waiting
from test_providers import Fake


class Flags(Base):
    def flags(self, *sessions):
        return self.roster(*sessions)["flags"]

    def by_key(self, *sessions):
        return {f["key"]: f for f in self.flags(*sessions)}

    def pill(self, sid="p"):
        """A session idle for three hours whose handover you have read."""
        s = session(sid, "maple", status="idle", updatedAt=ago(3 * HOUR), said="Done.")
        fleet.mark_seen(f"fake:{sid}", s)
        return s

    def test_the_roster_has_flags_and_no_blocks(self):
        got = self.roster(session("a"))
        self.assertEqual(sorted(got), ["banners", "columns", "counts", "flags"])
        self.assertNotIn("blocks", got)

    def test_a_row_is_the_key_the_id_the_name_the_raw_flag_and_whether_it_is_blocked(self):
        (row,) = self.flags(waiting("a", name="Ilse"))
        self.assertEqual(row, {"key": "fake:a", "id": "a", "name": "Ilse",
                               "flag": "waiting", "blocked": False})

    def test_there_is_one_row_for_every_session_on_the_machine(self):
        # A routine is not a column and a finished session is a pill, not a
        # tile; the chime and the marks the server keeps still know them.
        rows = self.by_key(
            session("a", "maple"), session("b", None),
            session("r", None, routine="nightly-report", status="waiting", waitingFor="input needed"),
            self.pill())
        self.assertEqual(sorted(rows), ["fake:a", "fake:b", "fake:p", "fake:r"])
        self.assertEqual(rows["fake:r"]["flag"], "waiting")

    def test_a_routine_and_a_pill_are_in_flags_and_not_in_the_tiles(self):
        got = self.roster(session("r", None, routine="nightly-report"), self.pill(), session("a", "maple"))
        (column,) = got["columns"]
        self.assertEqual(([t["key"] for t in column["sessions"]], [t["key"] for t in column["pills"]]),
                         (["fake:a"], ["fake:p"]))
        self.assertEqual(sorted(f["key"] for f in got["flags"]), ["fake:a", "fake:p", "fake:r"])

    def test_each_kind_of_flag_is_carried_raw(self):
        rows = self.by_key(
            waiting("w"),
            session("y", status="idle"),
            session("t", status="busy", quietFor=34.0, toolFor=34.0),
            session("s", status="busy", quietFor=7.0),
            session("n", status="busy", quietFor=0.1))
        self.assertEqual({k.split(":")[1]: f["flag"] for k, f in rows.items()},
                         {"w": "waiting", "y": "ready", "t": "tool", "s": "stuck", "n": None})

    def test_the_tile_may_say_less_than_the_flag_does(self):
        # Quiet 7 minutes is moving on the tile and `stuck` to the chime.
        got = self.roster(session("a", status="busy", quietFor=7.0))
        self.assertIsNone(got["columns"][0]["sessions"][0]["flag"])
        self.assertEqual(got["flags"][0]["flag"], "stuck")

    def test_a_session_that_wrote_down_what_blocks_it_is_blocked(self):
        lines.begin_turn("a", self.lines)
        lines.write("a", did="Built.", ask="Which branch?", n=1, root=self.lines)
        (row,) = self.flags(session("a"))
        self.assertEqual((row["flag"], row["blocked"]), ("ready", True))

    def test_a_session_a_provider_lists_twice_is_one_row(self):
        twice = Fake([session("a", name="Ilse"), session("a", name="Ilse", boss=True)])
        fleet.CONFIG.write_text("{}")
        rows = fleet.roster(providers=[twice])["flags"]
        self.assertEqual([r["key"] for r in rows], ["fake:a"])

    def test_the_old_marks_still_keep_the_ready_flag_off(self):
        s = session("a", status="idle", updatedAt=ago(5 * HOUR))
        seen.mark("fake:a", s["updatedAt"])
        (row,) = self.flags(s)
        self.assertIsNone(row["flag"])


class CodexRings(Base):
    """A provider that cannot say `waiting` still has a row that asks: a Codex
    command that escalated and has no answer. The tile says Needs you; the
    chime reads the same row as a waiting one, whatever the provider's
    capabilities."""

    CODEX = {"jump", "branch"}
    ASK = {"kind": "permission", "tool": "Shell", "command": "git push origin dev", "target": ""}

    def flag(self, caps, *sessions):
        fleet.CONFIG.write_text("{}")
        rows = fleet.roster(providers=[Fake(sessions, caps)])["flags"]
        return {r["id"]: r["flag"] for r in rows}

    def codex(self, sid="c", **over):
        return session(sid, status="waiting", asking=self.ASK, **over)

    def test_a_codex_row_that_asks_is_waiting_to_the_chime(self):
        self.assertEqual(self.flag(self.CODEX, self.codex()), {"c": "waiting"})

    def test_and_its_tile_is_still_needs_you_with_the_flag_the_tile_always_had(self):
        fleet.CONFIG.write_text("{}")
        got = fleet.roster(providers=[Fake([self.codex()], self.CODEX)])["columns"][0]["sessions"][0]
        self.assertEqual((got["stuck"]["kind"], got["stuck"]["source"], got["flag"]), ("needs", "permission", None))

    def test_a_codex_row_that_is_busy_or_idle_never_rings(self):
        for status in ("busy", "idle"):
            with self.subTest(status=status):
                got = self.flag(self.CODEX, session("c", status=status, quietFor=0.1, asking=self.ASK))
                self.assertNotEqual(got["c"], "waiting")
        self.assertIsNone(self.flag(self.CODEX, session("c", status="busy", quietFor=0.1))["c"])

    def test_a_codex_row_that_waits_with_nothing_to_approve_does_not_ring(self):
        self.assertIsNone(self.flag(self.CODEX, session("c", status="waiting"))["c"])

    def test_any_open_request_rings_as_it_is_needs_you_on_the_tile(self):
        got = self.flag(self.CODEX, session("c", status="waiting", asking={"kind": "question", "questions": []}))
        self.assertEqual(got["c"], "waiting")

    def test_a_pause_is_a_limit_on_the_tile_and_does_not_ring(self):
        got = self.flag(self.CODEX, session("c", status="waiting", asking={"kind": "pause", "what": "Usage credits"}))
        self.assertIsNone(got["c"])

    def test_a_claude_row_rings_as_before(self):
        # Within the first seconds an unnamed wait is still not an alarm, even
        # with a permission prompt open: the new path is not for providers that
        # can say `waiting` themselves.
        fresh = session("c", status="waiting", asking=self.ASK, updatedAt=fleet.time.time() * 1000)
        self.assertIsNone(self.flag({"jump", "branch", "waiting", "name", "status"}, fresh)["c"])
        self.assertEqual(self.flag({"jump", "branch", "waiting", "name", "status"},
                                   waiting("c", asking=self.ASK))["c"], "waiting")


class Members(Base):
    """`members()` is what the roster is made from, kept for the tests that
    read a session's raw fields: the flag, `silentFor`, what the round dropped."""

    def members(self, *sessions):
        fleet.CONFIG.write_text("{}")
        return fleet.members(providers=[Fake(sessions)])

    def test_it_lists_every_session_and_the_routines_last(self):
        got = self.members(session("r", None, routine="nightly-report"),
                           session("a", "maple"), session("b", None))
        self.assertEqual([m["key"] for m in got], ["fake:a", "fake:b", "fake:r"])

    def test_a_boss_leads_its_project_and_the_team_follows(self):
        got = self.members(
            session("w", "maple", name="Worker", status="idle", updatedAt=ago(1)),
            session("b", "maple", name="Boss", boss=True, team=["Worker"], status="busy", quietFor=0.1,
                    updatedAt=ago(5)))
        self.assertEqual([m["name"] for m in got], ["Boss", "Worker"])

    def test_it_keeps_the_fields_the_columns_are_made_from(self):
        (m,) = self.members(session("a", "maple", status="busy", quietFor=7.0))
        self.assertEqual((m["flag"], m["silentFor"]), ("stuck", 7.0))
        self.assertIn("paths", m)


if __name__ == "__main__":
    unittest.main()
