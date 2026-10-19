"""Finished sessions: the one-line pills at the foot of a column.

Through `roster()` with fake providers, the way the columns and the header are
tested. A session that has been idle for `finished_after_minutes`, with its
handover read and nothing left for the person, is a pill: out of `sessions`,
in `pills`, counted in nothing. Any sign of life makes it a tile again. The
page prints `pills` and decides nothing. Names and texts are invented.
"""
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import finished
import fleet
import lines
import seen
from test_columns import Base, session
from test_header import idle, moving
from test_needs_you import asks, waiting
from test_stuck_kinds import failure, hung

HOUR = 60


def ago(minutes):
    """The moment `minutes` ago, the way a provider says it: epoch milliseconds."""
    return int((time.time() - minutes * 60) * 1000)


class Finished(Base):
    """What the overview shows: a session `minutes` idle, handover read or not."""

    def stopped(self, sid="a", minutes=3 * HOUR, project="maple", **over):
        """A session that went idle `minutes` ago. Its handover is not read."""
        return session(sid, project, status="idle", updatedAt=ago(minutes), **over)

    def read(self, *sessions):
        """You looked at each of them, as it is now: a jump that reached its
        terminal, or a click on a tile with none, does exactly this."""
        for s in sessions:
            fleet.mark_seen(f"fake:{s['id']}", s)
        return sessions

    def finished(self, sid="a", minutes=3 * HOUR, **over):
        """A session idle for `minutes` whose handover you have read."""
        (s,) = self.read(self.stopped(sid, minutes, **over))
        return s

    def line(self, sid, ask="", n=0, by="session"):
        """The session has written its own line for the turn it is in."""
        lines.begin_turn(sid, self.lines)
        lines.write(sid, did="Notes page built.", ask=ask, n=n, by=by, root=self.lines)

    def column(self, *sessions, **kw):
        return self.roster(*sessions, **kw)["columns"][0]

    def names(self, column, part):
        return [t["name"] for t in column[part]]


class Pills(Finished):
    def test_a_session_idle_for_two_hours_with_its_handover_read_is_a_pill(self):
        column = self.column(self.finished("a", name="Femi"))
        self.assertEqual(column["sessions"], [])
        self.assertEqual(self.names(column, "pills"), ["Femi"])

    def test_a_column_with_no_finished_session_has_no_pills(self):
        self.assertEqual(self.column(moving("a"))["pills"], [])

    def test_a_pill_is_its_key_its_name_its_idle_time_its_line_and_its_jump(self):
        (pill,) = self.column(self.finished(
            "a", 3 * HOUR, name="Femi", canJump=True, title="Saved-card form"))["pills"]
        self.assertEqual(pill["key"], "fake:a")
        self.assertEqual(pill["name"], "Femi")
        self.assertEqual(pill["line"], "Saved-card form")
        self.assertEqual(pill["jump"], {"via": "pane"})
        self.assertEqual(pill["idle"]["text"], "3 h")
        self.assertAlmostEqual(pill["idle"]["since"], 180, delta=1)

    def test_a_pill_that_has_nowhere_to_go_says_why_before_anyone_clicks(self):
        (pill,) = self.column(self.finished("a"))["pills"]
        self.assertEqual(pill["jump"], {"via": "none", "reason": "no terminal"})

    def test_the_filter_box_finds_a_pill_by_what_it_finds_a_tile_by(self):
        (pill,) = self.column(self.finished("a", name="Femi", title="Saved-card form", prompt="Fix the REFUND flow"))["pills"]
        self.assertTrue(all(word in pill["find"] for word in ("femi", "saved-card form", "refund flow")), pill["find"])

    def test_a_boss_that_is_a_pill_still_says_it_led(self):
        (pill,) = self.column(self.finished("a", boss=True))["pills"]
        self.assertEqual(pill["tags"], ["boss"])

    def test_pills_go_most_recently_stopped_first_and_stay_put(self):
        got = self.column(self.finished("a", 300, name="Old"), self.finished("b", 130, name="New"),
                          self.finished("c", 200, name="Middle"))
        self.assertEqual(self.names(got, "pills"), ["New", "Middle", "Old"])

    def test_a_routine_is_never_a_pill_because_it_is_never_on_the_page(self):
        got = self.roster(moving("m"), self.finished("r", routine="nightly-report", project=None))
        self.assertEqual([c["name"] for c in got["columns"]], ["Maple"])
        self.assertEqual(got["columns"][0]["pills"], [])


