"""The Merges header button's count and the once-a-day ring (`deskring.py`).

The desk file is a throwaway one under a private `XDG_STATE_HOME`; the clock is passed in. The count comes
through `deskfile.items()`, never by reading the file here.
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import deskfile
import deskring

SHA = "a" * 40


def block(n, when, ticked=False):
    return (f"- [{'x' if ticked else ' '}] Merge sweatshop-ai/sheaf#{n}: thing {n}\n"
            f"  - Recommendation: Merge.\n  - Pinned commit: {SHA}\n"
            f"  - Handed over by Ciro, {when}.\n")


def at(text):
    return time.mktime(time.strptime(text, "%Y-%m-%d %H:%M"))


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

    def hand(self, n, when, ticked=False):
        deskfile.put_item(f"sweatshop-ai/sheaf#{n}", block(n, when, ticked))


class Count(Base):
    def test_no_desk_file_is_zero(self):
        deskfile.path().unlink()
        self.assertEqual(deskring.waiting(), 0)

    def test_it_counts_the_items_waiting(self):
        self.hand(1, "2026-11-13 09:00")
        self.hand(2, "2026-11-13 10:00")
        self.assertEqual(deskring.waiting(), 2)

    def test_a_ticked_item_is_no_longer_waiting_for_the_person(self):
        self.hand(1, "2026-11-13 09:00")
        self.hand(2, "2026-11-13 10:00", ticked=True)
        self.assertEqual(deskring.waiting(), 1)


class Ring(Base):
    def test_nothing_waiting_never_rings(self):
        self.assertIsNone(deskring.ring_due(now=at("2026-11-20 12:00")))

    def test_an_item_under_a_day_old_does_not_ring(self):
        self.hand(1, "2026-11-13 09:00")
        self.assertIsNone(deskring.ring_due(now=at("2026-11-14 08:59")))

    def test_the_oldest_item_past_a_day_rings_and_names_the_desk(self):
        self.hand(1, "2026-11-13 09:00")
        self.hand(2, "2026-11-14 07:00")
        text = deskring.ring_due(now=at("2026-11-14 09:01"))
        self.assertIn("merge desk", text.lower())

    def test_it_rings_once_a_day_not_on_every_poll(self):
        self.hand(1, "2026-11-13 09:00")
        self.assertTrue(deskring.ring_due(now=at("2026-11-14 10:00")))
        self.assertIsNone(deskring.ring_due(now=at("2026-11-14 10:30")))
        self.assertIsNone(deskring.ring_due(now=at("2026-11-14 20:00")))

    def test_it_rings_again_the_next_day(self):
        self.hand(1, "2026-11-13 09:00")
        self.assertTrue(deskring.ring_due(now=at("2026-11-14 10:00")))
        self.assertTrue(deskring.ring_due(now=at("2026-11-15 10:00")))

    def test_once_a_day_survives_a_restart(self):
        self.hand(1, "2026-11-13 09:00")
        self.assertTrue(deskring.ring_due(now=at("2026-11-14 10:00")))
        import importlib
        importlib.reload(deskring)      # the service restarted: nothing is kept in memory
        self.assertIsNone(deskring.ring_due(now=at("2026-11-14 11:00")))
        self.assertTrue((Path(self.tmp) / "agentview" / deskring.STAMP).exists())

    def test_an_unreadable_stamp_rings_rather_than_stays_silent(self):
        self.hand(1, "2026-11-13 09:00")
        stamp = Path(self.tmp) / "agentview" / deskring.STAMP
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text("not json")
        self.assertTrue(deskring.ring_due(now=at("2026-11-14 10:00")))

    def test_an_item_with_no_readable_time_is_not_taken_for_old(self):
        deskfile.put_item("sweatshop-ai/sheaf#3", "- [ ] Merge sweatshop-ai/sheaf#3: x\n  - Pinned commit: " + SHA + "\n")
        self.assertIsNone(deskring.ring_due(now=at("2030-01-01 10:00")))


if __name__ == "__main__":
    unittest.main()
