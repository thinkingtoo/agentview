"""What the person sees when a session is stopped by a limit, an API error or
a hang: the kind on its tile, its reason and context, the card's state word
and the card's mix line.

Through `roster()` with fake providers, the way the rest of the columns are
tested. What a provider hands over is `failure` (the API error that is the
session's last record), `lastTool`, `procsUnknown` and the movement facts that
already exist (`quietFor`, `subQuiet`, `bgTasks`, `shellCpu`, `toolFor`).
Names and texts are invented.

R17: a session waiting on a subagent or a background job is never Hung, and
nothing /proc could not answer makes one Hung.
"""
import itertools
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
from test_columns import Base, session
from test_needs_you import asks, prompt, waiting, INJECTION

NOW_MS = time.time() * 1000


def failure(kind="limit", held=22.0, **over):
    """What a provider hands over for an API error, written `held` minutes ago."""
    got = {"kind": kind, "type": "rate_limit" if kind == "limit" else "server_error",
           "status": 429 if kind == "limit" else None, "text": "An invented notice",
           "at": int(time.time() * 1000 - held * 60000), "resetsAt": None}
    got.update(over)
    return got


def tool(words="Run the unit tests", minutes=14.0):
    return {"text": words, "at": int(time.time() * 1000 - minutes * 60000)}


def hung(sid="a", quiet=14.0, **over):
    return session(sid, status="busy", quietFor=quiet, **over)


class Kind(Base):
    def stuck(self, *sessions, **kw):
        return self.tile(*sessions, **kw)["stuck"]


class Limit(Kind):
    def test_a_rate_limit_is_a_limit_with_the_reset_time_and_how_long_it_has_been_held(self):
        reset = int(time.time() * 1000 + 98 * 60000)
        got = self.stuck(session("a", status="idle", failure=failure("limit", held=22.0, resetsAt=reset)))
        self.assertEqual({k: got[k] for k in ("kind", "source", "reason")},
                         {"kind": "limit", "source": "api", "reason": "Rate limit"})
        self.assertEqual(got["context"]["resetsAt"], reset)
        self.assertAlmostEqual(got["context"]["held"], 22.0, delta=0.2)

    def test_a_limit_that_names_no_reset_time_has_none_to_show(self):
        got = self.stuck(session("a", failure=failure("limit")))
        self.assertIsNone(got["context"]["resetsAt"])

    def test_the_error_s_own_words_come_with_it(self):
        got = self.stuck(session("a", failure=failure("limit", text="Invented: hit the limit")))
        self.assertEqual(got["context"]["text"], "Invented: hit the limit")

    def test_a_limit_is_a_limit_whether_the_session_is_idle_or_busy(self):
        for status in ("idle", "busy"):
            with self.subTest(status=status):
                got = self.stuck(session("a", status=status, quietFor=0.1, failure=failure("limit")))
                self.assertEqual(got["kind"], "limit")

    def test_a_limit_is_stuck_even_with_a_background_job_running(self):
        got = self.stuck(session("a", status="idle", failure=failure("limit"),
                                 bgTasks=[{"label": "watch", "since": 3.0}]))
        self.assertEqual(got["kind"], "limit")

    def test_a_limit_held_for_hours_still_says_how_long(self):
        got = self.stuck(session("a", failure=failure("limit", held=5 * 60)))
        self.assertAlmostEqual(got["context"]["held"], 300.0, delta=0.2)


