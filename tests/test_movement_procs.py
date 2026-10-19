"""Which commands run under a session, and whether any of them is using CPU.

All of it over a fake `/proc`, never the real one: a test must not depend on
what happens to be running on the machine that runs it. The fake keeps the
shape the kernel gives: a `stat` line, a NUL-separated `cmdline`, and the
children of a process in `task/<pid>/children`.

R16 (an unrelated descendant, or a shell left behind, must not make a session
look alive) and R17 (a process vanishing mid-walk, pid reuse, a permission
error) are the cases that matter; each test says which it is.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import procs

SESSION = 100
OUT = "/tmp/claude-1000/-home-alice-proj/11111111-aaaa/tasks/%s.output"
BASH = ("bash\0-c\0-l\0source /home/alice/.claude/shell-snapshots/snapshot-bash-1.sh"
        " && eval 'run it' < /dev/null\0")
NODE = "node\0/opt/tools/some-mcp-server.js\0"


class FakeProc:
    """A `/proc` with just enough in it."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp())
        self.parent = {}

    def add(self, pid, parent=None, cmd="sleep\0", ticks=0, start=1000, out=None):
        """`out` is where its standard output goes: a background task's shell
        writes to `.../tasks/<id>.output`."""
        folder = self.root / str(pid)
        (folder / "task" / str(pid)).mkdir(parents=True)
        if out:
            (folder / "fd").mkdir()
            (folder / "fd" / "1").symlink_to(out)
        (folder / "task" / str(pid) / "children").write_text("")
        (folder / "cmdline").write_bytes(cmd.encode())
        self.burn(pid, ticks, start)
        if parent is not None:
            self.parent[pid] = parent
            children = self.root / str(parent) / "task" / str(parent) / "children"
            children.write_text(children.read_text() + f"{pid} ")
        return pid

    def burn(self, pid, ticks, start=1000):
        """The process has used `ticks` of CPU so far (user plus system)."""
        (self.root / str(pid) / "stat").write_text(
            f"{pid} (a (b) c) S 1 1 1 0 -1 4194304 1 0 0 0 {ticks} 0 0 0 20 0 1 0 {start} 0 0\n")

    def vanish(self, pid):
        """The process exits, but whoever listed it as a child read that
        list a moment earlier."""
        shutil.rmtree(self.root / str(pid))


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = FakeProc()
        self.fake.add(SESSION, cmd="claude\0")
        self.watch = procs.Shells(proc=self.fake.root)

    def look(self, at):
        return self.watch.look(SESSION, now=at)


class Shells(Base):
    def test_a_command_the_session_runs_is_a_shell_under_it(self):
        self.fake.add(200, SESSION, cmd=BASH)
        self.assertEqual(self.look(0)["shells"], 1)

    def test_a_shell_whose_command_is_burning_cpu_is_cpu(self):
        shell = self.fake.add(200, SESSION, cmd=BASH)
        test_run = self.fake.add(300, shell, cmd="python3\0-m\0pytest\0", ticks=10)
        self.look(0)                               # the first sight has nothing to compare with
        self.fake.burn(test_run, 400)
        self.assertEqual(self.look(3), {"shells": 1, "cpu": True, "tasks": []})

    def test_the_first_sight_is_never_cpu(self):
        shell = self.fake.add(200, SESSION, cmd=BASH)
        self.fake.add(300, shell, cmd="python3\0", ticks=9999)
        # Nothing to compare with yet: not "uses none" (False), which takes a second look.
        self.assertEqual(self.look(0), {"shells": 1, "cpu": None, "tasks": []})

    def test_a_shell_that_is_alive_but_idle_is_not_cpu(self):
        shell = self.fake.add(200, SESSION, cmd=BASH)
        self.fake.add(300, shell, cmd="sleep\0600\0", ticks=1)
        self.look(0)
        self.assertEqual(self.look(3), {"shells": 1, "cpu": False, "tasks": []})

    def test_cpu_is_remembered_for_a_few_seconds_so_a_busy_wait_does_not_flicker(self):
        shell = self.fake.add(200, SESSION, cmd=BASH)
        worker = self.fake.add(300, shell, cmd="curl\0", ticks=10)
        self.look(0)
        self.fake.burn(worker, 20)
        self.assertTrue(self.look(3)["cpu"])
        self.assertTrue(self.look(6)["cpu"])           # no new ticks, but 3 s after the last
        self.assertFalse(self.look(30)["cpu"])         # long enough for it to count as stopped

    def test_a_sample_from_long_ago_is_not_a_baseline(self):
        # Looks are skipped for sessions that have nothing to wait on. When
        # one is looked at again an hour later, the ticks since then say
        # nothing about the last few seconds.
        shell = self.fake.add(200, SESSION, cmd=BASH)
        worker = self.fake.add(300, shell, cmd="python3\0", ticks=10)
        self.look(0)
        self.fake.burn(worker, 5000)
        self.assertFalse(self.look(3600)["cpu"])