class Threshold(Finished):
    def test_two_hours_is_the_default_and_just_under_is_still_a_tile(self):
        got = self.column(self.finished("a", 119, name="Almost"), self.finished("b", 121, name="Done"))
        self.assertEqual(self.names(got, "sessions"), ["Almost"])
        self.assertEqual(self.names(got, "pills"), ["Done"])

    def test_the_config_says_how_long(self):
        self.config = {"finished_after_minutes": 30}
        got = self.column(self.finished("a", 29, name="Almost"), self.finished("b", 31, name="Done"))
        self.assertEqual(self.names(got, "sessions"), ["Almost"])
        self.assertEqual(self.names(got, "pills"), ["Done"])

    def test_a_number_that_is_not_more_than_nothing_is_two_hours(self):
        for bad in (0, -5, "soon", None, True, [120], float("inf")):
            with self.subTest(bad=bad):
                self.config = {"finished_after_minutes": bad}
                got = self.column(self.finished("a", 119, name="Almost"),
                                  self.finished("b", 121, name="Done"))
                self.assertEqual(self.names(got, "sessions"), ["Almost"])
                self.assertEqual(self.names(got, "pills"), ["Done"])

    def test_a_session_whose_stop_is_not_known_is_never_finished(self):
        # No moment to count from, so no idle time and nothing to call forgotten.
        s = session("a", status="idle", updatedAt=0, name="Mystery")
        self.read(s)
        got = self.column(s)
        self.assertEqual(self.names(got, "sessions"), ["Mystery"])
        self.assertEqual(got["pills"], [])


class CountedInNothing(Finished):
    def test_a_project_with_only_pills_is_all_idle(self):
        got = self.column(self.finished("a"), self.finished("b"))
        self.assertEqual((got["state"], got["sessions"]), ("idle", []))
        self.assertEqual(got["summary"], {"moving": 0, "stuck": 0, "idle": 0})

    def test_pills_do_not_make_a_project_look_busy(self):
        got = self.column(self.finished("a"), self.finished("b"), moving("m"))
        self.assertEqual(got["summary"], {"moving": 1, "stuck": 0, "idle": 0})
        self.assertEqual(got["state"], "moving")

    def test_pills_stay_out_of_the_summary_so_the_tiles_alone_make_it(self):
        got = self.column(self.finished("a"), idle("b"), hung("h", quiet=14.0))
        self.assertEqual(got["summary"], {"moving": 0, "stuck": 1, "idle": 1})

    def test_pills_are_in_none_of_the_headers_counts(self):
        got = self.roster(self.finished("a"), self.finished("b", project="orchard"),
                          moving("m"), waiting("w", asking=asks()))
        self.assertEqual(got["counts"], {"needs": 1, "otherStuck": 0, "moving": 1})
        self.assertEqual({t["key"] for c in got["columns"] for t in c["sessions"]}, {"fake:m", "fake:w"})

    def test_a_card_whose_only_session_is_a_pill_is_not_hidden(self):
        got = self.roster(self.finished("a", name="Femi"))
        self.assertEqual([c["name"] for c in got["columns"]], ["Maple"])
        self.assertEqual(self.names(got["columns"][0], "pills"), ["Femi"])


class KeepsATile(Finished):
    """Whatever it has been idle for, it is a full tile while anything is left
    for the person."""

    def tiles(self, *sessions):
        return self.names(self.column(*sessions), "sessions")

    def test_an_unread_handover_keeps_a_full_tile_however_old(self):
        self.assertEqual(self.tiles(self.stopped("a", 30 * 24 * HOUR, name="Old")), ["Old"])

    def test_things_left_for_you_keep_a_full_tile_however_old(self):
        self.line("a", ask="", n=2)
        self.assertEqual(self.tiles(self.finished("a", 5 * HOUR, name="Left")), ["Left"])

    def test_one_thing_a_guess_found_in_its_last_words_keeps_a_full_tile_too(self):
        # `n` is the ticket's word: a count above nothing, however it was read.
        got = self.finished("a", 5 * HOUR, name="Asked", said="Done. Should I push this to the remote?")
        self.assertEqual(self.tiles(got), ["Asked"])

    def test_an_open_question_keeps_a_full_tile(self):
        s = waiting("a", name="Asking", asking=asks(), updatedAt=ago(5 * HOUR))
        self.read(s)
        self.assertEqual(self.tiles(s), ["Asking"])

    def test_an_error_keeps_a_full_tile(self):
        s = self.finished("a", 5 * HOUR, name="Broken", failure=failure("error"))
        self.assertEqual(self.tiles(s), ["Broken"])

    def test_a_rate_limit_keeps_a_full_tile(self):
        s = self.finished("a", 5 * HOUR, name="Held", failure=failure("limit"))
        self.assertEqual(self.tiles(s), ["Held"])

    def test_a_job_it_is_waiting_on_keeps_a_full_tile(self):
        s = self.finished("a", 5 * HOUR, name="Waiting", bgTasks=[{"label": "watch", "since": 3.0}])
        self.assertEqual(self.tiles(s), ["Waiting"])

    def test_a_busy_session_is_a_tile_whatever_its_stop_was(self):
        s = session("a", status="busy", updatedAt=ago(5 * HOUR), quietFor=0.1, name="Busy")
        self.read(s)
        self.assertEqual(self.tiles(s), ["Busy"])