class Error(Kind):
    def reason(self, **over):
        return self.stuck(session("a", failure=failure("error", **over)))["reason"]

    def test_an_overloaded_api_is_overloaded(self):
        self.assertEqual(self.reason(status=529), "Overloaded")

    def test_a_failed_login_is_an_auth_error(self):
        self.assertEqual(self.reason(type="authentication_failed", status=401), "Auth error")
        self.assertEqual(self.reason(type="authentication_failed", status=None), "Auth error")

    def test_a_server_that_failed_is_a_server_error(self):
        self.assertEqual(self.reason(type="server_error", status=None), "Server error")
        self.assertEqual(self.reason(type="server_error", status=500), "Server error")

    def test_another_error_is_named_by_its_type(self):
        self.assertEqual(self.reason(type="invalid_request", status=400), "Invalid request")

    def test_an_error_that_names_nothing_is_an_api_error(self):
        self.assertEqual(self.reason(type="", status=None), "API error")
        self.assertEqual(self.reason(type="error", status=None), "API error")

    def test_the_context_is_the_error_and_when(self):
        got = self.stuck(session("a", failure=failure("error", held=3.0, text="Invented: could not reach")))
        self.assertEqual({k: got["context"][k] for k in ("type", "text")},
                         {"type": "server_error", "text": "Invented: could not reach"})
        self.assertAlmostEqual(got["context"]["ago"], 3.0, delta=0.2)
        self.assertEqual((got["kind"], got["source"]), ("error", "api"))


