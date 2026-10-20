import json, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import log
import dialog_words


def peer(pid, name, status="busy", cwd="/home/alice", started=None):
    return {"pid": pid, "name": name, "status": status, "cwd": cwd,
            "sessionId": f"sid-{pid}", "entrypoint": "cli",
            "startedAt": started or 0}


class Transitions(unittest.TestCase):
    def kinds(self, before, after):
        return [k for k, _ in log.transitions(before, after)]

    def test_a_new_session_is_news(self):
        got = log.transitions({}, {1: peer(1, "Ansgar")})
        self.assertEqual([k for k, _ in got], ["session.seen"])
        self.assertEqual(got[0][1]["name"], "Ansgar")

    def test_a_session_leaving_is_news_with_how_long_it_ran(self):
        import time
        started = (time.time() - 300) * 1000
        got = log.transitions({1: peer(1, "Ansgar", started=started)}, {})
        self.assertEqual(got[0][0], "session.gone")
        self.assertAlmostEqual(got[0][1]["ranFor"], 300, delta=5)

    def test_status_changes_are_recorded_both_ways(self):
        before = {1: peer(1, "Vera", "busy")}
        after = {1: peer(1, "Vera", "idle")}
        (kind, fields), = log.transitions(before, after)
        self.assertEqual((kind, fields["from"], fields["to"]), ("status", "busy", "idle"))
        (kind, fields), = log.transitions(after, before)
        self.assertEqual((fields["from"], fields["to"]), ("idle", "busy"))

    def test_a_heartbeat_alone_says_nothing(self):
        # `updatedAt` moves constantly. Logging it would bury everything that
        # actually happened under a line every two seconds.
        before = {1: {**peer(1, "Vera"), "updatedAt": 1}}
        after = {1: {**peer(1, "Vera"), "updatedAt": 2}}
        self.assertEqual(log.transitions(before, after), [])

    def test_a_session_moving_house_is_recorded(self):
        got = self.kinds({1: peer(1, "Vera", cwd="/a")}, {1: peer(1, "Vera", cwd="/b")})
        self.assertEqual(got, ["cwd"])


def waiting_peer(pid, name, needs=None, waiting_for="dialog open", status="waiting"):
    got = {**peer(pid, name, status), "waitingFor": waiting_for}
    if needs is not None:
        got["needs"] = needs
    return got


class Needs(unittest.TestCase):
    """Ticket 15: how many `dialog open` openings carry a `needs` text, per kind.
    The log writes the kind, a short label, and never the words: they may be
    a classifier's reading of a transcript."""
    def events(self, before, after):
        return [(k, f) for k, f in log.transitions(before, after) if k == "needs"]

    def test_a_dialog_that_opens_with_a_needs_text_writes_its_kind_and_not_its_words(self):
        words = dialog_words.ULTRAPLAN
        before = {1: waiting_peer(1, "Vera")}
        after = {1: waiting_peer(1, "Vera", words)}
        (kind, fields), = self.events(before, after)
        self.assertEqual((fields["from"], fields["to"], fields["name"], fields["pid"]),
                         (None, "ultraplan", "Vera", 1))
        self.assertNotIn("ultraplan in the cloud", json.dumps(log.transitions(before, after)))

    def test_each_text_claude_code_writes_has_its_kind_and_any_other_is_other(self):
        for words, kind in ((dialog_words.USAGE, "usage"), (dialog_words.RETRY, "fallback"),
                            (dialog_words.BILLING, "billing"), (dialog_words.AUTO_MODE, "auto mode"),
                            ("Invented: a sentence about the transcript of a session", "other")):
            with self.subTest(kind=kind):
                (_, fields), = self.events({1: waiting_peer(1, "Vera")}, {1: waiting_peer(1, "Vera", words)})
                self.assertEqual(fields["to"], kind)

    def test_the_words_never_reach_any_event(self):
        words = "Invented: a sentence about the transcript of a session"
        got = log.transitions({1: waiting_peer(1, "Vera")}, {1: waiting_peer(1, "Vera", words)})
        self.assertNotIn("sentence about", json.dumps(got))
        got = log.transitions({}, {1: waiting_peer(1, "Vera", words)})
        self.assertNotIn("sentence about", json.dumps(got))

    def test_a_dialog_already_open_when_the_session_is_first_seen_is_counted_once(self):
        # A restart of the watcher sees every session as new. The dialog is
        # open now whether or not anyone saw it open, and the count is of dialogs.
        (kind, fields), = self.events({}, {1: waiting_peer(1, "Vera", dialog_words.BILLING)})
        self.assertEqual((fields["from"], fields["to"], fields["pid"]), (None, "billing", 1))
        self.assertEqual(self.events({}, {1: waiting_peer(1, "Vera")}), [])
        self.assertEqual(self.events({}, {1: peer(1, "Vera", "busy")}), [])

    def test_the_dialog_closing_writes_the_kind_going_away(self):
        words = dialog_words.USAGE
        (_, fields), = self.events({1: waiting_peer(1, "Vera", words)}, {1: waiting_peer(1, "Vera", status="busy", waiting_for=None)})
        self.assertEqual((fields["from"], fields["to"]), ("usage", None))

    def test_a_menu_the_person_opened_has_no_kind_and_writes_no_needs_event(self):
        self.assertEqual(self.events({1: peer(1, "Vera", "busy")}, {1: waiting_peer(1, "Vera")}), [])

    def test_it_reads_back_as_a_kind_coming_and_going(self):
        at = "2026-10-19T10:00:00.000"
        self.assertIn("None -> usage", log.render({"at": at, "kind": "needs", "name": "Vera", "from": None, "to": "usage"}))
        self.assertIn("usage -> None", log.render({"at": at, "kind": "needs", "name": "Vera", "from": "usage", "to": None}))

    def test_a_needs_text_beside_no_dialog_is_not_a_dialog(self):
        # The classifier writes `needs` for a session that is not in a dialog.
        words = dialog_words.ULTRAPLAN
        for rec in ({**peer(1, "Vera", "idle"), "needs": words},
                    waiting_peer(1, "Vera", words, waiting_for="permission prompt"),
                    waiting_peer(1, "Vera", words, waiting_for="input needed"),
                    waiting_peer(1, "Vera", words, status="busy")):
            with self.subTest(waiting_for=rec.get("waitingFor")):
                self.assertEqual(self.events({1: peer(1, "Vera")}, {1: rec}), [])

    def test_the_same_kind_staying_open_says_nothing_more(self):
        words = dialog_words.ULTRAPLAN
        self.assertEqual(self.events({1: waiting_peer(1, "Vera", words)},
                                     {1: {**waiting_peer(1, "Vera", words), "updatedAt": 9}}), [])

    def test_a_needs_text_that_is_not_text_is_no_text(self):
        for value in (7, True, ["x"], {"a": 1}, "", "   "):
            with self.subTest(value=value):
                self.assertEqual(self.events({1: waiting_peer(1, "Vera")}, {1: waiting_peer(1, "Vera", value)}), [])


