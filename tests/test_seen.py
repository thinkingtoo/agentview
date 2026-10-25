import json, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import seen


class Seen(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "seen.json"
        self.addCleanup(shutil.rmtree, self.path.parent, True)

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

    def test_the_sessions_named_are_forgotten(self):
        # Which ones are gone is the round's decision (`poll.round`).
        seen.mark("s1", 100, self.path)
        seen.mark("s2", 100, self.path)
        seen.forget({"s1"}, self.path)
        self.assertEqual(seen.load(self.path), {"s2": 100})

    def test_a_key_not_in_the_file_is_nothing_and_leaves_it_alone(self):
        seen.mark("s1", 100, self.path)
        before = self.path.stat().st_mtime_ns
        seen.forget({"s2"}, self.path)
        self.assertEqual(seen.load(self.path), {"s1": 100})
        self.assertEqual(self.path.stat().st_mtime_ns, before)