class BackToATile(Finished):
    """Any sign of life makes a pill a tile again, with nothing for you to do."""

    def test_a_prompt_turns_a_pill_back_into_a_tile(self):
        pill = self.finished("a", 5 * HOUR, name="Femi")
        self.assertEqual(self.names(self.column(pill), "pills"), ["Femi"])
        woke = {**pill, "status": "busy", "quietFor": 0.1}
        got = self.column(woke)
        self.assertEqual((self.names(got, "sessions"), got["pills"]), (["Femi"], []))

    def test_a_new_write_turns_a_pill_back_into_a_tile(self):
        # The registry has not caught up and still says it stopped five hours
        # ago; the transcript was written to a minute ago.
        pill = self.finished("a", 5 * HOUR, name="Femi", quietFor=300.0)
        self.assertEqual(self.names(self.column(pill), "pills"), ["Femi"])
        got = self.column({**pill, "quietFor": 1.0})
        self.assertEqual((self.names(got, "sessions"), got["pills"]), (["Femi"], []))

    def test_a_write_in_the_last_half_hour_that_a_provider_counts_is_a_sign_of_life(self):
        strip = [0] * 30
        pill = self.finished("a", 5 * HOUR, name="Femi", writes=strip)
        self.assertEqual(self.names(self.column(pill), "pills"), ["Femi"])
        strip[12] = 3
        got = self.column({**pill, "writes": strip})
        self.assertEqual((self.names(got, "sessions"), got["pills"]), (["Femi"], []))

    def test_a_write_a_provider_counts_is_a_sign_of_life_only_for_as_long_as_it_is_recent(self):
        # The strip is per minute, oldest first: slot 29 is this minute.
        self.config = {"finished_after_minutes": 10}
        old, recent = [0] * 30, [0] * 30
        old[5], recent[26] = 2, 2                       # 24 minutes ago, 3 minutes ago
        got = self.column(self.finished("a", 5 * HOUR, name="Quiet", writes=old),
                          self.finished("b", 5 * HOUR, name="Writing", writes=recent))
        self.assertEqual((self.names(got, "sessions"), self.names(got, "pills")), (["Writing"], ["Quiet"]))
        self.assertAlmostEqual(got["pills"][0]["idle"]["since"], 24, delta=1)

    def test_a_stuck_kind_turns_a_pill_back_into_a_tile(self):
        pill = self.finished("a", 5 * HOUR, name="Femi")
        for extra in ({"failure": failure("error")}, {"failure": failure("limit")},
                      {"bgTasks": [{"label": "watch", "since": 3.0}]}):
            with self.subTest(extra=sorted(extra)):
                got = self.column({**pill, **extra})
                self.assertEqual((self.names(got, "sessions"), got["pills"]), (["Femi"], []))

    def test_a_session_that_stops_again_has_a_new_handover_and_is_a_tile_until_that_is_read(self):
        pill = self.finished("a", 5 * HOUR, name="Femi")
        again = {**pill, "updatedAt": ago(2), "said": "Second round done."}
        got = self.column(again)
        self.assertEqual((self.names(got, "sessions"), got["pills"]), (["Femi"], []))

    def test_it_shrinks_again_after_the_next_two_hours_idle(self):
        stamp = ago(121)
        again = session("a", status="idle", updatedAt=stamp, name="Femi")
        fleet.mark_seen("fake:a", {"updatedAt": ago(300)})          # the first stop, long read
        self.assertEqual(self.names(self.column(again), "sessions"), ["Femi"])
        fleet.mark_seen("fake:a", again)                              # the second, read now
        self.assertEqual(self.names(self.column(again), "pills"), ["Femi"])

    def test_the_card_goes_from_all_idle_to_moving_and_back_with_the_session(self):
        pill = self.finished("a", 5 * HOUR)
        self.assertEqual(self.column(pill)["state"], "idle")
        self.assertEqual(self.column({**pill, "status": "busy", "quietFor": 0.1})["state"], "moving")
        self.assertEqual(self.column(pill)["state"], "idle")


