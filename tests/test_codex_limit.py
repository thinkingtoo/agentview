"""A Codex usage limit, said once across the top of the page until it lifts.

The limit is the account's, not a session's, and it outlives the run that hit
it: a `codex exec` run that is refused ends a moment later and its lock goes
with it. So the provider finds it on disk, in the newest finished turn of the
recent rollouts, and the roster turns it into a banner: through `roster()`
with fake providers, and over a fake `~/.codex`. Texts are invented.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
from test_codex import Home, done, meta, rec, stamp, LIMIT, TID
from test_columns import Base, session
from test_providers import Fake

NOW = 1_792_411_200.0                      # Monday 2026-10-19 12:00:00 UTC
HOUR = 3600


def utc(testcase):
    """The machine is in UTC for the length of a test."""
    was = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    testcase.addCleanup(lambda: (os.environ.pop("TZ") if was is None else os.environ.__setitem__("TZ", was),
                                 time.tzset()))


def rollout(home, day, tid, *records):
    """A rollout under `sessions/2026/10/<day>`, its modified time the newest of its records."""
    folder = home.codex / "sessions" / "2026" / "10" / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-2026-10-{day}T10-00-00-{tid}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    newest = max(float(r.get("at", 0)) for r in records) if records else NOW
    os.utime(path, (newest, newest))
    return path


def finished(at, name=None, ok=False, **error):
    """A turn that completed at this moment (seconds), in an error or well."""
    r = done(ts=stamp(at), **error) if error else rec(stamp(at), "event_msg", type="task_complete")
    r["at"] = at
    return r


def refused(at, when="2:35 PM"):
    return finished(at, message=LIMIT % when, codex_error_info="usage_limit_exceeded")


class OnDisk(unittest.TestCase):
    def setUp(self):
        utc(self)
        self.home = Home()
        self.p = self.home.provider()
        self.p.clock = lambda: NOW
        self.addCleanup(shutil.rmtree, self.home.root, True)

    def limit(self):
        self.p.live()
        return self.p.limit()

    def test_a_refused_run_that_has_already_ended_is_still_the_limit(self):
        rollout(self.home, "19", "a" * 36, meta(ts=stamp(NOW - 600)), refused(NOW - 300))
        self.assertEqual(self.p.live(), [])
        self.assertEqual(self.p.limit(), {"name": "Codex", "at": int((NOW - 300) * 1000),
                                          "resetsAt": 1792420500000})

    def test_a_turn_that_finished_well_later_lifts_it(self):
        rollout(self.home, "19", "a" * 36, refused(NOW - 600))
        rollout(self.home, "19", "b" * 36, finished(NOW - 60))
        self.assertIsNone(self.limit())

    def test_a_run_still_going_does_not_lift_it(self):
        rollout(self.home, "19", "a" * 36, refused(NOW - 600))
        rollout(self.home, "19", "b" * 36, rec(stamp(NOW - 30), "event_msg", type="task_started") | {"at": NOW - 30})
        self.assertEqual(self.limit()["at"], int((NOW - 600) * 1000))

    def test_a_refusal_that_is_not_a_limit_is_not_one(self):
        rollout(self.home, "19", "a" * 36, finished(NOW - 60, message="Busy.", codex_error_info="server_overloaded"))
        self.assertIsNone(self.limit())

    def test_a_long_session_s_old_turn_does_not_hide_a_newer_refusal_elsewhere(self):
        # Written to a moment ago, but its last finished turn was hours back.
        rollout(self.home, "19", "a" * 36, finished(NOW - 5 * HOUR),
                rec(stamp(NOW - 10), "event_msg", type="token_count") | {"at": NOW - 10})
        rollout(self.home, "19", "b" * 36, refused(NOW - 600))
        self.assertEqual(self.limit()["at"], int((NOW - 600) * 1000))

    def test_a_file_written_to_lately_does_not_outvote_a_newer_finished_turn_in_an_older_one(self):
        # Both have been written to since: it is the finished turns that are compared.
        rollout(self.home, "19", "a" * 36, refused(NOW - 100),
                rec(stamp(NOW - 10), "event_msg", type="token_count") | {"at": NOW - 10})
        rollout(self.home, "19", "b" * 36, finished(NOW - 5 * HOUR),
                rec(stamp(NOW - 50), "event_msg", type="token_count") | {"at": NOW - 50})
        self.assertEqual(self.limit()["at"], int((NOW - 100) * 1000))

    def test_the_newest_of_two_refusals_gives_the_time(self):
        rollout(self.home, "19", "a" * 36, refused(NOW - 600, "2:35 PM"))
        rollout(self.home, "19", "b" * 36, refused(NOW - 60, "4:05 PM"))
        self.assertEqual(self.limit()["resetsAt"], 1792411200000 + 4 * HOUR * 1000 + 5 * 60000)

    def test_a_refusal_in_a_day_folder_long_past_is_not_looked_for(self):
        for day in range(1, 11):
            rollout(self.home, f"{day:02d}", f"{day:02d}" * 18, finished(NOW - 20 * 86400 + day))
        old = self.home.codex / "sessions" / "2026" / "09" / "05"
        old.mkdir(parents=True)
        path = old / f"rollout-2026-09-05T10-00-00-{'d' * 36}.jsonl"
        path.write_text(json.dumps(refused(NOW - 600)) + "\n")
        os.utime(path, (NOW, NOW))
        self.assertIsNone(self.limit())

    def test_nothing_on_disk_is_no_limit(self):
        self.assertIsNone(self.limit())

    def test_a_rollout_that_goes_while_it_is_looked_at_does_not_stop_the_session_list(self):
        rollout(self.home, "19", "a" * 36, refused(NOW - 600))

        def gone(path):
            raise FileNotFoundError(path)
        self.p.done_tail.scan = gone
        self.assertEqual(self.p.live(), [])
        self.assertIsNone(self.p.limit())

    def test_files_that_are_not_rollouts_or_not_json_are_passed_over(self):
        folder = self.home.codex / "sessions" / "2026" / "10" / "19"
        folder.mkdir(parents=True)
        (folder / "notes.txt").write_text(json.dumps(refused(NOW)))
        (folder / f"rollout-2026-10-19T10-00-00-{'e' * 36}.jsonl").write_text("not json\n{\"a\"\n[1]\n")
        self.assertIsNone(self.limit())

    def test_it_is_looked_for_every_ten_seconds_and_not_every_poll(self):
        path = rollout(self.home, "19", "a" * 36, refused(NOW - 60))
        self.assertIsNotNone(self.limit())
        path.unlink()
        self.assertIsNotNone(self.limit())
        self.p.clock = lambda: NOW + 11
        self.assertIsNone(self.limit())

    def test_only_what_was_written_since_is_read_the_second_time(self):
        path = rollout(self.home, "19", "a" * 36, refused(NOW - 600))
        self.p.clock = lambda: NOW
        self.limit()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(finished(NOW - 5)) + "\n")
        self.p.clock = lambda: NOW + 11
        self.assertIsNone(self.limit())

    def test_a_session_that_is_live_keeps_its_own_failure_and_the_account_has_the_limit(self):
        self.home.thread()
        self.home.lock()
        self.home.holder(4242)
        self.home.rollout(records=[meta(), refused(NOW - 60)])
        self.assertEqual(self.p.live()[0]["failure"]["kind"], "limit")
        self.assertEqual(self.p.limit()["at"], int((NOW - 60) * 1000))


class Counted(Base):
    """The roster says it once, with the time it lifts, until it does."""

    def setUp(self):
        super().setUp()
        utc(self)
        self.claude = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.claude, True)
        Usage = namedtuple("usage", "total used free")
        was = fleet.disk_usage
        fleet.disk_usage = lambda path: Usage(10**12, 0, 10**12)
        self.addCleanup(setattr, fleet, "disk_usage", was)
        real = time.time
        time.time = lambda: NOW
        self.addCleanup(setattr, time, "time", real)

    def banners(self, *held, extra=()):
        class Codex(Fake):
            name = "codex"

            def limit(self_):
                return held[0] if held else None
        fleet.CONFIG.write_text("{}")
        return fleet.roster(providers=[Codex([session("c", project="maple")]), *extra])["banners"]

    def hold(self, resets, ago=300, **over):
        """What a provider hands over: refused `ago` seconds back, lifting at `resets`."""
        return {"name": "Codex", "at": int((NOW - ago) * 1000),
                "resetsAt": None if resets is None else int(resets * 1000), **over}


    def test_a_limit_that_has_not_lifted_is_one_banner_that_says_when(self):
        self.assertEqual(self.banners(self.hold(NOW + 2 * HOUR + 1200)),
                         [{"kind": "limit", "text": "Codex usage limit reached, resets at 14:20"}])

    def test_a_limit_that_lifts_another_day_says_which(self):
        self.assertEqual(self.banners(self.hold(NOW + 15 * HOUR))[0]["text"],
                         "Codex usage limit reached, resets at 03:00 on Oct 20")

    def test_once_it_has_lifted_there_is_no_banner(self):
        self.assertEqual(self.banners(self.hold(NOW - 1)), [])
        self.assertEqual(self.banners(self.hold(NOW)), [])

    def test_a_limit_that_names_no_time_is_held_for_five_hours_from_the_refusal(self):
        self.assertEqual(self.banners(self.hold(None, ago=4 * HOUR))[0]["text"], "Codex usage limit reached")
        self.assertEqual(self.banners(self.hold(None, ago=5 * HOUR + 1)), [])

    def test_no_limit_is_no_banner(self):
        self.assertEqual(self.banners(), [])

    def test_what_a_provider_says_that_is_not_a_hold_is_no_banner_and_no_crash(self):
        for odd in ("limit", 7, [1], {}, {"name": "Codex"}, {"name": 5, "at": 1, "resetsAt": 2},
                    self.hold(1, resetsAt="soon"), self.hold(1, resetsAt=True), self.hold(1, resetsAt=float("nan")),
                    self.hold(1, resetsAt=10**40), self.hold(1, resetsAt=-5), self.hold(None, at="then"),
                    self.hold(None, at=None), self.hold(None, at=True)):
            with self.subTest(odd=odd):
                self.assertEqual(self.banners(odd), [])

    def test_a_provider_whose_hold_cannot_be_asked_is_no_banner_and_no_crash(self):
        class Broken(Fake):
            name = "broken"

            def limit(self):
                raise RuntimeError("no")
        self.assertEqual(self.banners(extra=[Broken()]), [])

    def test_a_provider_that_did_not_answer_this_round_has_no_say(self):
        class Stalled(Fake):
            name = "stalled"

            def live(self):
                raise RuntimeError("down")

            def limit(self):
                return {"name": "Stalled", "at": int((NOW - 60) * 1000), "resetsAt": int((NOW + 3600) * 1000)}
        self.assertEqual(self.banners(extra=[Stalled()]), [])

    def test_the_banner_is_not_a_kind_of_stuck_on_any_tile(self):
        class Codex(Fake):
            name = "codex"

            def limit(self_):
                return self.hold(NOW + 3600)
        fleet.CONFIG.write_text("{}")
        got = fleet.roster(providers=[Codex([session("c", status="busy", quietFor=0.1)])])
        self.assertEqual(len(got["banners"]), 1)
        self.assertEqual(got["counts"], {"needs": 0, "otherStuck": 0, "moving": 1})
        self.assertIsNone(got["columns"][0]["sessions"][0]["stuck"])

    def test_a_full_disk_and_a_limit_are_two_banners_the_disk_first(self):
        Usage = namedtuple("usage", "total used free")
        fleet.disk_usage = lambda path: Usage(10**12, 10**12, 0)
        got = self.banners(self.hold(NOW + 3600))
        self.assertEqual([b["kind"] for b in got], ["disk", "limit"])

    def test_two_providers_may_each_hold_the_page(self):
        class Other(Fake):
            name = "other"

            def limit(self):
                return {"name": "Other", "at": int((NOW - 60) * 1000), "resetsAt": int((NOW + 3600) * 1000)}
        got = self.banners(self.hold(NOW + 7200), extra=[Other()])
        self.assertEqual([b["text"] for b in got],
                         ["Codex usage limit reached, resets at 14:00", "Other usage limit reached, resets at 13:00"])


if __name__ == "__main__":
    unittest.main()
