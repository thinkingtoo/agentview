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
        claude._teams.clear()

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


class Workflows(Base):
    """A workflow's agents write one folder deeper than a background agent:
    `<session>/subagents/workflows/<run>/agent-*.jsonl`. A session waiting on
    the workflow is waiting on subagents (ticket 08, box 2)."""

    def agent(self, run, name, records, seconds_ago=5):
        agent = self.path.with_suffix("") / "subagents" / "workflows" / run / f"{name}.jsonl"
        write(agent, records, "w")
        touch(agent, seconds_ago)
        return agent

    def test_a_workflow_agents_writes_are_added_to_the_sessions_strip(self):
        write(self.path, [record(600)], "w")
        self.agent("wf_one", "agent-a1", [record(15), record(16)])
        writes = self.scan()["writes"]
        self.assertEqual((writes[29], sum(writes)), (2, 3))      # the session's own write is 10 minutes back

    def test_when_a_workflow_agent_last_wrote_is_the_subagent_time(self):
        write(self.path, [record(900)], "w")
        self.agent("wf_one", "agent-a1", [record(130)], seconds_ago=130)
        self.agent("wf_two", "agent-b2", [record(400)], seconds_ago=400)
        self.assertAlmostEqual(self.scan()["subQuiet"], 130 / 60)

    def test_a_background_agent_and_a_workflow_agent_are_one_sum(self):
        write(self.path, [record(600)], "w")
        sub = self.path.with_suffix("") / "subagents" / "agent-a1.jsonl"
        write(sub, [record(12)], "w")
        touch(sub, 12)
        self.agent("wf_one", "agent-b2", [record(14)])
        self.assertEqual(self.scan()["writes"][29], 2)

    def test_a_workflow_agent_that_stopped_long_ago_is_neither_read_nor_counted(self):
        write(self.path, [record(10)], "w")
        old = self.agent("wf_one", "agent-old", [record(3 * 3600)], seconds_ago=3 * 3600)
        with reads_of_files() as reads:
            writes = self.scan()["writes"]
        self.assertEqual(sum(writes), 1)
        self.assertEqual([path for path, _ in reads if path == str(old)], [])

    def test_a_file_in_a_workflow_folder_that_is_not_a_transcript_is_ignored(self):
        write(self.path, [record(10)], "w")
        meta = self.path.with_suffix("") / "subagents" / "workflows" / "wf_one" / "agent-a1.meta.json"
        meta.parent.mkdir(parents=True)
        meta.write_text("{}\n")
        self.assertEqual(sum(self.scan()["writes"]), 1)
        self.assertIsNone(self.scan()["subQuiet"])


LEAD = "6f0c91aa-1111-4222-8333-444455556666"
HEADER = [{"type": "agent-setting", "agentSetting": "general-purpose", "sessionId": "m"},
          {"type": "mode", "mode": "normal", "sessionId": "m"}]


