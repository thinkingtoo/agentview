import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import log


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


class Writing(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
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
        self.old, log.LOG = log.LOG, self.dir / "events.jsonl"
        log._flags.clear()

    def tearDown(self):
        log.LOG = self.old

    def roster(self, **flags):
        return [{"members": [{"sessionId": sid, "name": sid.upper(), "stuck": f}
                             for sid, f in flags.items()]}]

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
