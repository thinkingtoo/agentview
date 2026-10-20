"""Pills over HTTP: the click on one, the pin, and what a poll forgets.

On the server `test_attach.ClickServer` builds: port 0, throwaway stores, a
fake registry behind the real Claude provider, and no terminal anywhere that
a click could reach. A session whose stop is long past, once read, is a pill.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import finished
import jump
import seen
from test_attach import ClickServer, JOB, SID

KEY = f"claude:{SID}"
LONG_AGO = 1790000000000          # a stop far more than two hours back


class Pill(ClickServer):
    def setUp(self):
        super().setUp()
        self.background(statusUpdatedAt=LONG_AGO)

    def read_it(self):
        """You looked at it, as the page's click on a tile without a terminal does:
        with the stop its tile showed."""
        self.assertEqual(self.post({"key": KEY, "stop": LONG_AGO}, path="/api/seen"), (200, {"ok": True}))

    def stop_again(self):
        """The session has stopped again, a minute after the stop the page
        showed: the page's poll is behind the registry."""
        rec = self.cfg / "sessions" / "10.json"
        rec.write_text(json.dumps({**json.loads(rec.read_text()), "statusUpdatedAt": LONG_AGO + 60_000}))

    def keys(self, part):
        return [t["key"] for t in self.column()[part]]

    def marks(self):
        return seen.load(), finished.load()


class Reading(Pill):
    def test_a_session_idle_long_ago_is_a_tile_until_it_is_read_and_a_pill_after(self):
        self.assertEqual((self.keys("sessions"), self.keys("pills")), ([KEY], []))
        self.read_it()
        self.assertEqual((self.keys("sessions"), self.keys("pills")), ([], [KEY]))

    def test_a_pill_of_a_background_session_says_attach(self):
        self.read_it()
        (pill,) = self.column()["pills"]
        self.assertEqual(pill["jump"], {"via": "attach"})


class LookingIsNotReading(Pill):
    """R19, found by the Opus hunt: a handover is read only where it was shown,
    and only the stop the page showed."""

    def test_the_tile_says_which_stop_it_shows(self):
        (tile,) = self.column()["sessions"]
        self.assertEqual((tile["stop"], tile["unread"]), (LONG_AGO, True))

    def test_a_click_that_names_no_stop_does_not_read_the_handover(self):
        # A look that names no stop (a tab from before the overview) posts the key
        # alone: the chime is told, nothing is read.
        self.assertEqual(self.post({"key": KEY}, path="/api/seen"), (200, {"ok": True}))
        self.assertEqual((seen.load().get(KEY), finished.load()["read"]), (LONG_AGO, {}))
        (tile,) = self.column()["sessions"]
        self.assertEqual((tile["key"], tile["unread"], self.keys("pills")), (KEY, True, []))

    def test_a_click_on_a_tile_reads_the_stop_it_showed_and_tells_the_chime_too(self):
        self.read_it()
        self.assertEqual((seen.load().get(KEY), finished.load()["read"]), (LONG_AGO, {KEY: LONG_AGO}))

    def test_a_stop_the_page_never_showed_is_not_read(self):
        # The page showed the stop at LONG_AGO; the session worked and stopped
        # again before the click, with a handover nobody has seen.
        self.stop_again()
        self.assertEqual(self.post({"key": KEY, "stop": LONG_AGO}, path="/api/seen"), (200, {"ok": True}))
        self.assertEqual(finished.load()["read"], {})
        (tile,) = self.column()["sessions"]
        self.assertEqual((tile["unread"], tile["stop"], self.keys("pills")), (True, LONG_AGO + 60_000, []))

    def test_a_stop_that_is_not_a_whole_number_is_refused_and_marks_nothing(self):
        for stop in ("soon", True, 1.5, [LONG_AGO], {"a": 1}):
            with self.subTest(stop=stop):
                self.assertEqual(self.post({"key": KEY, "stop": stop}, path="/api/seen")[0], 400)
        self.assertEqual((seen.load(), finished.load()["read"]), ({}, {}))


