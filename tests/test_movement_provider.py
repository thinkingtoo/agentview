"""What a Claude session carries about its movement once the reader and the
process look are put together, through `ClaudeProvider.live()` over a fake
config folder and a fake `/proc`. Nothing here reads the real ones.
"""
import datetime
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import claude, procs
from test_movement_procs import BASH, NODE, OUT, FakeProc

PTS_54 = 34870          # `/dev/pts/54` as the kernel numbers it: the session is on a terminal
SID = "11111111-aaaa-bbbb-cccc-222222222222"


def stamp(seconds_ago=0):
    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds_ago)
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def text(seconds_ago):
    return {"type": "assistant", "timestamp": stamp(seconds_ago),
            "message": {"content": [{"type": "text", "text": "x"}]}}


def call(seconds_ago, tool_id="toolu_1", **inp):
    return {"type": "assistant", "timestamp": stamp(seconds_ago),
            "message": {"content": [{"type": "tool_use", "id": tool_id, "name": "Bash",
                                     "input": {"command": "pytest -q",
                                               "description": "Run the unit tests", **inp}}]}}


def accepted(seconds_ago, tool_id, task_id):
    return {"type": "user", "timestamp": stamp(seconds_ago),
            "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id,
                                     "content": "running"}]},
            "toolUseResult": {"backgroundTaskId": task_id}}


def ended(task_id):
    return {"type": "queue-operation", "operation": "enqueue", "timestamp": stamp(1),
            "content": "<task-notification>\n<task-id>%s</task-id>\n<status>completed</status>\n"
                       "</task-notification>" % task_id}