class Hung(Kind):
    def test_a_busy_session_nothing_proves_moving_for_ten_minutes_is_hung_with_its_last_tool(self):
        got = self.stuck(hung(quiet=14.0, lastTool=tool("Run the unit tests", 14.0)))
        self.assertEqual({k: got[k] for k in ("kind", "source", "reason")},
                         {"kind": "hung", "source": "silence", "reason": "Not moving for 14 min"})
        self.assertEqual(got["context"]["tool"], "Run the unit tests")
        self.assertAlmostEqual(got["context"]["ago"], 14.0, delta=0.2)

    def test_a_hung_session_with_no_tool_to_name_says_so_with_nothing(self):
        got = self.stuck(hung(quiet=14.0))
        self.assertEqual(got["context"], {"tool": "", "ago": None})

    def test_the_time_not_moving_is_the_time_since_the_last_sign_of_life(self):
        got = self.stuck(hung(quiet=40.0, subQuiet=15.0))
        self.assertEqual(got["reason"], "Not moving for 15 min")

    def test_long_silences_are_said_in_hours(self):
        self.assertEqual(self.stuck(hung(quiet=190.0))["reason"], "Not moving for 3 h")

    def test_a_session_still_inside_the_ten_minutes_is_not_hung(self):
        self.assertIsNone(self.stuck(hung(quiet=9.5)))

    def test_the_ten_minutes_come_from_the_config(self):
        self.config = {"hung_after_minutes": 20}
        self.assertIsNone(self.stuck(hung(quiet=15.0)))
        self.assertEqual(self.stuck(hung(quiet=25.0))["reason"], "Not moving for 25 min")

    def test_a_session_waiting_on_a_subagent_that_is_writing_is_never_hung(self):
        self.assertIsNone(self.stuck(hung(quiet=40.0, subQuiet=2.0)))

    def test_a_session_waiting_on_a_background_job_is_never_hung(self):
        self.assertIsNone(self.stuck(hung(quiet=40.0, bgTasks=[{"label": "watch", "since": 40.0}])))

    def test_a_session_waiting_on_a_command_that_is_using_cpu_is_never_hung(self):
        self.assertIsNone(self.stuck(hung(quiet=40.0, toolFor=40.0, shellCpu=True, doing="Run the tests")))

    def test_an_idle_session_is_never_hung_however_long(self):
        self.assertIsNone(self.stuck(session("a", status="idle", quietFor=500.0)))

    def test_a_busy_session_whose_turn_is_over_is_not_hung(self):
        # Hunt 08-2: a lead with teammates keeps the status busy after its turn
        # ends, for hours. Its turn is over: it is idle, not hung.
        tile = self.tile(hung(quiet=40.0, turnOver=True))
        self.assertIsNone(tile["stuck"])
        self.assertFalse(tile["moving"])

    def test_the_own_writes_of_such_a_session_are_no_sign_of_life_on_its_tile(self):
        # movement_of: "its own writes are not signs of life". Its last word was a
        # moment ago, and the tile does not say "writing".
        tile = self.tile(hung(quiet=0.03, turnOver=True))
        self.assertIsNone(tile["movement"])
        self.assertEqual(self.tile(hung(quiet=0.03))["movement"]["kind"], "writing")

    def test_a_session_whose_turn_ended_on_a_rate_limit_is_a_limit_not_hung(self):
        # Hunt 08-3: the reader says the turn is over when the last word is an
        # API error, so the silence behind a limit has no clock to be Hung by.
        got = self.stuck(hung(quiet=40.0, turnOver=True, failure=failure("limit", held=40.0)))
        self.assertEqual((got["kind"], got["reason"]), ("limit", "Rate limit"))
        self.assertAlmostEqual(got["context"]["held"], 40.0, delta=0.2)

    def test_such_a_session_makes_its_card_idle_and_counts_idle_in_the_mix(self):
        column = self.roster(hung(quiet=190.0, turnOver=True))["columns"][0]
        self.assertEqual((column["state"], column["summary"]), ("idle", {"moving": 0, "stuck": 0, "idle": 1}))

    def test_such_a_session_is_moving_while_a_subagent_writes(self):
        tile = self.tile(hung(quiet=40.0, subQuiet=2.0, turnOver=True))
        self.assertIsNone(tile["stuck"])
        self.assertTrue(tile["moving"])

    def test_a_subagent_gone_quiet_does_not_start_a_hung_clock_for_a_session_whose_turn_is_over(self):
        tile = self.tile(hung(quiet=40.0, subQuiet=15.0, turnOver=True))
        self.assertIsNone(tile["stuck"])
        self.assertFalse(tile["moving"])

    def test_only_a_provider_saying_the_turn_is_over_is_believed(self):
        for junk in ("yes", "true", 1, [True], {"a": 1}, None, False):
            with self.subTest(junk=junk):
                self.assertEqual(self.stuck(hung(quiet=40.0, turnOver=junk))["kind"], "hung")

    def test_only_a_busy_session_has_a_time_it_has_not_been_moving(self):
        # `silentFor` is how long a busy session has shown no sign of life. One
        # waiting on the person, or idle, has none, whatever its subagents did.
        def silent(row):
            return self.roster(row)["blocks"][0]["members"][0]["silentFor"]
        for status in ("waiting", "idle"):
            with self.subTest(status=status):
                self.assertIsNone(silent(session("a", status=status, quietFor=500.0, subQuiet=15.0)))
        self.assertEqual(silent(hung(quiet=14.0)), 14.0)

    def test_a_session_with_a_menu_open_is_never_hung(self):
        self.assertIsNone(self.stuck(session("a", status="waiting", waitingFor="dialog open",
                                             quietFor=500.0)))

    def test_a_session_nothing_is_known_about_is_not_called_hung(self):
        # No timing from the provider and no time of the last change: how long
        # it has been quiet cannot be said, so it is not said to be hung.
        self.assertIsNone(self.stuck(session("a", status="busy", updatedAt=0)))

    def test_a_busy_session_whose_writes_cannot_be_seen_is_not_hung_however_long_it_has_been_busy(self):
        # R17: no transcript to read (not found, or gone between two looks) is
        # no evidence of silence. The status has no heartbeat, so the moment
        # it changed says how long it has been busy and nothing about writes.
        for ago in (11, 60, 600):
            with self.subTest(minutes=ago):
                tile = self.tile(session("a", status="busy", updatedAt=int(NOW_MS - ago * 60000)))
                self.assertIsNone(tile["stuck"])
                self.assertEqual(tile["moving"], False)