class UnrelatedProcesses(Base):
    """R16: what runs under a session but is not a command it is waiting on."""

    def test_an_mcp_server_using_cpu_is_not_a_command_the_session_waits_on(self):
        server = self.fake.add(200, SESSION, cmd=NODE, ticks=10)
        helper = self.fake.add(201, server, cmd="python3\0helper.py\0", ticks=10)
        self.look(0)
        self.fake.burn(server, 900)
        self.fake.burn(helper, 900)
        self.assertEqual(self.look(3), {"shells": 0, "cpu": False, "tasks": []})

    def test_a_shell_snapshot_deeper_than_a_direct_child_is_not_the_session_running_it(self):
        server = self.fake.add(200, SESSION, cmd=NODE)
        shell = self.fake.add(201, server, cmd=BASH)
        worker = self.fake.add(202, shell, cmd="python3\0", ticks=1)
        self.look(0)
        self.fake.burn(worker, 900)
        self.assertEqual(self.look(3), {"shells": 0, "cpu": False, "tasks": []})

    def test_a_process_of_the_same_name_elsewhere_on_the_machine_is_not_counted(self):
        init = self.fake.add(1, cmd="init\0")
        self.fake.add(500, init, cmd=BASH, ticks=1)
        self.look(0)
        self.fake.burn(500, 999)
        self.assertEqual(self.look(3), {"shells": 0, "cpu": False, "tasks": []})


