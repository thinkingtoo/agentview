"""What the Claude reader counts from a transcript: writes per minute, over the
last 30 minutes, the session's own and its subagents'.

Fixtures are invented records with a timestamp and nothing else the reader
needs; no real text, no real paths. `NOW` is passed in, so no test depends on
the clock or on where in a minute it happens to run.
"""
import contextlib
import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import base, claude

NOW = datetime.datetime(2026, 10, 19, 12, 0, 30, tzinfo=datetime.timezone.utc)


def at(seconds_ago):
    when = NOW - datetime.timedelta(seconds=seconds_ago)
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def record(seconds_ago, kind="assistant", **extra):
    return {"type": kind, "timestamp": at(seconds_ago),
            "message": {"content": [{"type": "text", "text": "x"}]}, **extra}


def write(path, records, mode="a"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode, encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


@contextlib.contextmanager
def reads_of_files():
    """Every read of a file while the block runs, as (path, offset) pairs."""
    got = []
    original = base.read_from
    with mock.patch.object(base, "read_from",
                           lambda path, offset: (got.append((str(path), offset)), original(path, offset))[1]):
        yield got


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "proj" / "sid.jsonl"
        claude._cache.clear()
        claude.SUBS.cache.clear()

    def scan(self):
        return claude.scan_session(self.path, now=NOW.timestamp())


class WritesPerMinute(Base):
    def test_records_land_in_their_minute_with_the_newest_minute_last(self):
        # 12:00:30 is "now", so the last slot is the minute 12:00. Slot 28 is
        # 11:59, and 11:31 is the oldest minute still shown (slot 0).
        write(self.path, [record(10), record(20), record(40), record(29 * 60 + 5)], "w")
        writes = self.scan()["writes"]
        self.assertEqual(len(writes), 30)
        self.assertEqual((writes[0], writes[28], writes[29]), (1, 1, 2))
        self.assertEqual(sum(writes), 4)

    def test_a_record_older_than_thirty_minutes_is_not_in_the_strip(self):
        write(self.path, [record(31 * 60), record(10)], "w")
        writes = self.scan()["writes"]
        self.assertEqual((sum(writes), writes[29]), (1, 1))

    def test_bookkeeping_records_without_a_timestamp_are_not_writes(self):
        write(self.path, [{"type": "ai-title", "aiTitle": "Checkout form"},
                          {"type": "last-prompt", "lastPrompt": "hello"},
                          record(10)], "w")
        self.assertEqual(sum(self.scan()["writes"]), 1)

    def test_a_second_scan_adds_only_what_was_appended(self):
        write(self.path, [record(50), record(40)], "w")
        self.assertEqual(sum(self.scan()["writes"]), 2)
        write(self.path, [record(5)])
        with reads_of_files() as reads:
            writes = self.scan()["writes"]
        self.assertEqual(sum(writes), 3)
        # No extra full-file read: the counter rides on the one tail read, and
        # that read starts where the last one stopped.
        self.assertEqual(len(reads), 1)
        self.assertGreater(reads[0][1], 0)

    def test_a_session_quiet_for_an_hour_has_a_strip_of_zeros(self):
        write(self.path, [record(3600)], "w")
        self.assertEqual(self.scan()["writes"], [0] * 30)

    def test_no_transcript_yet_reports_no_strip_rather_than_zeros(self):
        self.assertIsNone(claude.scan_session(self.dir / "missing.jsonl", now=NOW.timestamp())["writes"])


class ColdStart(Base):
    """R14: after a restart the reader sees only the last COLD_BYTES of a big
    transcript. The minutes it could not see are unknown, not zero."""

    def big_transcript(self):
        # 40 minutes of one record every 20 s, each padded so the file is
        # larger than the (patched) cold window and the window holds only
        # the most recent part of it.
        pad = "p" * 400
        records = [record(s, pad=pad) for s in range(40 * 60, -1, -20)]
        write(self.path, records, "w")
        return records

    def test_minutes_before_the_window_are_unknown_not_zero(self):
        self.big_transcript()
        with mock.patch.object(base, "COLD_BYTES", 6000):
            writes = self.scan()["writes"]
        self.assertLess(6000, self.path.stat().st_size)
        unknown = [i for i, w in enumerate(writes) if w is None]
        # An oldest stretch is unknown, and it is a stretch: nothing seen is
        # followed by anything unseen.
        self.assertTrue(unknown, "a 6 kB window cannot have seen 30 minutes")
        self.assertEqual(unknown, list(range(len(unknown))))
        # What the window did see is counted, minute by minute, three a minute.
        seen = writes[len(unknown):]
        self.assertTrue(all(isinstance(w, int) for w in seen))
        self.assertEqual(seen[-2], 3)

    def test_the_first_minute_in_the_window_may_be_cut_so_it_is_unknown_too(self):
        # Equal-length records, three a minute at :10 :30 :50, and a window
        # that starts inside the line of the 11:57:10 record: the first whole
        # record is the one at 11:57:30, so the 11:57:10 one, in the same
        # minute, was never seen. That minute is therefore unknown. The next
        # one, 11:58, is whole.
        pad = "p" * 400
        write(self.path, [record(s, pad=pad) for s in range(40 * 60, -1, -20)], "w")
        line = len(self.path.read_bytes().splitlines()[0]) + 1
        with mock.patch.object(base, "COLD_BYTES", 10 * line + line // 2):
            writes = self.scan()["writes"]
        # Slot 29 is 12:00, so 11:58 is slot 27 and 11:57 is slot 26.
        self.assertEqual(writes[:26], [None] * 26)
        self.assertEqual(writes[26], None)
        self.assertEqual(writes[27], 3)

    def test_the_counters_add_no_read_to_a_cold_start(self):
        # One read of the tail, and nothing else: the counters ride on it.
        records = self.big_transcript()
        write(self.path, [{"type": "ai-title", "aiTitle": "Checkout form"}] + records[-3:], "a")
        with reads_of_files() as reads, mock.patch.object(base, "COLD_BYTES", 6000):
            self.scan()
        self.assertEqual([offset for _, offset in reads], [self.path.stat().st_size - 6000])

    def test_a_small_transcript_is_read_whole_so_nothing_in_it_is_unknown(self):
        write(self.path, [record(10)], "w")
        self.assertNotIn(None, self.scan()["writes"])

    def test_a_cold_read_of_a_quiet_session_still_knows_every_minute(self):
        # A big file whose window reaches back past 30 minutes saw them all.
        pad = "p" * 400
        write(self.path, [record(7200 - s * 20, pad=pad) for s in range(100)], "w")
        with mock.patch.object(base, "COLD_BYTES", 6000):
            writes = self.scan()["writes"]
        self.assertEqual(writes, [0] * 30)

    def test_the_unknown_minutes_age_out_as_the_clock_moves_on(self):
        self.big_transcript()
        with mock.patch.object(base, "COLD_BYTES", 6000):
            first = claude.scan_session(self.path, now=NOW.timestamp())["writes"]
        later = claude.scan_session(self.path, now=NOW.timestamp() + 40 * 60)["writes"]
        self.assertGreater(first.count(None), 0)
        self.assertEqual(later.count(None), 0)       # the unseen minutes are over 30 minutes old by then


def touch(path, seconds_ago):
    """Make the file look last written `seconds_ago` before NOW."""
    stamp = NOW.timestamp() - seconds_ago
    os.utime(path, (stamp, stamp))


class Subagents(Base):
    """R15: a subagent's writes count once, under its parent."""

    def subagent(self, name, records, seconds_ago=5):
        sub = self.path.with_suffix("") / "subagents" / f"{name}.jsonl"
        write(sub, records, "w")
        touch(sub, seconds_ago)
        return sub

    def test_a_subagents_writes_are_added_to_its_parents_strip(self):
        write(self.path, [record(10), record(70)], "w")
        self.subagent("agent-a1", [record(15), record(16), record(75)])
        writes = self.scan()["writes"]
        self.assertEqual((writes[28], writes[29]), (2, 3))
        self.assertEqual(sum(writes), 5)

    def test_two_subagents_and_the_parent_are_one_sum(self):
        write(self.path, [record(10)], "w")
        self.subagent("agent-a1", [record(12)])
        self.subagent("agent-b2", [record(14), record(15)])
        self.assertEqual(self.scan()["writes"][29], 4)

    def test_a_second_scan_counts_a_subagent_once_not_again(self):
        write(self.path, [record(10)], "w")
        sub = self.subagent("agent-a1", [record(12)])
        self.assertEqual(sum(self.scan()["writes"]), 2)
        self.assertEqual(sum(self.scan()["writes"]), 2)
        write(sub, [record(3)])
        touch(sub, 3)
        self.assertEqual(sum(self.scan()["writes"]), 3)

    def test_the_archive_scan_does_not_look_into_subagent_folders(self):
        # snapshot.py wants a title and calls scan_cached for every transcript
        # it keeps; a folder of subagents is for a session that is running.
        write(self.path, [record(10)], "w")
        self.subagent("agent-a1", [record(12), record(13)])
        got = claude.scan_cached(self.path, now=NOW.timestamp())
        self.assertEqual(sum(got["writes"]), 1)
        self.assertNotIn("subQuiet", got)

    def test_a_subagent_file_that_did_not_change_is_not_read_again(self):
        write(self.path, [record(10)], "w")
        self.subagent("agent-a1", [record(12)])
        self.scan()
        with reads_of_files() as reads:
            self.scan()
        self.assertEqual(reads, [])

    def test_when_a_subagent_last_wrote_is_reported_in_minutes(self):
        write(self.path, [record(600)], "w")
        self.subagent("agent-a1", [record(130)], seconds_ago=130)
        self.subagent("agent-b2", [record(400)], seconds_ago=400)
        self.assertAlmostEqual(self.scan()["subQuiet"], 130 / 60)

    def test_no_subagents_means_no_subagent_time(self):
        write(self.path, [record(10)], "w")
        self.assertIsNone(self.scan()["subQuiet"])

    def test_a_subagent_that_stopped_long_ago_is_neither_read_nor_counted(self):
        write(self.path, [record(10)], "w")
        self.subagent("agent-old", [record(3 * 3600)], seconds_ago=3 * 3600)
        with reads_of_files() as reads:
            writes = self.scan()["writes"]
        self.assertEqual(sum(writes), 1)
        self.assertEqual([path for path, _ in reads if "agent-old" in path], [])

    def test_a_subagent_file_that_is_not_a_transcript_is_ignored(self):
        write(self.path, [record(10)], "w")
        stray = self.path.with_suffix("") / "subagents" / "notes.txt"
        stray.parent.mkdir(parents=True)
        stray.write_text("not json\n")
        self.assertEqual(sum(self.scan()["writes"]), 1)


def started(seconds_ago, tool_id, command="pytest -q", description="Run the unit tests"):
    """The session asked for a command to run in the background."""
    return {"type": "assistant", "timestamp": at(seconds_ago),
            "message": {"content": [{"type": "tool_use", "id": tool_id, "name": "Bash",
                                     "input": {"command": command, "description": description,
                                               "run_in_background": True}}]}}


def accepted(seconds_ago, tool_id, task_id, key="backgroundTaskId"):
    """Claude Code's answer: the command runs, here is its task id."""
    return {"type": "user", "timestamp": at(seconds_ago),
            "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id,
                                     "content": "running in the background"}]},
            "toolUseResult": {key: task_id, "stdout": "", "stderr": ""}}