class HungAfter(Kind):
    """`hung_after_minutes` is a number of minutes greater than nothing: a
    fraction is allowed, zero or less would call everything quiet hung at once."""

    def hung_at(self, setting, quiet):
        self.config = {"hung_after_minutes": setting}
        return self.stuck(hung(quiet=quiet)) is not None

    def test_a_whole_number_is_the_minutes(self):
        self.assertFalse(self.hung_at(20, 15.0))
        self.assertTrue(self.hung_at(20, 25.0))

    def test_a_fraction_is_the_minutes_too(self):
        self.assertFalse(self.hung_at(7.5, 7.0))
        self.assertTrue(self.hung_at(7.5, 8.0))

    def test_anything_that_is_not_a_positive_number_is_the_ten_that_ships(self):
        for junk in ("20", "", None, True, False, 0, 0.0, -5, -0.5, float("nan"), float("inf"), [20], {"a": 1}):
            with self.subTest(junk=junk):
                self.assertFalse(self.hung_at(junk, 9.0))
                self.assertTrue(self.hung_at(junk, 11.0))

    def test_no_setting_at_all_is_ten(self):
        self.config = {}
        self.assertIsNone(self.stuck(hung(quiet=9.0)))
        self.assertIsNotNone(self.stuck(hung(quiet=11.0)))