class Races(Base):
    """R17: /proc changes under the walk. None of this raises, and none of it
    is ever read as 'moving'."""

    def test_a_process_that_exits_between_the_list_and_the_read_is_skipped(self):
        shell = self.fake.add(200, SESSION, cmd=BASH)
        self.fake.add(300, shell, cmd="python3\0", ticks=1)
        self.fake.vanish(300)
        self.assertEqual(self.look(0), {"shells": 1, "cpu": None, "tasks": []})

    def test_a_shell_that_exits_between_the_list_and_the_read_is_not_a_shell(self):
        self.fake.add(200, SESSION, cmd=BASH)
        self.fake.vanish(200)
        self.assertEqual(self.look(0), {"shells": 0, "cpu": False, "tasks": []})

    def test_a_reused_pid_is_a_different_process_and_its_ticks_are_not_a_continuation(self):
        shell = self.fake.add(200, SESSION, cmd=BASH)
        self.fake.add(300, shell, cmd="python3\0", ticks=10, start=1000)
        self.look(0)
        # 300 exits and the kernel hands the number to a new process, which
        # has already used more than the old one had by the second look.
        self.fake.burn(300, 7000, start=2222)
        self.assertEqual(self.look(3), {"shells": 1, "cpu": False, "tasks": []})

    def test_the_session_itself_being_gone_is_no_answer_rather_than_an_empty_one(self):
        self.fake.vanish(SESSION)
        self.assertIsNone(self.look(0))

    def test_a_kernel_without_children_files_is_no_answer(self):
        (self.fake.root / str(SESSION) / "task" / str(SESSION) / "children").unlink()
        self.assertIsNone(self.look(0))

    def test_a_stat_line_that_makes_no_sense_is_no_cpu(self):
        shell = self.fake.add(200, SESSION, cmd=BASH)
        worker = self.fake.add(300, shell, cmd="python3\0", ticks=1)
        self.look(0)
        (self.fake.root / str(worker) / "stat").write_text("300 (python3) S garbage\n")
        self.assertEqual(self.look(3), {"shells": 1, "cpu": False, "tasks": []})

    @unittest.skipIf(os.geteuid() == 0, "root can read anything")
    def test_a_process_we_may_not_read_is_no_cpu_and_no_crash(self):
        shell = self.fake.add(200, SESSION, cmd=BASH)
        worker = self.fake.add(300, shell, cmd="python3\0", ticks=1)
        self.look(0)
        self.fake.burn(worker, 900)
        stat = self.fake.root / str(worker) / "stat"
        stat.chmod(0)
        self.addCleanup(stat.chmod, 0o644)
        self.assertEqual(self.look(3), {"shells": 1, "cpu": False, "tasks": []})

    def test_a_runaway_tree_is_walked_only_so_far(self):
        shell = self.fake.add(200, SESSION, cmd=BASH)
        for n in range(procs.MAX_WALK * 3):
            self.fake.add(1000 + n, shell, cmd="sleep\0", ticks=1)
        self.look(0)
        walked = [p for p in self.fake.root.iterdir() if p.name.isdigit()]
        self.assertGreater(len(walked), procs.MAX_WALK)
        self.assertLessEqual(len(self.watch.last), procs.MAX_WALK)


class BackgroundOutputs(Base):
    """A background task's shell writes to the task's own output file. That
    ties a task id to the very process that runs it, so a shell that belongs
    to something else cannot stand in for it."""

    def tasks(self):
        return self.look(0)["tasks"]

    def test_a_shell_writing_to_a_task_output_file_is_that_task_running(self):
        self.fake.add(200, SESSION, cmd=BASH, out=OUT % "bk7q2m9xa")
        self.assertEqual(self.tasks(), ["bk7q2m9xa"])

    def test_two_shells_are_two_tasks(self):
        self.fake.add(200, SESSION, cmd=BASH, out=OUT % "bk7q2m9xa")
        self.fake.add(201, SESSION, cmd=BASH, out=OUT % "bm1x2y3z4")
        self.assertEqual(sorted(self.tasks()), ["bk7q2m9xa", "bm1x2y3z4"])

    def test_a_command_in_the_foreground_has_no_task(self):
        self.fake.add(200, SESSION, cmd=BASH, out="pipe:[12345]")
        self.assertEqual(self.tasks(), [])

    def test_a_file_that_is_not_a_task_output_is_not_one(self):
        self.fake.add(200, SESSION, cmd=BASH, out="/tmp/build.log")
        self.fake.add(201, SESSION, cmd=BASH, out="/tmp/other/tasks/notes.txt")
        self.fake.add(202, SESSION, cmd=BASH, out="/tmp/build/bk7q2m9xa.output")
        self.assertEqual(self.tasks(), [])

    def test_an_output_file_held_by_a_process_that_is_no_shell_of_the_session_is_not_its_task(self):
        # R16: an MCP server that happens to log to a file of that name.
        self.fake.add(200, SESSION, cmd=NODE, out=OUT % "bk7q2m9xa")
        self.assertEqual(self.tasks(), [])

    def test_a_shell_whose_output_cannot_be_read_is_just_not_a_task(self):
        # R17: the descriptor is gone, or not ours.
        shell = self.fake.add(200, SESSION, cmd=BASH, out=OUT % "bk7q2m9xa")
        (self.fake.root / str(shell) / "fd" / "1").unlink()
        self.assertEqual(self.look(0), {"shells": 1, "cpu": None, "tasks": []})


if __name__ == "__main__":
    unittest.main()