def notice(task_id, status="completed"):
    return ("<task-notification>\n<task-id>%s</task-id>\n<tool-use-id>toolu_x</tool-use-id>\n"
            "<output-file>/tmp/x/%s.output</output-file>\n<status>%s</status>\n"
            "<summary>done</summary>\n</task-notification>" % (task_id, task_id, status))


def queued(seconds_ago, text):
    return {"type": "queue-operation", "operation": "enqueue",
            "timestamp": at(seconds_ago), "content": text}


class BackgroundTasks(Base):
    def tasks(self):
        return self.scan()["tasks"]

    def test_a_command_started_in_the_background_is_an_open_task_with_its_age(self):
        write(self.path, [started(700, "toolu_1"), accepted(699, "toolu_1", "bk7q2m9xa")], "w")
        got = self.tasks()
        self.assertEqual([t["label"] for t in got], ["Run the unit tests"])
        self.assertAlmostEqual(got[0]["since"], 699 / 60)   # it ran from the answer

    def test_a_task_the_session_was_told_ended_is_no_longer_open(self):
        write(self.path, [started(700, "toolu_1"), accepted(699, "toolu_1", "bk7q2m9xa"),
                          queued(60, notice("bk7q2m9xa"))], "w")
        self.assertEqual(self.tasks(), [])

    def test_failed_killed_and_stopped_close_a_task_as_completed_does(self):
        for status in ("failed", "killed", "stopped"):
            write(self.path, [started(700, "toolu_1"), accepted(699, "toolu_1", "bk7q2m9xa"),
                              queued(60, notice("bk7q2m9xa", status))], "w")
            claude._cache.clear()
            self.assertEqual(self.tasks(), [], status)

    def test_the_notice_can_arrive_as_a_queued_command_or_a_typed_turn(self):
        for ending in (
                {"type": "attachment", "timestamp": at(60),
                 "attachment": {"type": "queued_command", "prompt": notice("bk7q2m9xa")}},
                {"type": "user", "timestamp": at(60),
                 "message": {"role": "user", "content": notice("bk7q2m9xa")}}):
            write(self.path, [started(700, "toolu_1"), accepted(699, "toolu_1", "bk7q2m9xa"),
                              ending], "w")
            claude._cache.clear()
            self.assertEqual(self.tasks(), [])

    def test_stopping_a_task_by_hand_closes_it_and_never_opens_one(self):
        # TaskStop's own result carries `task_id`; reading it as a start made
        # phantom open tasks on 6 of 24 live sessions.
        stop = {"type": "user", "timestamp": at(30),
                "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_2",
                                         "content": "stopped"}]},
                "toolUseResult": {"message": "stopped", "task_id": "bk7q2m9xa",
                                  "task_type": "local_bash", "command": "pytest -q"}}
        write(self.path, [started(700, "toolu_1"), accepted(699, "toolu_1", "bk7q2m9xa"), stop], "w")
        self.assertEqual(self.tasks(), [])
        claude._cache.clear()
        write(self.path, [stop], "w")
        self.assertEqual(self.tasks(), [])

    def test_a_notice_quoted_inside_a_tool_result_is_not_an_ending(self):
        # A session reading a file or a log that shows a notice is not being told.
        quote = {"type": "user", "timestamp": at(30),
                 "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_9",
                                          "content": notice("bk7q2m9xa")}]}}
        write(self.path, [started(700, "toolu_1"), accepted(699, "toolu_1", "bk7q2m9xa"), quote], "w")
        self.assertEqual(len(self.tasks()), 1)

    def test_a_monitor_is_a_background_task_too(self):
        write(self.path, [
            {"type": "assistant", "timestamp": at(300),
             "message": {"content": [{"type": "tool_use", "id": "toolu_m", "name": "Monitor",
                                      "input": {"description": "Watch the deploy"}}]}},
            accepted(299, "toolu_m", "bm1x2y3z4", key="taskId")], "w")
        self.assertEqual(len(self.tasks()), 1)

    def test_a_background_agent_is_not_a_shell_task(self):
        # Its evidence is its own transcript (the subagent reader), and no
        # shell can stand behind it.
        write(self.path, [started(700, "toolu_1", command="", description="Review"),
                          accepted(699, "toolu_1", "a9k2m7q1x", key="taskId")], "w")
        self.assertEqual(self.tasks(), [])

    def test_a_task_started_beyond_what_was_read_is_just_not_known(self):
        write(self.path, [queued(60, notice("bk7q2m9xa"))], "w")
        self.assertEqual(self.tasks(), [])

    def test_a_task_whose_starting_call_is_unknown_still_counts(self):
        write(self.path, [accepted(699, "toolu_gone", "bk7q2m9xa")], "w")
        self.assertEqual([t["label"] for t in self.tasks()], ["a background job"])

    def test_an_ordinary_tool_result_opens_nothing(self):
        write(self.path, [{"type": "user", "timestamp": at(5),
                           "message": {"content": [{"type": "tool_result", "tool_use_id": "t",
                                                    "content": "ok"}]},
                           "toolUseResult": {"stdout": "ok", "stderr": ""}}], "w")
        self.assertEqual(self.tasks(), [])

    def test_the_open_tasks_are_remembered_only_up_to_a_bound(self):
        records = []
        for n in range(claude.MAX_TASKS + 20):
            records += [started(900 - n, f"toolu_{n}"), accepted(899 - n, f"toolu_{n}", f"bt{n:07d}")]
        write(self.path, records, "w")
        self.assertEqual(len(self.tasks()), claude.MAX_TASKS)


if __name__ == "__main__":
    unittest.main()