class TheClock(Kind):
    """Not moving for `hung_after_minutes` means since the last sign of life of
    any kind: a write, CPU under a command, a background job. The signs the core
    stops counting at `WAIT_MAX_MINUTES` end there, not when the session began."""

    CAP = fleet.WAIT_MAX_MINUTES

    def stuck_for(self, **over):
        return self.stuck(hung(**over))

    def test_cpu_seen_five_minutes_ago_is_a_sign_of_life_five_minutes_ago(self):
        self.assertIsNone(self.stuck_for(quiet=40.0, toolFor=40.0, shellCpuAgo=5.0))

    def test_and_at_twelve_minutes_ago_the_session_has_not_been_moving_for_twelve(self):
        got = self.stuck_for(quiet=40.0, toolFor=40.0, shellCpuAgo=12.0)
        self.assertEqual((got["kind"], got["reason"]), ("hung", "Not moving for 12 min"))

    def test_a_write_younger_than_the_cpu_is_the_sign(self):
        got = self.stuck_for(quiet=15.0, toolFor=40.0, shellCpuAgo=30.0)
        self.assertEqual(got["reason"], "Not moving for 15 min")

    def test_cpu_with_no_call_in_flight_is_not_a_sign(self):
        # A shell left behind burns CPU after the call came back.
        got = self.stuck_for(quiet=40.0, shellCpuAgo=2.0)
        self.assertEqual(got["reason"], "Not moving for 40 min")

    def test_cpu_that_was_never_seen_is_not_a_sign(self):
        self.assertEqual(self.stuck_for(quiet=40.0, toolFor=40.0, shellCpuAgo=None)["reason"],
                         "Not moving for 40 min")

    def test_cpu_moving_now_is_a_sign_now(self):
        tile = self.tile(hung(quiet=40.0, toolFor=40.0, shellCpu=True, shellCpuAgo=0.0))
        self.assertEqual((tile["moving"], tile["stuck"]), (True, None))

    def test_a_job_still_inside_the_bound_is_a_sign_now(self):
        self.assertIsNone(self.stuck_for(quiet=500.0, bgTasks=[{"label": "watch", "since": self.CAP - 1}]))

    def test_a_job_past_the_bound_stopped_counting_when_it_passed_it(self):
        # Six hours and five minutes: it stopped counting five minutes ago.
        job = lambda minutes: [{"label": "watch", "since": minutes}]
        self.assertIsNone(self.stuck_for(quiet=500.0, bgTasks=job(self.CAP + 5)))
        got = self.stuck_for(quiet=500.0, bgTasks=job(self.CAP + 11))
        self.assertEqual((got["kind"], got["reason"]), ("hung", "Not moving for 11 min"))

    def test_the_youngest_of_several_jobs_decides(self):
        jobs = [{"label": "old", "since": self.CAP + 90}, {"label": "newer", "since": self.CAP + 3}]
        self.assertIsNone(self.stuck_for(quiet=500.0, bgTasks=jobs))

    def test_a_call_with_cpu_now_past_the_bound_is_a_sign_for_ten_more_minutes(self):
        over = lambda minutes: self.stuck_for(quiet=minutes, toolFor=minutes, shellCpu=True, shellCpuAgo=0.0)
        self.assertIsNone(over(self.CAP + 5))
        self.assertEqual(over(self.CAP + 11)["reason"], "Not moving for 11 min")

    def test_cpu_seen_after_the_bound_is_no_sign_and_the_bound_itself_is_the_last_one(self):
        # A call 7 h old: the mark where it stopped counting is 60 min ago. CPU
        # seen 30 min ago came after the mark and proves nothing; the mark stands.
        got = self.stuck_for(quiet=420.0, toolFor=420.0, shellCpuAgo=30.0)
        self.assertEqual(got["reason"], "Not moving for 1 h")

    def test_cpu_that_stopped_before_the_bound_was_reached_counts_from_when_it_stopped(self):
        # CPU last seen 150 min ago, before the mark at 60: it is the CPU that ended it.
        got = self.stuck_for(quiet=420.0, toolFor=420.0, shellCpuAgo=150.0)
        self.assertEqual(got["reason"], "Not moving for 2 h")

    def test_a_subagent_still_writing_is_a_sign(self):
        self.assertIsNone(self.stuck_for(quiet=500.0, subQuiet=2.0))

    def test_the_time_is_never_less_than_the_ten_minutes_when_hung(self):
        cases = itertools.product((12.0, 40.0, 500.0), (None, 0.0, 3.0, 11.0, 90.0),
                                  (None, 5.0, 14.0), (None, self.CAP - 1, self.CAP + 4, self.CAP + 30),
                                  (False, True))
        for quiet, cpu_ago, sub, job, cpu in cases:
            with self.subTest(quiet=quiet, cpu_ago=cpu_ago, sub=sub, job=job, cpu=cpu):
                row = hung(quiet=quiet, toolFor=quiet, shellCpuAgo=cpu_ago, subQuiet=sub, shellCpu=cpu,
                           bgTasks=[{"label": "watch", "since": job}] if job else [])
                got = self.tile(row)
                if got["stuck"] and got["stuck"]["kind"] == "hung":
                    self.assertFalse(got["moving"])
                    self.assertGreaterEqual(self.roster(row)["blocks"][0]["members"][0]["silentFor"], 10.0)

    def test_a_cpu_time_that_is_not_a_time_is_not_believed(self):
        for junk in ("5", True, -3.0, float("nan"), float("inf"), [1], None):
            with self.subTest(junk=junk):
                got = self.stuck_for(quiet=40.0, toolFor=40.0, shellCpuAgo=junk)
                self.assertEqual(got["reason"], "Not moving for 40 min")


class Races(Kind):
    """R17: /proc that could not answer is not proof that nothing runs."""

    def test_a_session_whose_processes_could_not_be_read_is_not_hung(self):
        self.assertIsNone(self.stuck(hung(quiet=40.0, toolFor=40.0, procsUnknown=True)))

    def test_and_is_hung_once_they_can_and_show_nothing(self):
        self.assertEqual(self.stuck(hung(quiet=40.0, toolFor=40.0, procsUnknown=False))["kind"], "hung")

    def test_a_session_whose_processes_could_not_be_read_but_whose_job_is_known_is_moving(self):
        tile = self.tile(hung(quiet=40.0, procsUnknown=True, bgTasks=[{"label": "watch", "since": 5.0}]))
        self.assertTrue(tile["moving"])
        self.assertIsNone(tile["stuck"])

    def test_only_a_provider_saying_so_is_believed_that_it_could_not_read(self):
        for junk in ("yes", 1, [1], None, 0, ""):
            with self.subTest(junk=junk):
                self.assertEqual(self.stuck(hung(quiet=40.0, procsUnknown=junk))["kind"], "hung")


