"""The Merges table (`desktable.py`): its rows, and the tick its button writes on the page.

The desk file is a throwaway one under a private `XDG_STATE_HOME`. Items are handed over through
`deskfile.put_item`, so they carry a record and are pinned like real ones.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import deskfile
import desktable

SHA = "a" * 40


def block(n, rec="merge. Reviewed, clean.", ticked=False, sha=SHA, extra=""):
    return (f"- [{'x' if ticked else ' '}] Merge sweatshop-ai/sheaf#{n}: thing {n}\n"
            f"  - Recommendation: {rec}\n  - Pinned commit: {sha}\n"
            f"  - Handed over by Ciro, 2026-11-13 0{n}:00.\n{extra}")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = {k: os.environ.get(k) for k in ("XDG_STATE_HOME", "XDG_RUNTIME_DIR")}
        os.environ["XDG_STATE_HOME"] = self.tmp
        os.environ["XDG_RUNTIME_DIR"] = self.tmp
        deskfile.path().parent.mkdir(parents=True, exist_ok=True)
        deskfile.path().write_text(deskfile.SKELETON)

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hand(self, n, **kw):
        deskfile.put_item(f"sweatshop-ai/sheaf#{n}", block(n, **kw))


class Rows(Base):
    def test_a_row_carries_number_name_verdict_and_handed_time(self):
        self.hand(1)
        (row,) = desktable.rows()
        self.assertEqual((row["kind"], row["repo"], row["number"], row["name"], row["verdict"], row["why"]),
                         ("Merge", "sweatshop-ai/sheaf", 1, "thing 1", "merge", "Reviewed, clean."))
        self.assertEqual((row["handed"], row["pinned"], row["state"]), ("2026-11-13 01:00", SHA, "waiting"))
        self.assertIsNotNone(row["handed_at"])

    def test_the_four_verdicts(self):
        for n, rec in enumerate(("merge. a", "don't merge. b", "wait. c", "found by the scan, no recommendation yet."), 1):
            self.hand(n, rec=rec)
        rows = sorted(desktable.rows(), key=lambda r: r["number"])
        self.assertEqual([(r["verdict"], r["why"]) for r in rows],
                         [("merge", "a"), ("don't merge", "b"), ("wait", "c"), ("none", "")])

    def test_a_merged_item_is_done_with_its_result(self):
        self.hand(1)
        deskfile.edit(lambda t: deskfile.settle(t, "sweatshop-ai/sheaf#1", "Merged as abcdef1 at 10:00"))
        (row,) = desktable.rows()
        self.assertEqual((row["state"], row["result"]), ("done", "Merged as abcdef1 at 10:00"))

    def test_a_refused_press_shows_its_reason_and_can_be_pressed_again(self):
        self.hand(1)
        deskfile.edit(lambda t: deskfile.settle(t, "sweatshop-ai/sheaf#1", "Not merged: GitHub says CONFLICTING", untick=True))
        (row,) = desktable.rows()
        self.assertEqual((row["state"], row["result"]), ("refused", "Not merged: GitHub says CONFLICTING"))


class Tick(Base):
    def test_tick_writes_the_box_the_watcher_reads(self):
        self.hand(1)
        self.hand(2)
        desktable.tick("sweatshop-ai/sheaf#1", SHA)
        self.assertEqual({i.key: i.ticked for i in deskfile.items()},
                         {"sweatshop-ai/sheaf#1": True, "sweatshop-ai/sheaf#2": False})
        self.assertEqual(desktable.rows()[1]["state"], "pressing")

    def test_a_gone_item_is_404(self):
        with self.assertRaises(desktable.Refused) as got:
            desktable.tick("sweatshop-ai/sheaf#9", SHA)
        self.assertEqual(got.exception.code, 404)

    def test_an_item_handed_over_again_is_refused_and_left_unticked(self):
        self.hand(1)
        self.hand(1, sha="b" * 40)
        with self.assertRaises(desktable.Refused) as got:
            desktable.tick("sweatshop-ai/sheaf#1", SHA)
        self.assertEqual(got.exception.code, 409)
        self.assertFalse(deskfile.items()[0].ticked)

    def test_a_ticked_item_is_not_ticked_twice(self):
        self.hand(1)
        desktable.tick("sweatshop-ai/sheaf#1", SHA)
        before = deskfile.path().read_text()
        with self.assertRaises(desktable.Refused):
            desktable.tick("sweatshop-ai/sheaf#1", SHA)
        self.assertEqual(deskfile.path().read_text(), before)

    def test_an_item_on_the_page_twice_is_refused(self):
        self.hand(1)
        deskfile.path().write_text(deskfile.path().read_text() + block(1))
        with self.assertRaises(desktable.Refused) as got:
            desktable.tick("sweatshop-ai/sheaf#1", SHA)
        self.assertEqual(got.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