class Handover(Finished):
    """A session that has told you something you have not read stays a tile,
    with what it said on it."""

    def test_an_unread_handover_is_on_the_tile_in_the_sessions_words(self):
        tile = self.tile(self.stopped("a", 5 * HOUR, said="Search index rebuilt; the docs page links to it."))
        self.assertEqual((tile["unread"], tile["handover"]),
                         (True, "Search index rebuilt; the docs page links to it."))

    def test_once_read_it_is_gone_from_the_tile(self):
        s = self.stopped("a", 5 * HOUR, said="Search index rebuilt.")
        self.read(s)
        # Pinned open, so that there is a tile to look at: read, it would be a pill.
        finished.pin("fake:a", True)
        tile = self.tile(s)
        self.assertEqual((tile["unread"], tile["handover"]), (False, ""))

    def test_a_busy_session_has_no_handover_to_read_yet(self):
        s = session("a", status="busy", updatedAt=ago(5 * HOUR), quietFor=0.1, said="Last turn's words.")
        tile = self.tile(s)
        self.assertEqual((tile["unread"], tile["handover"]), (False, ""))

    def test_a_session_with_nothing_to_say_has_an_unread_handover_with_no_words(self):
        tile = self.tile(self.stopped("a", 5 * HOUR))
        self.assertEqual((tile["unread"], tile["handover"]), (True, ""))

    def test_markup_in_a_handover_is_carried_as_text_for_the_page_to_print_as_text(self):
        # R7: the roster never makes markup; the page sets text as text.
        said = '<img src=x onerror="alert(1)"> done'
        self.assertEqual(self.tile(self.stopped("a", 5 * HOUR, said=said))["handover"], said)


class OldMarks(Finished):
    """R19. The seen marks the block view left behind say a row was clicked, and
    the old row never put what the session said in front of you. They keep the
    chime and the ready flag as they were; they do not finish a session."""

    def legacy(self, sid="a", minutes=5 * HOUR, **over):
        """An idle session whose only mark is the block view's: seen.json, and
        no read mark of the overview's."""
        s = self.stopped(sid, minutes, **over)
        seen.mark(f"fake:{sid}", s["updatedAt"])
        return s

    def test_a_session_the_block_view_marked_seen_is_not_a_pill_before_its_handover_is_read(self):
        s = self.legacy("a", name="Femi", said="Release notes drafted.")
        got = self.column(s)
        self.assertEqual((self.names(got, "sessions"), got["pills"]), (["Femi"], []))

    def test_it_shows_the_handover_it_never_showed_before(self):
        tile = self.tile(self.legacy("a", said="Release notes drafted."))
        self.assertEqual((tile["unread"], tile["handover"]), (True, "Release notes drafted."))

    def test_the_chime_still_reads_the_old_mark_as_seen(self):
        got = self.roster(self.legacy("a"))
        self.assertIsNone(got["blocks"][0]["members"][0]["flag"])

    def test_the_first_look_in_the_overview_finishes_it(self):
        s = self.legacy("a", name="Femi")
        fleet.mark_seen("fake:a", s)
        self.assertEqual(self.names(self.column(s), "pills"), ["Femi"])

    def test_an_old_mark_for_an_earlier_stop_counts_for_nothing_either_way(self):
        s = self.stopped("a", 5 * HOUR)
        seen.mark("fake:a", s["updatedAt"] - 1000)
        self.assertEqual(self.column(s)["pills"], [])

    def test_the_read_mark_is_for_the_stop_it_was_made_at(self):
        # You read the handover of an earlier stop of the same session.
        s = self.stopped("a", 5 * HOUR)
        fleet.mark_seen("fake:a", {"updatedAt": s["updatedAt"] - 1000})
        self.assertEqual(self.column(s)["pills"], [])

    def test_a_chime_mark_alone_never_finishes_a_session_whatever_wrote_it(self):
        # What the page cannot tell: a jump that failed used to write this too.
        seen.mark("fake:a", self.stopped("a", 5 * HOUR)["updatedAt"])
        self.assertEqual(self.column(self.stopped("a", 5 * HOUR))["pills"], [])

    def test_the_old_view_and_the_overview_agree_the_session_is_read_after_one_click(self):
        s = self.stopped("a", 5 * HOUR)
        fleet.mark_seen("fake:a", s)
        self.assertFalse(seen.ready("fake:a", s["updatedAt"], seen.load()))