class JumpFromAPill(Pill):
    """R4: a failed jump from a pill must not mark anything seen."""

    def test_a_jump_from_a_pill_that_reached_the_terminal_leaves_it_a_pill(self):
        self.read_it()
        status, done = self.post({"key": KEY})
        self.assertEqual((status, done["ok"]), (200, True))
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(self.keys("pills"), [KEY])

    def test_a_failed_jump_from_a_pill_marks_nothing_seen(self):
        self.read_it()
        before = self.marks()
        self.fails = True
        status, done = self.post({"key": KEY})
        self.assertEqual((status, done["ok"], done["reason"]), (200, False, "wezterm cli spawn failed"))
        self.assertEqual(self.marks(), before)
        self.assertEqual(self.keys("pills"), [KEY])

    def test_a_click_that_only_waited_for_a_tab_marks_nothing_either(self):
        self.read_it()
        self.stop_again()
        before = self.marks()
        jump._ATTACHING[JOB] = jump._now() + jump.ATTACH_GRACE
        status, done = self.post({"key": KEY})
        self.assertEqual((status, done["ok"], done["did"]), (200, True, "opening"))
        self.assertEqual((self.marks(), self.opened), (before, []))

    def test_a_session_that_stopped_again_since_the_poll_stays_unread_when_its_jump_fails(self):
        # The pill was read at the stop it shows. By the click the session has
        # stopped again; a jump that reaches nothing has shown you nothing.
        self.read_it()
        self.stop_again()
        before = self.marks()
        self.fails = True
        self.post({"key": KEY})
        self.assertEqual(self.marks(), before)
        self.assertEqual((self.keys("sessions"), self.keys("pills")), ([KEY], []))

    def test_a_session_that_stopped_again_since_the_poll_is_read_when_its_jump_reached_it(self):
        # The same click, when the terminal did come to the front: now it was seen.
        self.read_it()
        self.stop_again()
        self.assertEqual(self.post({"key": KEY})[1]["ok"], True)
        self.assertEqual((self.keys("sessions"), self.keys("pills")), ([], [KEY]))


class Keep(Pill):
    """`POST /api/keep`: pin a pill open as a tile, or let it shrink again."""

    def keep(self, on=True, key=KEY, **kw):
        return self.post({"key": key, "pinned": on}, path="/api/keep", **kw)

    def test_a_pinned_pill_is_a_full_tile_that_says_it_is_pinned(self):
        self.read_it()
        self.assertEqual(self.keep(), (200, {"ok": True, "pinned": True}))
        (tile,) = self.column()["sessions"]
        self.assertEqual((tile["key"], tile["pinned"], self.keys("pills")), (KEY, True, []))

    def test_it_survives_every_poll(self):
        self.read_it()
        self.keep()
        for _ in range(3):
            self.assertEqual((self.keys("sessions"), self.keys("pills")), ([KEY], []))
        self.assertEqual(finished.load()["pinned"], [KEY])

    def test_unpinning_makes_it_a_pill_again(self):
        self.read_it()
        self.keep()
        self.assertEqual(self.keep(False), (200, {"ok": True, "pinned": False}))
        self.assertEqual((self.keys("sessions"), self.keys("pills")), ([], [KEY]))

    def test_it_ends_with_the_session(self):
        self.read_it()
        self.keep()
        for rec in (self.cfg / "sessions").glob("*.json"):
            rec.unlink()
        self.assertEqual(self.roster()["columns"], [])
        self.assertEqual(finished.load()["pinned"], [])

    def test_a_session_that_is_not_alive_cannot_be_pinned(self):
        self.assertEqual(self.keep(key="claude:nobody")[0], 404)
        self.assertEqual(finished.load()["pinned"], [])

    def test_a_request_that_is_not_what_it_expects_is_refused(self):
        for body in ({}, {"key": KEY}, {"key": KEY, "pinned": "yes"}, {"key": 7, "pinned": True},
                     {"key": KEY, "pinned": 1}):
            with self.subTest(body=body):
                self.assertEqual(self.post(body, path="/api/keep")[0], 400)
        self.assertEqual(finished.load()["pinned"], [])

    def test_the_guard_is_todays_a_local_page_with_the_fleet_header(self):
        self.assertEqual(self.keep(headers={"X-Fleet": "0"})[0], 403)
        self.assertEqual(self.keep(headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(finished.load()["pinned"], [])

    def test_pinning_opens_nothing_and_marks_nothing_seen(self):
        before = seen.load()
        self.keep()
        self.assertEqual((self.opened, seen.load()), ([], before))


if __name__ == "__main__":
    unittest.main()