class Order(Kind):
    """One session may be several things. The tile says the most urgent, in
    the order the card does: Needs you, Error, Hung, Limit."""

    def test_needs_you_beats_an_error(self):
        got = self.stuck(waiting(asking=asks(), failure=failure("error")))
        self.assertEqual(got["kind"], "needs")

    def test_an_error_beats_hung(self):
        got = self.stuck(hung(quiet=40.0, failure=failure("error")))
        self.assertEqual(got["kind"], "error")

    def test_hung_beats_a_limit(self):
        got = self.stuck(hung(quiet=40.0, failure=failure("limit")))
        self.assertEqual(got["kind"], "hung")

    def test_a_limit_beats_moving(self):
        self.assertEqual(self.stuck(hung(quiet=0.1, failure=failure("limit")))["kind"], "limit")


class Card(Base):
    def state(self, *sessions):
        return self.roster(*sessions)["columns"][0]["state"]

    def writing(self, sid):
        return session(sid, status="busy", quietFor=0.1)

    ORDER = ("needs", "error", "hung", "limit", "moving", "idle")

    def make(self, name, sid):
        return {
            "needs": lambda: waiting(sid, asking=asks()),
            "error": lambda: session(sid, status="idle", failure=failure("error")),
            "hung": lambda: hung(sid, quiet=40.0),
            "limit": lambda: session(sid, status="idle", failure=failure("limit")),
            "moving": lambda: self.writing(sid),
            "idle": lambda: session(sid, status="idle"),
        }[name]()

    def test_the_card_takes_the_most_urgent_session_in_the_full_order(self):
        # Every two of the six, both ways round: the one higher in the order wins.
        for first, second in itertools.permutations(self.ORDER, 2):
            with self.subTest(first=first, second=second):
                got = self.state(self.make(first, "s1"), self.make(second, "s2"))
                self.assertEqual(got, min(first, second, key=self.ORDER.index))

    def test_all_six_together_are_needs_you_and_without_it_the_next_down(self):
        for n in range(len(self.ORDER)):
            names = self.ORDER[n:]
            with self.subTest(names=names):
                got = self.state(*[self.make(name, f"s{i}") for i, name in enumerate(reversed(names))])
                self.assertEqual(got, names[0])

    def test_each_kind_below_another_still_wins_over_moving_and_idle(self):
        for name, make in (("error", lambda sid: session(sid, status="idle", failure=failure("error"))),
                           ("hung", lambda sid: hung(sid, quiet=40.0)),
                           ("limit", lambda sid: session(sid, status="idle", failure=failure("limit")))):
            with self.subTest(kind=name):
                self.assertEqual(self.state(self.writing("m"), session("i", status="idle"), make("k")), name)

    def test_a_card_whose_only_trouble_is_a_menu_the_person_opened_is_not_stuck(self):
        got = self.roster(session("a", status="waiting", waitingFor="dialog open", updatedAt=int(NOW_MS - 120000)))
        column = got["columns"][0]
        self.assertEqual((column["state"], column["summary"]), ("idle", {"moving": 0, "stuck": 0, "idle": 1}))