class Teammates(Base):
    """A named teammate is not under the session's folder: it writes a transcript
    of its own next to the session's, and says whose team it is in its first
    message, `teamName: session-<first 8 of the session's id>`. A session
    waiting on one is waiting on a subagent (ticket 08, box 2)."""

    def setUp(self):
        super().setUp()
        self.path = self.dir / "proj" / f"{LEAD}.jsonl"
        write(self.path, [record(600)], "w")

    def mate(self, name, records, team=f"session-{LEAD[:8]}", seconds_ago=5, header=HEADER, folder=None):
        """A transcript beside the session's (or in another project folder, next
        to the session's own): header lines, then the messages, each stamped
        with the team when it has one."""
        extra = {"teamName": team, "agentName": name} if team else {}
        path = (self.dir / folder if folder else self.path.parent) / f"{name}.jsonl"
        write(path, header + [{**r, **extra} for r in records], "w")
        touch(path, seconds_ago)
        return path

    def test_a_teammates_writes_are_added_to_the_sessions_strip(self):
        self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [record(15, "user"), record(16)])
        writes = self.scan()["writes"]
        self.assertEqual((writes[29], sum(writes)), (2, 3))      # the session's own write is 10 minutes back

    def test_when_a_teammate_last_wrote_is_the_subagent_time(self):
        self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [record(130, "user")], seconds_ago=130)
        self.mate("22222222-aaaa-4bbb-8ccc-000000000002", [record(400, "user")], seconds_ago=400)
        self.assertAlmostEqual(self.scan()["subQuiet"], 130 / 60)

    def test_a_transcript_of_another_sessions_team_or_of_no_team_is_not_a_teammate(self):
        self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [record(15, "user")], team="session-99999999")
        self.mate("22222222-aaaa-4bbb-8ccc-000000000002", [record(15, "user")], team=None)
        got = self.scan()
        self.assertEqual(sum(got["writes"]), 1)
        self.assertIsNone(got["subQuiet"])

    def test_a_teammate_that_stopped_long_ago_is_not_counted(self):
        self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [record(3 * 3600, "user")], seconds_ago=3 * 3600)
        got = self.scan()
        self.assertEqual(sum(got["writes"]), 1)
        self.assertIsNone(got["subQuiet"])

    def test_a_teammate_whose_first_message_is_not_written_yet_counts_once_it_is(self):
        mate = self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [])
        self.assertIsNone(self.scan()["subQuiet"])
        write(mate, [{**record(3, "user"), "teamName": f"session-{LEAD[:8]}"}])
        touch(mate, 3)
        self.assertAlmostEqual(self.scan()["subQuiet"], 3 / 60)

    def test_a_teammate_is_not_read_again_for_what_team_it_is_in(self):
        self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [record(15, "user")])
        self.mate("22222222-aaaa-4bbb-8ccc-000000000002", [record(15, "user")], team=None)
        self.scan()
        looked = []
        with mock.patch.object(claude, "_team_of", lambda path: looked.append(path)):
            self.assertAlmostEqual(self.scan()["subQuiet"], 5 / 60)
        self.assertEqual(looked, [])

    def test_what_team_a_file_is_in_is_kept_for_a_bounded_number_of_files(self):
        for n in range(5):
            self.mate(f"33333333-aaaa-4bbb-8ccc-00000000000{n}", [record(15, "user")], team=None)
        with mock.patch.object(claude, "MAX_TEAMS", 3):
            self.scan()
        self.assertLessEqual(len(claude._teams), 3)

    def test_the_sessions_own_transcript_is_not_its_teammate(self):
        # Its first message says it is in its own team, so only the exclusion
        # of its own file keeps it from being its own subagent.
        write(self.path, [{**record(5, "user"), "teamName": f"session-{LEAD[:8]}"}], "w")
        touch(self.path, 5)
        self.assertIsNone(self.scan()["subQuiet"])

    # Hunt 08-2, finding 2. A session that moves to another directory keeps its
    # transcript in the folder it started in, and a teammate it spawns after
    # that writes in the folder of the directory it is in then (2 of 118
    # teammates on this machine; both a `<project>-wt/<name>` worktree, both
    # one of the session's own directories).

    def lead_in(self, *directories):
        write(self.path, [record(600 - n, cwd=cwd) for n, cwd in enumerate(directories)], "w")

    def test_a_teammate_in_the_folder_of_a_directory_the_session_moved_to_is_its_teammate(self):
        self.lead_in("/work/proj", "/work/proj-wt/ana")
        self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [record(15, "user")], folder="-work-proj-wt-ana")
        got = self.scan()
        self.assertAlmostEqual(got["subQuiet"], 5 / 60)
        self.assertEqual(sum(got["writes"]), 3)      # the session's two records, and the teammate's

    def test_a_folder_of_a_directory_the_session_never_had_is_not_looked_into(self):
        self.lead_in("/work/proj")
        self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [record(15, "user")], folder="-work-elsewhere")
        got = self.scan()
        self.assertIsNone(got["subQuiet"])
        self.assertEqual(sum(got["writes"]), 1)

    def test_a_teammate_of_another_team_in_such_a_folder_is_still_not_its_teammate(self):
        self.lead_in("/work/proj", "/work/proj-wt/ana")
        self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [record(15, "user")], team="session-99999999",
                  folder="-work-proj-wt-ana")
        self.assertIsNone(self.scan()["subQuiet"])

    def test_the_sessions_own_folder_named_by_a_directory_is_not_counted_twice(self):
        self.lead_in("proj")        # a directory whose folder is the one the transcript is in
        self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [record(15, "user")])
        self.assertEqual(sum(self.scan()["writes"]), 2)

    def test_only_the_newest_directories_are_remembered(self):
        self.lead_in("/work/a", "/work/b", "/work/c")
        self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [record(15, "user")], folder="-work-a")
        self.mate("22222222-aaaa-4bbb-8ccc-000000000002", [record(15, "user")], folder="-work-c")
        with mock.patch.object(claude, "MAX_CWDS", 2):
            got = self.scan()
        self.assertEqual(sum(got["writes"]), 4)      # the session's three records, and the one in -work-c

    def test_a_directory_is_remembered_by_when_the_session_was_last_in_it(self):
        write(self.path, [record(600, cwd="/work/a"), record(590, cwd="/work/b"), record(580, cwd="/work/c"),
                          record(570, cwd="/work/a")], "w")
        self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [record(15, "user")], folder="-work-a")
        with mock.patch.object(claude, "MAX_CWDS", 2):
            self.assertAlmostEqual(self.scan()["subQuiet"], 5 / 60)

    def test_a_subagents_directory_in_the_sessions_file_is_not_the_sessions_own(self):
        write(self.path, [record(600, cwd="/work/proj"), record(30, cwd="/work/other", isSidechain=True)], "w")
        self.mate("22222222-aaaa-4bbb-8ccc-000000000001", [record(15, "user")], folder="-work-other")
        self.assertIsNone(self.scan()["subQuiet"])


