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


def stamped(minutes_ago):
    import datetime
    when = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=minutes_ago))
    return when.isoformat().replace("+00:00", "Z")


def call(tool_id, minutes_ago):
    return {"type": "assistant", "timestamp": stamped(minutes_ago),
            "message": {"content": [{"type": "tool_use", "id": tool_id,
                                     "name": "Bash", "input": {"command": "ls"}}]}}


def answer(tool_id, minutes_ago):
    return {"type": "user", "timestamp": stamped(minutes_ago),
            "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id,
                                     "content": "ok"}]}}


def said(text, minutes_ago):
    return {"type": "assistant", "timestamp": stamped(minutes_ago),
            "message": {"content": [{"type": "text", "text": text}]}}


class InFlight(unittest.TestCase):
    """What counts as a tool call still running.

    The page reads transcripts incrementally, so unlike a full read it never
    forgets. A call whose result never arrives -- an interrupted turn, a
    compaction, a subagent whose result lands in another file -- used to sit
    in that memory for the rest of the session, and once it was 20 minutes
    old every busy poll flagged the session `tool 20m`. It blinked off
    whenever the session stopped being busy, which is what a real long call
    never does.
    """

    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "t.jsonl"
        fleet._cache.clear()

    def test_a_call_with_no_result_yet_is_in_flight(self):
        write(self.path, [call("t1", 25)], "w")
        self.assertAlmostEqual(fleet.scan_cached(self.path)["pending"], 25, delta=1)

    def test_an_answered_call_is_not(self):
        write(self.path, [call("t1", 25), answer("t1", 24)], "w")
        self.assertIsNone(fleet.scan_cached(self.path)["pending"])

    def test_a_call_the_session_moved_on_from_is_not_in_flight(self):
        # The result never came, and then the session said something else.
        # Nothing is running: the transcript moved on without it.
        write(self.path, [call("t1", 40)], "w")
        fleet.scan_cached(self.path)
        write(self.path, [said("carrying on", 5)])
        self.assertIsNone(fleet.scan_cached(self.path)["pending"])

    def test_the_newest_call_is_the_one_reported(self):
        write(self.path, [call("t1", 40), answer("t1", 39), call("t2", 3)], "w")
        self.assertAlmostEqual(fleet.scan_cached(self.path)["pending"], 3, delta=1)

    def test_two_calls_in_one_message_are_both_in_flight(self):
        # Parallel tool calls share a message, and a timestamp.
        write(self.path, [{"type": "assistant", "timestamp": stamped(7), "message": {
            "content": [{"type": "tool_use", "id": "a", "name": "Bash", "input": {}},
                        {"type": "tool_use", "id": "b", "name": "Read", "input": {}}]}}], "w")
        self.assertAlmostEqual(fleet.scan_cached(self.path)["pending"], 7, delta=1)

    def test_the_memory_of_calls_does_not_grow_without_end(self):
        write(self.path, [call(f"t{i}", 60 - i) for i in range(200)], "w")
        fleet.scan_cached(self.path)
        state = fleet._cache[("state", str(self.path))]
        self.assertLessEqual(len(state["uses"]), 64)


class StartingASkill(unittest.TestCase):
    """A skill starts in two ways, and they look nothing alike on disk."""

    def test_the_model_calling_the_skill_tool(self):
        self.assertTrue(fleet.boss_line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "boss"}}]}}))

    def test_you_typing_the_slash_command(self):
        # This is how the second boss was started, and matching only the
        # tool call missed him for a morning.
        self.assertTrue(fleet.boss_line({"type": "user", "message": {"content":
            "<command-message>boss</command-message>\n"
            "<command-name>/boss</command-name>\n"
            "<command-args>you'll overview lumen, your team is Kian and Basil</command-args>"}}))

    def test_another_skill_is_not_the_boss_skill(self):
        self.assertFalse(fleet.boss_line({"type": "user", "message": {"content":
            "<command-name>/deploy</command-name>"}}))
        self.assertFalse(fleet.boss_line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "brainstorming"}}]}}))

    def test_reading_the_skill_is_not_running_it(self):
        # How this feature was written: a session that greps the boss files
        # carries every one of these words in a tool result.
        self.assertFalse(fleet.boss_line({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "<command-name>/boss</command-name> ... skill: boss"}]}}))
        self.assertFalse(fleet.boss_line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "grep -c 'skill\":\"boss\"' transcript.jsonl"}}]}}))

    def test_a_boss_is_found_wherever_in_the_file_it_was_started(self):
        # `/boss` was typed a third of the way into a 1.8 MB transcript --
        # well past any head worth reading, which is why the whole file is
        # scanned once rather than a bounded slice of it.
        path = Path(tempfile.mkdtemp()) / "t.jsonl"
        filler = {"type": "assistant", "timestamp": stamped(9),
                  "message": {"content": [{"type": "text", "text": "x" * 400}]}}
        write(path, [filler] * 300 +
                    [{"type": "user", "message": {"content":
                      "<command-name>/boss</command-name>"}}] +
                    [filler] * 300, "w")
        fleet._cache.clear()
        self.assertTrue(fleet.scan_cached(path)["boss"])

    def test_a_transcript_that_never_mentions_it_is_not_parsed_twice(self):
        path = Path(tempfile.mkdtemp()) / "t.jsonl"
        write(path, [{"type": "ai-title", "aiTitle": "Ordinary work"}], "w")
        fleet._cache.clear()
        self.assertFalse(fleet.scan_cached(path)["boss"])


