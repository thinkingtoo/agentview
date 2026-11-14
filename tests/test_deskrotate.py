"""The press path reads a bounded log: `merge-desk.log` is rotated past `desk.MAX_LOG`, and the records the
desk still asks about are carried into the new log, so `desk status`, `recover()` and the press answer as before.

Runs in this process with `XDG_STATE_HOME` and `XDG_RUNTIME_DIR` under a throwaway directory and
`deskwatch.gh` replaced by a function that answers from a dict: never the real GitHub, never the real state folder.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import desk
import deskfile
import deskwatch

SHA = "ead9a1f" + "0" * 33
SHA2 = "b" * 40
MERGED_AS = "41678e3" + "1" * 33
STAMP = "2026-11-14T02:00:00+0100"
BULK = ["x" * 100] * 200        # about 20 KB of raw What-ships lines, as a hand-over of a deploying repo keeps


SAVED = (desk.MAX_LOG, deskwatch.gh, deskwatch.GRACE, deskwatch.log.error)


def restore():
    desk.MAX_LOG, deskwatch.gh, deskwatch.GRACE, deskwatch.log.error = SAVED
    desk._floor = 0


def setUpModule():
    global _runtime
    _runtime = tempfile.mkdtemp()
    os.environ["XDG_RUNTIME_DIR"] = _runtime


def tearDownModule():
    os.environ.pop("XDG_RUNTIME_DIR", None)
    shutil.rmtree(_runtime, True)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = str(self.tmp / "state")
        self.addCleanup(lambda: os.environ.pop("XDG_STATE_HOME") if old is None else os.environ.__setitem__("XDG_STATE_HOME", old))
        self.addCleanup(restore)
        desk._floor = 0
        deskwatch.GRACE = 0
        deskwatch.log.error = lambda *a, **k: None
        self.prs = {}
        deskwatch.gh = self.fake_gh
        self.log = desk.log_path()
        self.log.parent.mkdir(parents=True)

    def fake_gh(self, *args):
        repo, n = args[args.index("-R") + 1], args[2]
        pr = self.prs.get(f"{repo}#{n}")
        return (0, json.dumps(pr)) if pr else (1, "Could not resolve to a PullRequest")

    def put(self, event, k, **fields):
        with open(self.log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": STAMP, "event": event, "key": k, **fields}) + "\n")

    def lines(self):
        return self.log.read_text(encoding="utf-8").count("\n")

    def archives(self):
        return sorted(self.log.parent.glob(desk.LOG + ".*"))

    def page(self, k, pinned):
        repo, n = k.rpartition("#")[::2]
        block = desk.item_block(repo, n, "t", "merge", "", pinned, "main", None, "a session", "2026-11-14 02:00", [])
        with deskfile.locked():
            deskfile.put_item(k, block)

    def story(self):
        """A log with every kind of key: waiting, being pressed, merged, refused (on the page), withdrawn, tidied."""
        self.put("ready", "o/r#1", pinned=SHA, ships=BULK, base="main", by="a")
        self.put("pressing", "o/r#1", pinned=SHA)
        self.put("ready", "o/r#2", pinned=SHA, ships=BULK, base="main", by="a")
        self.put("ready", "o/r#3", pinned=SHA, ships=BULK, base="main", by="a")
        self.put("pressing", "o/r#3", pinned=SHA)
        self.put("merged", "o/r#3", sha=MERGED_AS)
        self.put("ready", "o/r#4", pinned=SHA, ships=BULK, base="main", by="a")
        self.put("pressing", "o/r#4", pinned=SHA)
        self.put("refused", "o/r#4", why="GitHub says CONFLICTING")
        self.put("ready", "o/r#5", pinned=SHA, ships=BULK, base="main", by="a")
        self.put("withdrawn", "o/r#5")
        self.put("ready", "o/r#6", pinned=SHA, ships=BULK, base="main", by="a")
        self.put("refused", "o/r#6", why="x")
        self.put("tidied", "o/r#6", was="refused")
        self.put("installed", "install:tool", sha=SHA)
        self.page("o/r#4", SHA)
        self.prs["o/r#1"] = {"state": "OPEN", "mergeable": "MERGEABLE", "headRefOid": SHA, "mergeCommit": None, "baseRefName": "main"}

    def filler(self, n=60):
        for i in range(100, 100 + n):
            self.put("ready", f"o/r#{i}", pinned=SHA2, ships=BULK, base="main", by="a")
            self.put("withdrawn", f"o/r#{i}")

    def answers(self):
        keys = [f"o/r#{i}" for i in range(1, 7)] + ["install:tool"]
        return {"all": desk.status_all()[:7], "status": [desk.status_line(k) for k in keys],
                "last": [(r["at"], r["event"], r.get("pinned"), r.get("why")) if r else None
                         for r in map(deskwatch.last_event, keys)],
                "ship": [bool(deskwatch.handed_over(k, SHA)) for k in keys if k in LIVE],
                "on": [deskscan_on(k) for k in keys + ["o/r#999"]]}


LIVE = {"o/r#1", "o/r#2", "o/r#4"}      # a press can only ask about an item that waits, is pressed, or was refused on the page


def deskscan_on(k):
    import deskscan
    with deskfile.locked():
        return deskscan.on_desk(k)


class Rotation(Case):
    def test_a_poll_of_a_50_mb_log_reads_a_bounded_amount(self):
        self.story()
        before = self.lines()
        self.filler(2400)
        self.assertGreater(self.log.stat().st_size, 50_000_000)
        read = []
        real = desk._read_log
        desk._read_log = lambda: read.append(len(real())) or real()
        try:
            for _ in range(3):
                deskwatch.recover()
        finally:
            desk._read_log = real
        self.assertTrue(read and max(read) <= desk.MAX_LOG, read)
        self.assertLessEqual(self.log.stat().st_size, desk.MAX_LOG)
        self.assertEqual(sum(p.read_text(encoding="utf-8").count("\n") for p in self.archives()), before + 4800)

    def test_status_and_press_answers_are_the_same_after_a_rotation(self):
        self.story()
        self.filler(60)
        desk.MAX_LOG = 10 ** 9
        before = self.answers()
        size = self.log.stat().st_size
        desk.MAX_LOG = size // 2
        self.assertEqual(self.answers(), before)
        self.assertEqual(len(self.archives()), 1)
        self.assertLess(self.log.stat().st_size, size)

    def test_a_press_that_began_before_the_rotation_is_settled_as_before(self):
        for merged in (True, False):
            with self.subTest(merged=merged):
                self.setUp()
                self.story()
                self.filler(60)
                if merged:
                    self.prs["o/r#1"] = {"state": "MERGED", "mergeable": "UNKNOWN", "headRefOid": SHA,
                                         "mergeCommit": {"oid": MERGED_AS}, "baseRefName": "main"}
                desk.MAX_LOG = self.log.stat().st_size // 2
                deskwatch.recover()
                self.assertEqual(len(self.archives()), 1)
                last = deskwatch.last_event("o/r#1")
                self.assertEqual(last["event"], "merged" if merged else "refused")
                self.assertEqual(desk.status_line("o/r#1").split(": ")[1].split(" ")[0].rstrip(":"), "merged" if merged else "refused")
                deskwatch.recover()
                self.assertEqual(deskwatch.last_event("o/r#1"), last)

    def test_the_hand_over_of_a_waiting_item_survives_so_the_press_can_check_what_ships(self):
        self.story()
        self.filler(60)
        desk.MAX_LOG = self.log.stat().st_size // 2
        desk.history()
        for k in ("o/r#2", "o/r#1", "o/r#4"):     # waiting, pressing, refused and still on the page
            self.assertIsNotNone(deskwatch.handed_over(k, SHA), k)
        self.assertIsNone(deskwatch.handed_over("o/r#5", SHA))      # withdrawn and off the page: only its last record is kept
        self.assertEqual(desk.status_line("o/r#5").split(": ")[1].split(" ")[0], "withdrawn")

    def test_a_key_whose_last_record_is_tidied_keeps_its_last_status_record(self):
        self.story()
        self.filler(60)
        desk.MAX_LOG = self.log.stat().st_size // 2
        self.assertEqual(deskwatch.last_event("o/r#6")["event"], "refused")
        self.assertEqual(desk.history("o/r#6")[-1]["event"], "tidied")

    def test_the_order_of_the_keys_is_kept(self):
        self.story()
        self.filler(60)
        desk.MAX_LOG = 10 ** 9
        keys = [r["key"] for r in desk.history()]
        order = list(dict.fromkeys(keys))
        desk.MAX_LOG = self.log.stat().st_size // 2
        self.assertEqual(list(dict.fromkeys(r["key"] for r in desk.history())), order)

    def test_a_log_that_stays_big_after_a_rotation_is_not_rotated_at_every_poll(self):
        self.story()
        self.filler(60)
        desk.MAX_LOG = 100                       # smaller than anything that must be carried
        for _ in range(4):
            desk.history()
        self.assertEqual(len(self.archives()), 1)

    def test_an_unreadable_line_does_not_stop_the_rotation(self):
        self.story()
        with open(self.log, "a", encoding="utf-8") as fh:
            fh.write("{broken\n\n[]\n")
        self.filler(60)
        desk.MAX_LOG = self.log.stat().st_size // 2
        self.assertEqual(desk.status_line("o/r#3").split(": ")[1].split(" ")[0], "merged")
        self.assertEqual(len(self.archives()), 1)

    def test_records_written_after_a_rotation_follow_the_carried_ones(self):
        self.story()
        self.filler(60)
        desk.MAX_LOG = self.log.stat().st_size // 2
        desk.history()
        with deskfile.locked():
            desk.log("pressing", "o/r#2", pinned=SHA)
        self.assertEqual(deskwatch.last_event("o/r#2")["event"], "pressing")
        self.assertIsNotNone(deskwatch.handed_over("o/r#2", SHA))


if __name__ == "__main__":
    unittest.main()