class TurnEnd(Base):
    """The reader says when the session's own newest word is the end of a turn:
    Claude Code writes the stop hooks' summary and the turn's duration, and the
    registry may go on saying busy (hunt 08-2, finding 1)."""

    def over(self, *records):
        write(self.path, records, "w")
        return self.scan()["turnOver"]

    def test_a_turn_duration_is_the_end_of_a_turn(self):
        self.assertTrue(self.over(record(30), {"type": "system", "subtype": "turn_duration", "timestamp": at(29)}))

    def test_a_stop_hook_summary_is_the_end_of_a_turn(self):
        self.assertTrue(self.over(record(30), {"type": "system", "subtype": "stop_hook_summary", "timestamp": at(29)}))

    def test_a_session_still_working_is_not_over(self):
        self.assertFalse(self.over(record(30)))
        self.assertFalse(self.over())

    def test_what_is_said_after_the_end_of_a_turn_opens_it_again(self):
        end = {"type": "system", "subtype": "turn_duration", "timestamp": at(29)}
        self.assertFalse(self.over(record(30), end, record(20, "user")))
        self.assertFalse(self.over(record(30), end, record(20)))

    def test_a_subagents_end_of_turn_in_the_sessions_file_is_not_the_sessions(self):
        self.assertFalse(self.over(record(30), {"type": "system", "subtype": "turn_duration",
                                                "timestamp": at(29), "isSidechain": True}))

    def test_other_system_records_are_neither(self):
        notice = {"type": "system", "subtype": "informational", "timestamp": at(28)}
        end = {"type": "system", "subtype": "turn_duration", "timestamp": at(29)}
        self.assertTrue(self.over(record(30), end, notice))
        self.assertFalse(self.over(record(30), notice))


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