class Pinned(Finished):
    """A pill pinned open is a full tile until you unpin it or the session closes."""

    def pin(self, sid, on=True):
        finished.pin(f"fake:{sid}", on)

    def test_a_pinned_pill_is_a_full_tile(self):
        s = self.finished("a", 5 * HOUR, name="Femi")
        self.pin("a")
        got = self.column(s)
        self.assertEqual((self.names(got, "sessions"), got["pills"]), (["Femi"], []))
        self.assertTrue(got["sessions"][0]["pinned"])

    def test_a_tile_nobody_pinned_says_it_is_not(self):
        self.assertFalse(self.tile(moving("a"))["pinned"])

    def test_a_pinned_idle_session_counts_as_an_ordinary_idle_tile(self):
        s = self.finished("a", 5 * HOUR)
        self.pin("a")
        got = self.roster(s)
        column = got["columns"][0]
        self.assertEqual((column["summary"], column["state"]), ({"moving": 0, "stuck": 0, "idle": 1}, "idle"))
        self.assertEqual(got["counts"], {"needs": 0, "otherStuck": 0, "moving": 0})
        self.assertIsNone(column["sessions"][0]["counted"])

    def test_the_pin_survives_polls(self):
        s = self.finished("a", 5 * HOUR, name="Femi")
        self.pin("a")
        for _ in range(3):
            self.assertEqual(self.names(self.column(s), "sessions"), ["Femi"])

    def test_the_pin_survives_a_poll_that_still_finds_the_session(self):
        s = self.finished("a", 5 * HOUR, name="Femi")
        self.pin("a")
        self.roster(s)
        finished.forget({"fake:a"}, answered={"fake"})
        self.assertEqual(self.names(self.column(s), "sessions"), ["Femi"])

    def test_the_pin_survives_a_poll_that_missed_the_provider(self):
        s = self.finished("a", 5 * HOUR, name="Femi")
        self.pin("a")
        finished.forget(set(), answered=set())
        self.assertEqual(self.names(self.column(s), "sessions"), ["Femi"])

    def test_the_pin_ends_with_the_session(self):
        s = self.finished("a", 5 * HOUR, name="Femi")
        self.pin("a")
        finished.forget(set(), answered={"fake"})            # the poll that no longer lists it
        self.assertEqual(finished.load()["pinned"], [])
        # Resumed later under the same id it is not pinned, and what you read
        # of it before it closed is forgotten with it, as the seen mark is.
        got = self.column(s)
        self.assertEqual((self.names(got, "sessions"), got["pills"]), (["Femi"], []))
        self.assertFalse(got["sessions"][0]["pinned"])

    def test_unpinning_lets_it_shrink_again(self):
        s = self.finished("a", 5 * HOUR, name="Femi")
        self.pin("a")
        self.pin("a", False)
        self.assertEqual(self.names(self.column(s), "pills"), ["Femi"])

    def test_a_pin_holds_the_session_open_whatever_wakes_it_or_not(self):
        s = self.finished("a", 5 * HOUR, name="Femi")
        self.pin("a")
        woke = {**s, "status": "busy", "quietFor": 0.1}
        self.assertEqual(self.names(self.column(woke), "sessions"), ["Femi"])
        self.assertEqual(self.names(self.column(s), "sessions"), ["Femi"])

    def test_pinning_one_session_leaves_the_others_to_shrink(self):
        a, b = self.finished("a", 5 * HOUR, name="Femi"), self.finished("b", 5 * HOUR, name="Odile")
        self.pin("a")
        got = self.column(a, b)
        self.assertEqual((self.names(got, "sessions"), self.names(got, "pills")), (["Femi"], ["Odile"]))


if __name__ == "__main__":
    unittest.main()
