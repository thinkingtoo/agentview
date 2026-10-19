"""What the overview remembers about finished sessions, beside `seen.json`.

Two facts: which stop of a session you read the handover of, in the overview,
and which sessions you pinned open. Neither is config -- that file is yours to
hand-edit -- and neither is the chime's seen mark, which keeps its meaning.
"""
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import finished
import seen


class State(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        self.path = tmp / "finished.json"

    def test_nothing_is_read_or_pinned_to_begin_with(self):
        self.assertEqual(finished.load(self.path), {"read": {}, "pinned": []})

    def test_a_handover_is_read_as_of_the_stop_it_was_read_at(self):
        finished.mark_read("fake:a", 100, self.path)
        state = finished.load(self.path)
        self.assertTrue(finished.is_read("fake:a", 100, state))

    def test_a_session_that_stops_again_has_a_handover_you_have_not_read(self):
        finished.mark_read("fake:a", 100, self.path)
        self.assertFalse(finished.is_read("fake:a", 200, finished.load(self.path)))

    def test_a_session_with_no_stop_has_nothing_to_have_read(self):
        finished.mark_read("fake:a", 0, self.path)
        self.assertEqual(finished.load(self.path)["read"], {})
        self.assertFalse(finished.is_read("fake:a", 0, finished.load(self.path)))

    def test_pinning_and_unpinning(self):
        finished.pin("fake:a", True, self.path)
        finished.pin("fake:b", True, self.path)
        finished.pin("fake:a", True, self.path)
        self.assertEqual(finished.load(self.path)["pinned"], ["fake:a", "fake:b"])
        finished.pin("fake:a", False, self.path)
        self.assertEqual(finished.load(self.path)["pinned"], ["fake:b"])

    def test_a_pin_and_a_read_mark_do_not_undo_each_other(self):
        finished.mark_read("fake:a", 100, self.path)
        finished.pin("fake:a", True, self.path)
        finished.mark_read("fake:b", 300, self.path)
        self.assertEqual(finished.load(self.path),
                         {"read": {"fake:a": 100, "fake:b": 300}, "pinned": ["fake:a"]})

    def test_a_file_that_is_not_ours_reads_as_nothing_and_does_not_raise(self):
        for text in ("", "not json", "[]", "7", '{"read": 5, "pinned": "x"}',
                     '{"read": {"a": "soon", "b": true, "c": null}, "pinned": [1, null, {}]}'):
            with self.subTest(text=text):
                self.path.write_text(text)
                self.assertEqual(finished.load(self.path), {"read": {}, "pinned": []})

    def test_a_folder_that_cannot_be_written_is_not_a_crash(self):
        blocked = self.path.parent / "file"
        blocked.write_text("")
        finished.pin("fake:a", True, blocked / "finished.json")
        finished.mark_read("fake:a", 100, blocked / "finished.json")

    def test_forgetting_drops_what_no_longer_exists(self):
        finished.mark_read("fake:a", 100, self.path)
        finished.mark_read("fake:b", 100, self.path)
        finished.pin("fake:a", True, self.path)
        finished.pin("fake:b", True, self.path)
        finished.forget({"fake:a"}, self.path, answered={"fake"})
        self.assertEqual(finished.load(self.path), {"read": {"fake:a": 100}, "pinned": ["fake:a"]})

    def test_a_provider_that_did_not_answer_keeps_its_sessions_pins_and_marks(self):
        # A missed round is not a closed session: forgetting then would turn
        # every pill of that provider back into a tile when it comes back.
        finished.mark_read("codex:a", 100, self.path)
        finished.pin("codex:a", True, self.path)
        finished.forget({"claude:x"}, self.path, answered={"claude"})
        self.assertEqual(finished.load(self.path), {"read": {"codex:a": 100}, "pinned": ["codex:a"]})

    def test_two_threads_changing_it_at_once_both_land(self):
        def work(n):
            for i in range(25):
                finished.pin(f"fake:{n}-{i}", True, self.path)
                finished.mark_read(f"fake:{n}-{i}", 100 + i, self.path)
        threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        state = finished.load(self.path)
        self.assertEqual((len(state["pinned"]), len(state["read"])), (100, 100))


class Where(unittest.TestCase):
    def test_it_is_beside_the_seen_marks_so_that_one_move_of_the_state_folder_moves_both(self):
        was = seen.store
        self.addCleanup(setattr, seen, "store", was)
        seen.store = lambda: Path("/somewhere/agentview/seen.json")
        self.assertEqual(finished.store(), Path("/somewhere/agentview/finished.json"))


if __name__ == "__main__":
    unittest.main()
