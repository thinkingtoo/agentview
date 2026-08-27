import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet


def write(path, records, mode="a"):
    with open(path, mode, encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


class IncrementalScan(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "t.jsonl"
        fleet._cache.clear()

    def test_only_the_new_lines_are_read_the_second_time(self):
        # Transcripts run to tens of megabytes and change every few seconds.
        # Re-reading one in full on every poll is what made the page crawl.
        write(self.path, [{"type": "ai-title", "aiTitle": "First"}], "w")
        self.assertEqual(fleet.scan_cached(self.path)["title"], "First")

        reads = []
        original = fleet._read_from
        fleet._read_from = lambda p, off: (reads.append(off), original(p, off))[1]
        try:
            write(self.path, [{"type": "ai-title", "aiTitle": "Second"}])
            self.assertEqual(fleet.scan_cached(self.path)["title"], "Second")
        finally:
            fleet._read_from = original
        self.assertTrue(reads and reads[0] > 0, f"ha riletto da {reads}")

    def test_an_unchanged_file_is_not_read_at_all(self):
        write(self.path, [{"type": "last-prompt", "lastPrompt": "hello"}], "w")
        fleet.scan_cached(self.path)
        calls = []
        original = fleet._read_from
        fleet._read_from = lambda p, off: (calls.append(off), original(p, off))[1]
        try:
            self.assertEqual(fleet.scan_cached(self.path)["prompt"], "hello")
        finally:
            fleet._read_from = original
        self.assertEqual(calls, [])

    def test_a_tool_call_answered_later_stops_being_pending(self):
        write(self.path, [{"type": "assistant", "timestamp": "2026-08-27T10:00:00.000Z",
                           "message": {"content": [
                               {"type": "tool_use", "id": "t1", "name": "Bash",
                                "input": {"command": "sleep 1"}}]}}], "w")
        self.assertIsNotNone(fleet.scan_cached(self.path)["pending"])
        write(self.path, [{"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1"}]}}])
        self.assertIsNone(fleet.scan_cached(self.path)["pending"])

    def test_a_truncated_file_is_read_again_from_the_start(self):
        write(self.path, [{"type": "ai-title", "aiTitle": "Old"}], "w")
        fleet.scan_cached(self.path)
        write(self.path, [{"type": "ai-title", "aiTitle": "Fresh"}], "w")   # rewritten
        self.assertEqual(fleet.scan_cached(self.path)["title"], "Fresh")

    def test_half_a_line_at_the_end_is_not_swallowed(self):
        # A session writes while the page reads; the last line can be partial.
        write(self.path, [{"type": "ai-title", "aiTitle": "One"}], "w")
        fleet.scan_cached(self.path)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write('{"type": "ai-title", "aiTi')      # torn mid-write
        self.assertEqual(fleet.scan_cached(self.path)["title"], "One")
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write('tle": "Two"}\n')                  # the rest lands
        self.assertEqual(fleet.scan_cached(self.path)["title"], "Two")