class WhatItIsDoing(unittest.TestCase):
    """The call in flight, which is the busy row's whole content."""

    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "t.jsonl"
        fleet._cache.clear()

    def test_the_call_in_flight_names_the_work(self):
        write(self.path, [{"type": "assistant", "timestamp": "2026-09-08T10:00:00.000Z",
                           "message": {"content": [
                               {"type": "tool_use", "id": "t1", "name": "Edit",
                                "input": {"file_path": "/x/fleet.py",
                                          "old_string": "a", "new_string": "b"}}]}}], "w")
        self.assertEqual(fleet.scan_cached(self.path)["doing"], "Editing fleet.py")

    def test_an_answered_call_is_not_what_it_is_doing(self):
        write(self.path, [{"type": "assistant", "timestamp": "2026-09-08T10:00:00.000Z",
                           "message": {"content": [
                               {"type": "tool_use", "id": "t1", "name": "Edit",
                                "input": {"file_path": "/x/fleet.py"}}]}}], "w")
        write(self.path, [{"type": "user", "timestamp": "2026-09-08T10:00:01.000Z",
                           "message": {"content": [
                               {"type": "tool_result", "tool_use_id": "t1"}]}}])
        self.assertEqual(fleet.scan_cached(self.path)["doing"], "")

    def test_a_call_the_session_has_talked_past_is_not_running(self):
        # The same rule `pending` uses: an unanswered call that is no longer
        # the newest thing said is a result that is never coming.
        write(self.path, [{"type": "assistant", "timestamp": "2026-09-08T10:00:00.000Z",
                           "message": {"content": [
                               {"type": "tool_use", "id": "t1", "name": "Edit",
                                "input": {"file_path": "/x/fleet.py"}}]}}], "w")
        write(self.path, [{"type": "assistant", "timestamp": "2026-09-08T10:05:00.000Z",
                           "message": {"content": [{"type": "text", "text": "Done."}]}}])
        self.assertEqual(fleet.scan_cached(self.path)["doing"], "")

    def test_a_written_file_is_not_kept_in_memory(self):
        # A Write carries the whole file in its input. Ten sessions holding
        # their last write is how a page that reads incrementally to stay
        # cheap gets expensive again.
        big = "x" * 200_000
        write(self.path, [{"type": "assistant", "timestamp": "2026-09-08T10:00:00.000Z",
                           "message": {"content": [
                               {"type": "tool_use", "id": "t1", "name": "Write",
                                "input": {"file_path": "/x/big.txt", "content": big}}]}}], "w")
        self.assertEqual(fleet.scan_cached(self.path)["doing"], "Writing big.txt")
        state = fleet._cache[("state", str(self.path))]
        self.assertLess(len(json.dumps(state["uses"], default=str)), 2000)


class WhatItSaidLast(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "t.jsonl"
        fleet._cache.clear()

    def test_a_new_prompt_clears_the_last_thing_it_said(self):
        # A busy row shows the session's running commentary. Kept across a
        # new prompt, the previous turn's closing sentence reads as what it
        # is doing now.
        write(self.path, [{"type": "assistant", "timestamp": "2026-09-08T10:00:00.000Z",
                           "message": {"content": [{"type": "text", "text": "All done."}]}}], "w")
        self.assertEqual(fleet.scan_cached(self.path)["said"], "All done.")
        write(self.path, [{"type": "user", "timestamp": "2026-09-08T10:01:00.000Z",
                           "message": {"content": "now do the other thing"}}])
        self.assertEqual(fleet.scan_cached(self.path)["said"], "")

    def test_a_tool_result_is_not_a_new_prompt(self):
        write(self.path, [{"type": "assistant", "timestamp": "2026-09-08T10:00:00.000Z",
                           "message": {"content": [{"type": "text", "text": "Checking."}]}}], "w")
        write(self.path, [{"type": "user", "timestamp": "2026-09-08T10:00:01.000Z",
                           "message": {"content": [
                               {"type": "tool_result", "tool_use_id": "t1"}]}}])
        self.assertEqual(fleet.scan_cached(self.path)["said"], "Checking.")

    def test_a_meta_record_is_not_a_new_prompt(self):
        # The hook's own block reaches the transcript as a meta user record.
        write(self.path, [{"type": "assistant", "timestamp": "2026-09-08T10:00:00.000Z",
                           "message": {"content": [{"type": "text", "text": "Checking."}]}}], "w")
        write(self.path, [{"type": "user", "isMeta": True,
                           "message": {"content": "Stop hook feedback: ..."}}])
        self.assertEqual(fleet.scan_cached(self.path)["said"], "Checking.")