class Mix(Base):
    def summary(self, *sessions):
        return self.roster(*sessions)["columns"][0]["summary"]

    def test_the_mix_counts_stuck_by_kind(self):
        got = self.summary(
            waiting("a", asking=asks()),
            session("b", status="idle", failure=failure("error")),
            hung("c", quiet=40.0),
            session("d", status="idle", failure=failure("limit")),
            session("e", status="busy", quietFor=0.1),
            session("f", status="idle"))
        self.assertEqual(got, {"moving": 1, "stuck": 4, "idle": 1})

    def test_an_error_session_is_stuck_even_with_a_job_running(self):
        got = self.summary(session("a", status="idle", failure=failure("error"),
                                   bgTasks=[{"label": "watch", "since": 3.0}]))
        self.assertEqual(got, {"moving": 0, "stuck": 1, "idle": 0})

    def test_a_busy_session_with_unreadable_processes_is_not_stuck(self):
        got = self.summary(hung(quiet=40.0, toolFor=40.0, procsUnknown=True))
        self.assertEqual(got, {"moving": 0, "stuck": 0, "idle": 1})

    def test_a_session_counted_stuck_always_has_a_kind_on_its_tile(self):
        statuses = ("idle", "busy", "waiting")
        waits = ("", "dialog open", "input needed", "permission prompt")
        quiets = (None, 0.2, 40.0)
        fails = (None, failure("limit"), failure("error"))
        jobs = ([], [{"label": "watch", "since": 3.0}])
        askings = (None, asks(), prompt())
        for status, wait, quiet, fail, job, asking in itertools.product(
                statuses, waits, quiets, fails, jobs, askings):
            over = {"status": status, "waitingFor": wait, "bgTasks": job}
            if quiet is not None:
                over["quietFor"] = quiet
            if fail:
                over["failure"] = fail
            if asking:
                over["asking"] = asking
            with self.subTest(**{k: v for k, v in over.items() if k != "failure"}, fail=bool(fail)):
                column = self.roster(session("a", **over))["columns"][0]
                tile = column["sessions"][0]
                self.assertEqual(column["summary"]["stuck"], 1 if tile["stuck"] else 0)
                self.assertEqual(sum(column["summary"].values()), 1)

    def test_the_mix_and_the_state_word_agree_on_whether_anything_is_stuck(self):
        for make in (lambda: waiting("a", asking=asks()),
                     lambda: session("a", status="idle", failure=failure("limit")),
                     lambda: hung("a", quiet=40.0),
                     lambda: session("a", status="busy", quietFor=0.1),
                     lambda: session("a", status="idle")):
            column = self.roster(make())["columns"][0]
            self.assertEqual(column["summary"]["stuck"] > 0, column["state"] in ("needs", "error", "hung", "limit"))


class Chime(Base):
    """Today's flags stay as they are, because the chime reads them. The kinds
    are for the page and add nothing to what rings."""

    READ = ("key", "status", "flag", "blocked", "waitingFor", "n", "ask")

    def heard(self, *sessions):
        got = self.roster(*sessions)["blocks"]
        return [{"alarms": b["alarms"], "blocked": b["blocked"], "ready": b["ready"],
                 "busy": b["busy"],
                 "members": [{k: m[k] for k in self.READ} for m in b["members"]]}
                for b in got]

    def test_a_hung_session_is_still_stuck_to_the_chime_and_the_tile_does_not_say_it(self):
        got = self.roster(hung(quiet=17.0))
        member = got["blocks"][0]["members"][0]
        self.assertEqual((member["flag"], got["blocks"][0]["alarms"]), ("stuck", 1))
        tile = got["columns"][0]["sessions"][0]
        self.assertEqual((tile["flag"], tile["stuck"]["kind"]), (None, "hung"))

    def test_a_hung_session_rings_exactly_as_it_did(self):
        self.assertEqual(self.heard(hung(quiet=17.0, lastTool=tool(), procsUnknown=False)),
                         self.heard(hung(quiet=17.0)))

    def test_a_failure_adds_nothing_to_what_rings(self):
        for kind in ("limit", "error"):
            for status in ("idle", "busy"):
                with self.subTest(kind=kind, status=status):
                    plain = session("a", status=status, quietFor=0.1)
                    self.assertEqual(self.heard(session("a", status=status, quietFor=0.1,
                                                        failure=failure(kind))),
                                     self.heard(plain))

    def test_an_error_on_a_waiting_session_rings_as_the_waiting_session_does(self):
        self.assertEqual(self.heard(waiting(asking=asks(), failure=failure("error"))),
                         self.heard(waiting(asking=asks())))

    def test_a_session_unreadable_by_proc_still_rings_as_stuck(self):
        member = self.heard(hung(quiet=17.0, procsUnknown=True))[0]["members"][0]
        self.assertEqual(member["flag"], "stuck")

    def test_the_tile_of_a_busy_session_proc_cannot_read_has_no_stuck_flag_and_no_kind(self):
        tile = self.tile(hung(quiet=17.0, toolFor=17.0, procsUnknown=True))
        self.assertEqual((tile["flag"], tile["stuck"]), (None, None))


