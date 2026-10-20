"""A track's ETA: measured from the boxes ticked while agentview watched.

The pace file lives in a temp dir; nothing here reads or writes the real
`~/.claude/agentview/pace.json`. Track names are invented.
"""
import datetime
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pace

HOUR, DAY = 3600, 86400
T0 = datetime.datetime(2030, 3, 4, 9, 0).timestamp()     # a Monday


class Eta(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / "pace.json"

    def eta(self, done, total, now):
        return pace.eta("checkout", done, total, now, self.path)

    def test_first_sight_has_no_pace_yet(self):
        got = self.eta(3, 7, T0)
        self.assertEqual(got["text"], "ETA after the next box")
        self.assertIn("no pace yet", got["why"])

    def test_no_box_since_first_sight_is_still_no_pace(self):
        self.eta(3, 7, T0)
        self.assertEqual(self.eta(3, 7, T0 + DAY)["text"], "ETA after the next box")

    def test_the_pace_is_boxes_since_first_sight_over_the_time_since(self):
        self.eta(3, 7, T0)
        got = self.eta(5, 7, T0 + DAY)            # 2 boxes a day, 2 left: one more day
        self.assertEqual(got["text"], "ETA Wed 6")
        self.assertIn("2 boxes in 24 h", got["why"])
        self.assertIn("2 left", got["why"])

    def test_a_track_that_stops_sees_its_estimate_slip(self):
        self.eta(3, 7, T0)
        self.eta(5, 7, T0 + DAY)
        self.assertEqual(self.eta(5, 7, T0 + 3 * DAY)["text"], "ETA Sun 10")   # 2 in 3 days: 3 more

    def test_an_estimate_within_the_day_says_today(self):
        self.eta(1, 3, T0)
        self.assertEqual(self.eta(2, 3, T0 + HOUR)["text"], "ETA today")

    def test_far_off_is_not_a_date(self):
        self.eta(0, 200, T0)
        self.assertEqual(self.eta(1, 200, T0 + DAY)["text"], "ETA over 3 months")

    def test_further_than_a_week_gives_day_and_month(self):
        self.eta(0, 10, T0)
        self.assertEqual(self.eta(1, 10, T0 + DAY)["text"], "ETA 14 Mar")

    def test_an_unticked_box_starts_the_count_again(self):
        self.eta(3, 7, T0)
        self.eta(5, 7, T0 + DAY)
        self.assertEqual(self.eta(4, 7, T0 + 2 * DAY)["text"], "ETA after the next box")
        self.assertEqual(pace.load(self.path)["checkout"], {"since": T0 + 2 * DAY, "done": 4, "last": 4})

    def test_the_file_is_written_only_when_the_count_changes(self):
        self.eta(3, 7, T0)
        self.eta(4, 7, T0 + DAY)
        before = self.path.stat().st_mtime_ns
        self.eta(4, 7, T0 + 2 * DAY)
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_a_broken_file_is_no_history(self):
        self.path.write_text("[not a dict")
        self.assertEqual(self.eta(2, 5, T0)["text"], "ETA after the next box")
        self.path.write_text('{"checkout": {"since": "yesterday", "done": 1}}')
        self.assertEqual(pace.load(self.path), {})

    def test_an_unwritable_place_raises_nothing(self):
        blocked = self.dir / "file"
        blocked.write_text("")
        got = pace.eta("checkout", 1, 2, T0, blocked / "pace.json")
        self.assertEqual(got["text"], "ETA after the next box")


if __name__ == "__main__":
    unittest.main()
