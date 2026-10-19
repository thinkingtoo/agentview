"""What the person sees of movement: the sign on each tile, the strip and the
mix on each card. Through `roster()` with fake providers, the way the rest of
the columns are tested; the provider's own facts are what a Claude session
hands over (`writes`, `subQuiet`, `bgTasks`, `shellCpu`, `quietFor`,
`toolFor`, `doing`).

Names and texts are invented.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import lines
from test_columns import Base, session

def ago(minutes):
    """The moment a status changed `minutes` ago, as a peer file says it.

    Measured from the call, not from import: the code under test reads the
    clock when it runs, and a suite that has been going for a few seconds
    would otherwise put the sign at 14.1 minutes instead of 14."""
    return int(time.time() * 1000 - minutes * 60000)


def strip(**slots):
    """30 slots, zero but for the ones named: `s29=3` is the newest minute."""
    out = [0] * 30
    for name, count in slots.items():
        out[int(name[1:])] = count
    return out


class Sign(Base):
    def movement(self, **over):
        """What the tile says (kind and words) and whether it counts as moving."""
        tile = self.tile(session("a", **over))
        got = tile["movement"]
        return (got and {k: got[k] for k in ("kind", "text")}), tile["moving"]

    def sign(self, **over):
        got, _ = self.movement(**over)
        return got["text"] if got else None

    def test_a_session_that_just_wrote_is_writing_and_says_how_long_ago(self):
        self.assertEqual(self.movement(status="busy", quietFor=8 / 60),
                         ({"kind": "writing", "text": "writing · 8s ago"}, True))

    def test_a_busy_session_that_wrote_minutes_ago_is_still_writing(self):
        self.assertEqual(self.sign(status="busy", quietFor=3.2), "writing · 3 min ago")

    def test_a_subagent_that_wrote_is_the_session_writing(self):
        self.assertEqual(self.sign(status="busy", quietFor=12.0, subQuiet=20 / 60),
                         "writing · 20s ago")

    def test_a_long_command_with_cpu_under_it_is_waiting_on_it_and_moving(self):
        got = self.movement(status="busy", quietFor=12.0, toolFor=12.0,
                            doing="Run the unit tests", shellCpu=True)
        self.assertEqual(got, ({"kind": "waiting", "text": "waiting on: Run the unit tests, 12 min"}, True))

    def test_a_long_command_with_nothing_using_cpu_is_named_but_not_moving(self):
        # Replaces today's `tool` flag: the same fact, said as a sign. What
        # it is not is evidence of movement.
        got = self.movement(status="busy", quietFor=34.0, toolFor=34.0, doing="Run the unit tests")
        self.assertEqual(got, ({"kind": "waiting", "text": "waiting on: Run the unit tests, 34 min"}, False))

    def test_a_call_with_no_words_of_its_own_is_a_command(self):
        self.assertEqual(self.sign(status="busy", quietFor=12.0, toolFor=12.0, shellCpu=True),
                         "waiting on: a command, 12 min")

    def test_a_session_waiting_on_a_subagent_that_is_still_writing_says_so(self):
        self.assertEqual(self.movement(status="busy", quietFor=12.0, subQuiet=4.0),
                         ({"kind": "waiting", "text": "waiting on: a subagent, 12 min"}, True))

    def test_a_subagent_still_writing_is_enough_when_the_session_has_no_time_of_its_own(self):
        # Neither number may be missing for the sign to be made: no transcript
        # time for the session, a subagent that wrote four minutes ago.
        self.assertEqual(self.movement(status="busy", subQuiet=4.0),
                         ({"kind": "waiting", "text": "waiting on: a subagent, 4 min"}, True))

    def test_a_subagent_gone_quiet_is_not_movement(self):
        self.assertEqual(self.movement(status="busy", quietFor=12.0, subQuiet=11.0),
                         (None, False))

    def test_an_idle_session_with_a_background_job_is_moving_never_idle(self):
        got = self.movement(status="idle", updatedAt=ago(30), quietFor=29.0,
                            bgTasks=[{"label": "Run the unit tests", "since": 5.0}])
        self.assertEqual(got, ({"kind": "waiting", "text": "waiting on: Run the unit tests, 5 min"}, True))

    def test_several_jobs_are_counted_and_the_oldest_sets_the_time(self):
        self.assertEqual(self.sign(status="idle", updatedAt=ago(30),
                                   bgTasks=[{"label": "a", "since": 20.0}, {"label": "b", "since": 5.0}]),
                         "waiting on: 2 background jobs, 20 min")

    def test_an_idle_session_is_idle_and_says_since_when(self):
        self.assertEqual(self.movement(status="idle", updatedAt=ago(14), quietFor=14.0),
                         ({"kind": "idle", "text": "idle 14 min"}, False))

    def test_a_session_that_only_just_stopped_is_idle_not_writing(self):
        # Its last record was written seconds ago, and it is done.
        self.assertEqual(self.sign(status="idle", updatedAt=ago(0.1), quietFor=0.1),
                         "idle <1 min")

    def test_idle_for_hours_and_days_says_hours_and_days(self):
        self.assertEqual(self.sign(status="idle", updatedAt=ago(190)), "idle 3 h")
        self.assertEqual(self.sign(status="idle", updatedAt=ago(60 * 24 * 3)), "idle 3 d")

    def test_a_session_that_never_said_when_it_stopped_is_just_idle(self):
        self.assertEqual(self.sign(status="idle", updatedAt=0), "idle")

    def test_a_busy_session_that_has_gone_quiet_with_nothing_running_has_no_sign(self):
        self.assertEqual(self.movement(status="busy", quietFor=15.0), (None, False))

    def test_a_provider_that_says_nothing_about_a_session_that_just_began_work_is_given_the_time(self):
        # The status changing to busy a few minutes ago is an event, and the
        # only one there is. It is not evidence for ever.
        self.assertEqual(self.movement(status="busy", updatedAt=ago(3)), (None, True))

    def test_and_a_busy_status_nobody_has_heard_from_in_ten_minutes_proves_nothing(self):
        # The peer status has no heartbeat: busy for an hour is not movement.
        self.assertEqual(self.movement(status="busy", updatedAt=ago(60)), (None, False))
        self.assertEqual(self.movement(status="busy", updatedAt=0), (None, False))

    def test_a_finished_session_is_not_moving_because_a_subagent_wrote_a_minute_ago(self):
        # Every subagent run ends with the parent going idle seconds later.
        self.assertEqual(self.movement(status="idle", updatedAt=ago(3), quietFor=3.0, subQuiet=1.0),
                         ({"kind": "idle", "text": "idle 3 min"}, False))

    def test_a_session_waiting_on_a_dialog_is_not_writing(self):
        # Its last record is the question. The tile says Needs you in its own
        # way; the movement sign does not contradict it.
        self.assertEqual(self.movement(status="waiting", waitingFor="input needed", quietFor=0.2,
                                       updatedAt=ago(1)), (None, False))


class WhatTheSignCarries(Base):
    """The sign is words for the person, and facts for whoever reads the roster."""

    def sign(self, **over):
        return self.tile(session("a", **over))["movement"]

    def test_writing_carries_how_many_seconds_ago(self):
        self.assertEqual(self.sign(status="busy", quietFor=8 / 60)["ago"], 8)

    def test_waiting_carries_what_on_and_for_how_many_minutes(self):
        got = self.sign(status="busy", quietFor=12.0, toolFor=12.0, doing="Run the unit tests",
                        shellCpu=True)
        self.assertEqual((got["on"], got["since"]), ("Run the unit tests", 12.0))

    def test_idle_carries_since_when(self):
        self.assertEqual(self.sign(status="idle", updatedAt=ago(14))["since"], 14.0)


class TheBound(Base):
    """R16: evidence from a process or a job counts only for so long."""

    def moving(self, **over):
        return self.tile(session("a", **over))["moving"]

    def test_a_command_with_cpu_is_moving_for_hours_but_not_for_ever(self):
        hours = lambda h: dict(status="busy", quietFor=h * 60, toolFor=h * 60, shellCpu=True)
        self.assertTrue(self.moving(**hours(5)))
        self.assertFalse(self.moving(**hours(7)))

    def test_a_background_job_is_moving_for_hours_but_not_for_ever(self):
        job = lambda h: dict(status="idle", updatedAt=ago(h * 60),
                             bgTasks=[{"label": "watch", "since": h * 60}])
        self.assertTrue(self.moving(**job(5)))
        self.assertFalse(self.moving(**job(7)))

    def test_a_busy_session_keeps_the_grace_after_the_bound_for_ten_minutes(self):
        # The evidence stops at six hours; "not moving for ten minutes" is
        # counted from there, not from the session's last write.
        past = lambda minutes: minutes + fleet.WAIT_MAX_MINUTES
        cpu = lambda m: dict(status="busy", quietFor=past(m), toolFor=past(m), shellCpu=True)
        job = lambda m: dict(status="busy", quietFor=past(m) + 30,
                             bgTasks=[{"label": "watch", "since": past(m)}])
        for make in (cpu, job):
            with self.subTest(make=make.__name__):
                self.assertTrue(self.moving(**make(5)))
                self.assertFalse(self.moving(**make(11)))

    def test_cpu_with_no_call_in_flight_proves_nothing(self):
        # A shell left behind burns CPU after the call came back.
        self.assertFalse(self.moving(status="idle", updatedAt=ago(40), shellCpu=True))
        self.assertFalse(self.moving(status="busy", quietFor=40.0, shellCpu=True))

    def test_the_bound_is_one_the_caller_can_read(self):
        self.assertEqual(fleet.WAIT_MAX_MINUTES, 360)


class Thresholds(Base):
    def test_a_busy_session_is_moving_until_it_has_been_quiet_for_ten_minutes(self):
        moving = lambda q: self.tile(session("a", status="busy", quietFor=q))["moving"]
        self.assertTrue(moving(9.5))
        self.assertFalse(moving(10.5))

    def test_the_ten_minutes_come_from_the_config(self):
        self.config = {"hung_after_minutes": 20}
        self.assertTrue(self.tile(session("a", status="busy", quietFor=15.0))["moving"])


class Flags(Base):
    """The chime reads the flags, and they do not change. The tile is what
    the person reads, and it no longer shows a flag the sign contradicts."""

    def test_the_tool_flag_is_gone_from_the_tile_and_still_in_the_blocks(self):
        got = self.roster(session("a", status="busy", quietFor=34.0, toolFor=34.0))
        self.assertIsNone(got["columns"][0]["sessions"][0]["flag"])
        self.assertEqual(got["blocks"][0]["members"][0]["flag"], "tool")

    def test_stuck_is_not_shown_for_a_session_that_is_moving(self):
        # Quiet 7 minutes: today's page said stuck at 5. The new rule says
        # moving until 10.
        got = self.roster(session("a", status="busy", quietFor=7.0))
        self.assertIsNone(got["columns"][0]["sessions"][0]["flag"])
        self.assertEqual(got["blocks"][0]["members"][0]["flag"], "stuck")

    def test_stuck_is_shown_as_hung_once_nothing_moves(self):
        tile = self.tile(session("a", status="busy", quietFor=17.2))
        self.assertEqual((tile["flag"], tile["stuck"]["kind"]), (None, "hung"))

    def test_a_session_waiting_on_a_job_is_not_shown_stuck(self):
        tile = self.tile(session("a", status="busy", quietFor=8.0, toolFor=None,
                                 bgTasks=[{"label": "watch", "since": 8.0}]))
        self.assertIsNone(tile["flag"])
        self.assertTrue(tile["moving"])


class Strip(Base):
    def column(self, *sessions):
        return self.roster(*sessions)["columns"][0]

    def test_the_strip_is_thirty_counts_oldest_first_summed_over_the_sessions(self):
        column = self.column(session("a", writes=strip(s27=2, s29=3)),
                             session("b", writes=strip(s29=4, s0=1)))
        self.assertEqual(column["strip"], strip(s0=1, s27=2, s29=7))
        self.assertEqual(len(column["strip"]), 30)

    def test_a_minute_one_session_did_not_see_is_a_minute_nobody_saw(self):
        # R14: after a restart, one session's file was read from its tail.
        # Zero would say "it wrote nothing", which nobody knows.
        cold = strip(s29=3)
        cold[:10] = [None] * 10
        column = self.column(session("a", writes=cold), session("b", writes=strip(s2=5)))
        self.assertEqual(column["strip"][:10], [None] * 10)
        self.assertEqual(column["strip"][10:], strip(s29=3)[10:])

    def test_a_session_whose_provider_does_not_count_is_left_out_not_counted_as_zero(self):
        column = self.column(session("a", writes=strip(s29=3)), session("b"))
        self.assertEqual(column["strip"], strip(s29=3))

    def test_a_project_where_nothing_is_counted_has_a_strip_of_unknowns(self):
        self.assertEqual(self.column(session("a"))["strip"], [None] * 30)

    def test_a_strip_that_is_not_thirty_whole_counts_is_not_believed(self):
        for bad in ([1, 2, 3], "no", [0] * 29 + ["x"], [0] * 29 + [-1], [0] * 31, None):
            self.assertEqual(self.column(session("a", writes=bad))["strip"], [None] * 30, bad)

    def test_each_project_has_its_own_strip(self):
        got = self.roster(session("a", "maple", writes=strip(s29=1)),
                          session("b", "orchard", writes=strip(s29=9)))
        self.assertEqual({c["raw"]: c["strip"][29] for c in got["columns"]},
                         {"maple": 1, "orchard": 9})


class Mix(Base):
    def summary(self, *sessions):
        return self.roster(*sessions)["columns"][0]["summary"]

    def test_the_card_counts_moving_stuck_and_idle(self):
        got = self.summary(
            session("a", status="busy", quietFor=0.1),
            session("b", status="busy", quietFor=2.0),
            session("c", status="waiting", waitingFor="input needed", updatedAt=ago(2),
                    asking={"kind": "question", "questions": []}),
            session("d", status="idle", updatedAt=ago(50)))
        self.assertEqual(got, {"moving": 2, "stuck": 1, "idle": 1})

    def test_a_session_that_needs_you_is_stuck_even_with_a_job_running(self):
        got = self.summary(session("a", status="waiting", waitingFor="input needed",
                                   updatedAt=ago(2), bgTasks=[{"label": "watch", "since": 3.0}],
                                   asking={"kind": "question", "questions": []}))
        self.assertEqual(got, {"moving": 0, "stuck": 1, "idle": 0})

    def test_an_idle_session_with_a_job_is_moving(self):
        got = self.summary(session("a", status="idle", updatedAt=ago(30),
                                   bgTasks=[{"label": "watch", "since": 30.0}]))
        self.assertEqual(got, {"moving": 1, "stuck": 0, "idle": 0})

    def test_a_busy_session_with_nothing_proving_it_moves_is_stuck(self):
        got = self.summary(session("a", status="busy", quietFor=40.0))
        self.assertEqual(got, {"moving": 0, "stuck": 1, "idle": 0})

    def test_a_session_that_asked_you_something_is_stuck(self):
        self.wrote_ask("a", "Which database should I use?")
        got = self.summary(session("a", status="idle", updatedAt=ago(20)))
        self.assertEqual(got, {"moving": 0, "stuck": 1, "idle": 0})

    def wrote_ask(self, sid, ask):
        lines.begin_turn(sid, self.lines)
        lines.write(sid, did="working", ask=ask, n=1, root=self.lines)


if __name__ == "__main__":
    unittest.main()