class Provider(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.cfg = base / "claude"
        (self.cfg / "sessions").mkdir(parents=True)
        self.fake = FakeProc()
        # The session itself, on a terminal, the way the registry wants it.
        self.fake.add(100, cmd="claude\0")
        (self.fake.root / "100" / "stat").write_text(
            f"100 (claude) S 1 1 1 {PTS_54} -1 4194304 1 0 0 0 1 2 0 0 20 0 15 0 1640779 0 0\n")
        self.transcript = self.cfg / "projects" / "-tmp" / f"{SID}.jsonl"
        claude._cache.clear()
        claude.SUBS.cache.clear()
        self.provider = claude.ClaudeProvider(self.cfg, proc=self.fake.root)

    def session(self, records, status="busy"):
        self.transcript.parent.mkdir(parents=True, exist_ok=True)
        self.transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
        (self.cfg / "sessions" / "100.json").write_text(json.dumps({
            "pid": 100, "sessionId": SID, "kind": "interactive", "entrypoint": "cli",
            "status": status, "procStart": "1640779", "cwd": "/tmp", "name": "Ilse"}))

    def live(self):
        return self.provider.live()

    def shell(self, *, ticks=10, task=None, number=200):
        """A command the session runs, with something under it. With `task`,
        it is that background task's shell: its output is the task's file."""
        shell = self.fake.add(number, 100, cmd=BASH, out=OUT % task if task else None)
        return self.fake.add(number + 100, shell, cmd="python3\0-m\0pytest\0", ticks=ticks)


class Writes(Provider):
    def test_a_session_carries_its_strip_with_its_subagents_counted_in_once(self):
        self.session([text(30), text(20)])
        sub = self.transcript.with_suffix("") / "subagents" / "agent-a1.jsonl"
        sub.parent.mkdir(parents=True)
        sub.write_text("".join(json.dumps(text(s)) + "\n" for s in (10, 11, 12)))
        os.utime(sub, (time.time() - 10, time.time() - 10))
        got = self.live()
        # R15: one session on the page, not two; its subagent is part of it.
        self.assertEqual([s["id"] for s in got], [SID])
        self.assertEqual(len(got[0]["writes"]), 30)
        self.assertEqual(sum(got[0]["writes"]), 5)
        self.assertAlmostEqual(got[0]["subQuiet"], 10 / 60, delta=0.05)

    def test_a_session_with_no_transcript_reports_no_strip(self):
        (self.cfg / "sessions" / "100.json").write_text(json.dumps({
            "pid": 100, "sessionId": SID, "kind": "interactive", "entrypoint": "cli",
            "status": "idle", "procStart": "1640779", "cwd": "/tmp", "name": "Ilse"}))
        self.assertIsNone(self.live()[0]["writes"])


class WhatItWaitsOn(Provider):
    def test_a_command_in_flight_with_cpu_under_its_shell_is_seen_as_cpu(self):
        self.session([call(120)])
        worker = self.shell()
        self.live()
        self.fake.burn(worker, 500)
        got = self.live()[0]
        self.assertTrue(got["shellCpu"])
        self.assertIsNotNone(got["toolFor"])

    def test_an_mcp_server_using_cpu_under_a_session_with_a_call_in_flight_is_not_cpu(self):
        # R16: the servers run all day; they say nothing about the call.
        self.session([call(120)])
        server = self.fake.add(200, 100, cmd=NODE, ticks=10)
        self.live()
        self.fake.burn(server, 5000)
        self.assertFalse(self.live()[0]["shellCpu"])

    def test_a_shell_left_burning_after_the_call_came_back_is_not_cpu(self):
        # R16: nothing is waiting on it. The reader does not even look.
        self.session([call(120, tool_id="toolu_1"),
                      {"type": "user", "timestamp": stamp(60),
                       "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                                "content": "ok"}]}},
                      text(50)], status="idle")
        worker = self.shell()
        looks = []
        original = self.provider.shells.look
        self.provider.shells.look = lambda pid, now=None: (looks.append(pid), original(pid, now))[1]
        self.live()
        self.fake.burn(worker, 5000)
        got = self.live()[0]
        self.assertFalse(got["shellCpu"])
        self.assertEqual(looks, [])

    def test_a_background_task_with_its_own_shell_alive_is_reported(self):
        self.session([call(300), accepted(299, "toolu_1", "bk7q2m9xa")], status="idle")
        self.shell(task="bk7q2m9xa")
        got = self.live()[0]
        self.assertEqual([t["label"] for t in got["bgTasks"]], ["Run the unit tests"])
        self.assertAlmostEqual(got["bgTasks"][0]["since"], 299 / 60, delta=0.05)

    def test_a_background_task_with_no_shell_left_behind_it_is_not(self):
        # The shell died and no notice came: nothing runs, whatever the file says.
        self.session([call(300), accepted(299, "toolu_1", "bk7q2m9xa")], status="idle")
        self.assertEqual(self.live()[0]["bgTasks"], [])

    def test_a_task_a_resumed_session_never_heard_the_end_of_is_not_running(self):
        # R16: the previous process died with its shells and no notice was
        # written. The new process runs shells of its own, but none of them
        # writes to that task's output.
        self.session([call(300), accepted(299, "toolu_1", "bk7q2m9xa")], status="busy")
        self.shell()                                   # a foreground command, stdout a pipe
        self.shell(task="bz0other00", number=250)      # and some other task's shell
        self.assertEqual(self.live()[0]["bgTasks"], [])

    def test_of_two_open_tasks_only_the_one_whose_shell_lives_is_reported(self):
        self.session([call(300, tool_id="toolu_1"), accepted(299, "toolu_1", "bk7q2m9xa"),
                      call(200, tool_id="toolu_2", description="Watch the deploy"),
                      accepted(199, "toolu_2", "bm1x2y3z4")], status="idle")
        self.shell(task="bm1x2y3z4")
        self.assertEqual([t["label"] for t in self.live()[0]["bgTasks"]], ["Watch the deploy"])

    def test_a_shell_left_behind_by_a_task_that_ended_is_not_a_job(self):
        # R16: the notice closed the task; the shell that outlived it proves nothing.
        self.session([call(300), accepted(299, "toolu_1", "bk7q2m9xa"), ended("bk7q2m9xa")],
                     status="idle")
        self.shell()
        got = self.live()[0]
        self.assertEqual(got["bgTasks"], [])

    def test_a_session_whose_processes_cannot_be_read_says_nothing_rather_than_moving(self):
        # R17: the folder of the session's children is gone.
        self.session([call(300), accepted(299, "toolu_1", "bk7q2m9xa")], status="idle")
        (self.fake.root / "100" / "task" / "100" / "children").unlink()
        got = self.live()[0]
        self.assertEqual((got["bgTasks"], got["shellCpu"]), ([], False))


if __name__ == "__main__":
    unittest.main()