class Bounds(Base):
    JUNK = ("a failure", 7, None, [], {}, {"kind": "poll"}, {"kind": "limit", "at": "x"},
            {"kind": "limit", "type": ["x"], "status": "429", "text": 5, "at": -1, "resetsAt": "soon"},
            {"kind": "error", "at": float("inf"), "resetsAt": float("nan")},
            {"kind": "error", "text": "x" * 5000, "type": "t" * 500})

    def test_what_cannot_be_read_marks_nothing_or_marks_with_a_whole_one(self):
        for junk in self.JUNK:
            with self.subTest(junk=junk):
                got = self.tile(session("a", status="idle", failure=junk))["stuck"]
                if got is None:
                    continue
                self.assertIn(got["kind"], ("limit", "error"))
                self.assertEqual(set(got), {"kind", "source", "reason", "context"})
                self.assertIsInstance(got["reason"], str)
                self.assertTrue(got["reason"])

    def test_the_words_of_an_error_and_its_type_are_cut_to_what_a_tile_holds(self):
        got = fleet.failure_of({"kind": "error", "text": "x" * 5000, "type": "t" * 500}, time.time())
        self.assertLessEqual(len(got["text"]), fleet.FAILURE_LEN)
        self.assertLessEqual(len(got["type"]), fleet.LABEL_LEN)

    def test_a_time_that_is_ahead_of_the_clock_is_held_for_nothing_not_for_less(self):
        got = fleet.failure_of(failure("limit", at=int(time.time() * 1000 + 3600000)), time.time())
        self.assertEqual(got["held"], 0.0)

    def test_no_time_is_no_hold(self):
        self.assertIsNone(fleet.failure_of({"kind": "limit"}, time.time())["held"])

    def test_a_last_tool_that_is_not_one_is_none(self):
        for junk in ("Bash", 5, None, [], {}, {"text": 5, "at": 1}, {"text": "x"}, {"text": "x", "at": "now"},
                     {"text": "", "at": 1}):
            with self.subTest(junk=junk):
                self.assertIsNone(fleet.tool_of(junk, time.time()))

    def test_a_last_tool_has_its_words_cut_and_its_age(self):
        got = fleet.tool_of({"text": "w" * 900, "at": int(time.time() * 1000 - 120000)}, time.time())
        self.assertLessEqual(len(got["text"]), fleet.HINT_LEN)
        self.assertAlmostEqual(got["ago"], 2.0, delta=0.1)


class Literal(Base):
    """R7: what a session or Claude Code wrote is text. It arrives as it was."""

    def test_markup_in_an_error_and_a_tool_arrives_unchanged(self):
        err = self.tile(session("a", status="idle", failure=failure("error", text=INJECTION)))["stuck"]
        self.assertEqual(err["context"]["text"], INJECTION)
        hang = self.tile(hung(quiet=40.0, lastTool=tool(INJECTION)))["stuck"]
        self.assertEqual(hang["context"]["tool"], INJECTION)

    def test_markup_in_an_error_type_is_a_reason_that_is_the_type_as_text(self):
        got = self.tile(session("a", status="idle", failure=failure("error", type=INJECTION)))["stuck"]
        self.assertIn("<", got["reason"])


if __name__ == "__main__":
    unittest.main()
