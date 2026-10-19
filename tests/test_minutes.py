"""The strip of per-minute write counts that a provider hands over, checked and added up
in one place: the core believes a strip only if it is thirty whole counts, and a project's
strip is its sessions' added minute by minute."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import minutes


class Strips(unittest.TestCase):
    def test_a_strip_is_thirty_counts_each_a_whole_number_or_none(self):
        for good in ([0] * 30, [3] * 30, [None] * 30, [None, 0, 7] * 10, [10**9] * 30):
            with self.subTest(good=good[:4]):
                self.assertTrue(minutes.is_strip(good))

    def test_anything_else_is_not_one(self):
        for bad in (None, 0, "x" * 30, [0] * 29, [0] * 31, [], (0,) * 30, {i: 0 for i in range(30)},
                    [-1] + [0] * 29, [1.5] + [0] * 29, [True] + [0] * 29, ["1"] + [0] * 29,
                    [[0]] + [0] * 29, [float("nan")] + [0] * 29):
            with self.subTest(bad=repr(bad)[:30]):
                self.assertFalse(minutes.is_strip(bad))

    def test_strips_are_added_minute_by_minute(self):
        self.assertEqual(minutes.added([[1] * 30, [2] * 30, [4] * 30]), [7] * 30)

    def test_a_minute_any_of_them_could_not_see_is_unknown(self):
        one = [1] * 30
        two = [2] * 30
        two[3] = None
        got = minutes.added([one, two])
        self.assertEqual(got[3], None)
        self.assertEqual(got[:3] + got[4:], [3] * 29)

    def test_a_strip_that_is_not_there_is_left_out_and_none_at_all_is_none(self):
        self.assertEqual(minutes.added([None, [5] * 30, None]), [5] * 30)
        self.assertIsNone(minutes.added([None, None]))
        self.assertIsNone(minutes.added([]))

    def test_the_sum_is_a_new_list(self):
        one = [1] * 30
        got = minutes.added([one])
        got[0] = 9
        self.assertEqual(one[0], 1)


if __name__ == "__main__":
    unittest.main()