class Writing(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.old, log.LOG = log.LOG, self.dir / "events.jsonl"

    def tearDown(self):
        log.LOG = self.old

    def test_an_event_is_one_json_line(self):
        log.event("status", name="Vera", **{"from": "busy", "to": "idle"})
        rec = json.loads(log.LOG.read_text().strip())
        self.assertEqual(rec["kind"], "status")
        self.assertEqual(rec["to"], "idle")
        self.assertIn("at", rec)

    def test_the_same_error_is_written_once_not_every_poll(self):
        log._seen_errors.clear()
        for _ in range(5):
            log.error("watch", OSError("no such file"))
        self.assertEqual(len(log.LOG.read_text().strip().splitlines()), 1)

    def test_a_fast_operation_writes_nothing(self):
        with log.timed("roster", 5.0):
            pass
        self.assertFalse(log.LOG.exists())

    def test_a_slow_one_writes_its_own_line(self):
        import time
        with log.timed("roster", 0.01, sessions=9):
            time.sleep(0.02)
        rec = json.loads(log.LOG.read_text().strip())
        self.assertEqual((rec["kind"], rec["op"], rec["sessions"]), ("slow", "roster", 9))

    def test_an_exception_inside_a_timed_block_is_logged_and_re_raised(self):
        log._seen_errors.clear()
        with self.assertRaises(ValueError):
            with log.timed("roster", 5.0):
                raise ValueError("bad line")
        rec = json.loads(log.LOG.read_text().strip())
        self.assertEqual(rec["kind"], "error")
        self.assertIn("bad line", rec["error"])

    def test_the_file_rotates_instead_of_growing_forever(self):
        log.MAX_BYTES, old = 200, log.MAX_BYTES
        try:
            for i in range(40):
                log.event("status", name=f"session-{i}", note="x" * 40)
            self.assertTrue(log.LOG.with_suffix(".jsonl.1").exists())
            self.assertLess(log.LOG.stat().st_size, 2000)
        finally:
            log.MAX_BYTES = old

    def test_reading_back_filters_by_kind_and_by_who(self):
        log.event("status", name="Vera", **{"from": "busy", "to": "idle"})
        log.event("action", what="jump", asked={"pid": 7})
        log.event("status", name="Elke", **{"from": "idle", "to": "busy"})
        self.assertEqual(len(log.read(log.LOG, kinds=("status",))), 2)
        self.assertEqual(len(log.read(log.LOG, who="Vera")), 1)
        self.assertEqual(len(log.read(log.LOG, limit=1)), 1)

    def test_every_event_renders_on_one_line(self):
        log.event("session.gone", name="Ansgar", pid=3, ranFor=214)
        line, = [log.render(r) for r in log.read(log.LOG)]
        self.assertIn("Ansgar", line)
        self.assertIn("ranFor=214", line)
        self.assertNotIn("\n", line)


if __name__ == "__main__":
    unittest.main()


class Flags(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.old, log.LOG = log.LOG, self.dir / "events.jsonl"
        log._flags.clear()

    def tearDown(self):
        log.LOG = self.old

    def roster(self, **flags):
        return [{"key": sid, "id": sid, "name": sid.upper(), "flag": f, "blocked": False}
                for sid, f in flags.items()]

    def test_the_first_sight_of_a_session_is_not_a_transition(self):
        # It may have been stuck for an hour before the page was opened.
        # Saying it "became" stuck now would date the problem wrongly.
        log.note_roster(self.roster(a="stuck"))
        self.assertFalse(log.LOG.exists())

    def test_becoming_stuck_and_recovering_are_both_written(self):
        log.note_roster(self.roster(a=None))
        log.note_roster(self.roster(a="stuck"))
        log.note_roster(self.roster(a=None))
        got = [(r["from"], r["to"]) for r in log.read(log.LOG, kinds=("flag",))]
        self.assertEqual(got, [(None, "stuck"), ("stuck", None)])

    def test_a_poll_where_nothing_moved_writes_nothing(self):
        log.note_roster(self.roster(a="waiting", b=None))
        log.note_roster(self.roster(a="waiting", b=None))
        self.assertEqual(log.read(log.LOG, kinds=("flag",)), [])
