import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import seen


class Seen(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "seen.json"

    def test_a_session_you_have_never_looked_at_is_ready(self):
        self.assertTrue(seen.ready("s1", 100, seen.load(self.path)))

    def test_looking_at_it_settles_it(self):
        seen.mark("s1", 100, self.path)
        self.assertFalse(seen.ready("s1", 100, seen.load(self.path)))

    def test_stopping_again_makes_it_ready_again(self):
        # The mark is the moment it stopped, not the session. A new answer
        # carries a new `statusUpdatedAt`, so it comes back on its own --
        # there is nothing to clear and nothing that can go stale.
        seen.mark("s1", 100, self.path)
        self.assertTrue(seen.ready("s1", 200, seen.load(self.path)))

    def test_a_session_that_never_stopped_is_not_ready(self):
        self.assertFalse(seen.ready("s1", None, seen.load(self.path)))

    def test_marks_survive_being_written_and_read(self):
        seen.mark("s1", 100, self.path)
        seen.mark("s2", 300, self.path)
        self.assertEqual(seen.load(self.path), {"s1": 100, "s2": 300})

    def test_a_corrupt_file_is_not_fatal(self):
        # Losing what you have read is a smaller problem than a page that
        # will not load.
        self.path.write_text("{ this is not json")
        self.assertEqual(seen.load(self.path), {})

    def test_sessions_that_are_gone_are_forgotten(self):
        seen.mark("s1", 100, self.path)
        seen.mark("s2", 100, self.path)
        seen.forget({"s2"}, self.path)
        self.assertEqual(seen.load(self.path), {"s2": 100})

    def test_forgetting_nothing_leaves_the_file_alone(self):
        seen.mark("s1", 100, self.path)
        before = self.path.stat().st_mtime_ns
        seen.forget({"s1"}, self.path)
        self.assertEqual(self.path.stat().st_mtime_ns, before)
