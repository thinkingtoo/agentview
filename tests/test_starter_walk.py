"""Who started a process: the walk up from a `codex` process through its parents.

All of it over a fake `/proc`, never the real one. A `codex exec` run is
folded into the tile of the session that started it, so a wrong answer here
puts a run in the wrong project, and no answer puts a stray tile on the page.
R17: the walk must survive a process vanishing mid-walk, a pid the kernel
handed to somebody else, and a process that is not ours to read.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import procs


class Tree:
    """A `/proc` with just the `stat` line of each process: its parent and its start."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp())

    def add(self, pid, parent, start=1000, comm="sh", stdout=None):
        folder = self.root / str(pid)
        folder.mkdir(exist_ok=True)
        if stdout is not None:
            (folder / "fd").mkdir(exist_ok=True)
            os.symlink(stdout, folder / "fd" / "1")
        (folder / "stat").write_text(
            f"{pid} ({comm}) S {parent} 1 1 0 -1 4194304 1 0 0 0 5 0 0 0 20 0 1 0 {start} 0 0\n")
        return pid

    def chain(self, *pids):
        """pids[0] is the oldest: each one is the parent of the next, and starts later."""
        parent = 1
        for at, pid in enumerate(pids):
            self.add(pid, parent, start=1000 + at * 10)
            parent = pid
        return pids[-1]


class Walk(unittest.TestCase):
    def setUp(self):
        self.tree = Tree()

    def up(self, pid):
        return procs.ancestors(self.tree.root, pid)

    def test_the_parents_come_nearest_first_and_init_is_left_out(self):
        self.tree.add(1, 0, start=1)
        leaf = self.tree.chain(50, 100, 200, 300)
        self.assertEqual(self.up(leaf), [200, 100, 50])

    def test_a_process_whose_parent_is_init_has_no_ancestors(self):
        self.assertEqual(self.up(self.tree.add(300, 1)), [])

    def test_a_process_that_is_not_there_has_none(self):
        self.assertEqual(self.up(999), [])

    def test_a_pid_that_is_not_a_pid_has_none(self):
        for odd in (None, "abc", True, -3, 0, 1.5, [4]):
            with self.subTest(odd=odd):
                self.assertEqual(self.up(odd), [])

    def test_an_ancestor_that_is_gone_ends_the_walk_there(self):
        leaf = self.tree.chain(50, 100, 200, 300)
        (self.tree.root / "100" / "stat").unlink()
        self.assertEqual(self.up(leaf), [200])

    def test_an_ancestor_that_is_not_ours_to_read_ends_the_walk_there(self):
        leaf = self.tree.chain(50, 100, 200, 300)
        stat = self.tree.root / "100" / "stat"
        os.chmod(stat, 0)
        self.addCleanup(os.chmod, stat, 0o644)
        self.assertEqual(self.up(leaf), [200])

    def test_a_stat_line_that_makes_no_sense_ends_the_walk(self):
        leaf = self.tree.chain(50, 100, 200, 300)
        for line in ("", "garbage", "200 (sh) S", "200 (sh) S x y z", "200 (sh S 100 1"):
            with self.subTest(line=line):
                (self.tree.root / "200" / "stat").write_text(line)
                self.assertEqual(self.up(leaf), [])

    def test_a_command_with_parentheses_and_spaces_in_its_name_is_read_whole(self):
        self.tree.add(100, 1, start=1000)
        self.tree.add(200, 100, start=1010, comm="a) S 7 (b c")
        leaf = self.tree.add(300, 200, start=1020)
        self.assertEqual(self.up(leaf), [200, 100])

    def test_a_parent_that_started_after_its_child_is_a_pid_given_to_somebody_else(self):
        # R17: the real parent died, and its number now belongs to a newer process.
        leaf = self.tree.chain(50, 100, 200, 300)
        self.tree.add(200, 100, start=5000)
        self.assertEqual(self.up(leaf), [])

    def test_a_parent_that_started_at_the_same_tick_is_still_a_parent(self):
        self.tree.add(100, 1, start=1000)
        self.tree.add(200, 100, start=1000)
        self.assertEqual(self.up(200), [100])

    def test_a_child_that_changes_parent_while_it_is_looked_at_ends_the_walk(self):
        # R17: the parent exited between the two reads and the child was handed on.
        leaf = self.tree.chain(50, 100, 200, 300)
        reads, real = [], procs._read

        def racing(path):
            if str(path).endswith("/300/stat"):
                reads.append(path)
                if len(reads) == 2:
                    self.tree.add(300, 1, start=1020)
            return real(path)
        procs._read = racing
        self.addCleanup(setattr, procs, "_read", real)
        self.assertEqual(self.up(leaf), [])

    def test_a_loop_of_parents_ends_where_it_closes(self):
        self.tree.add(100, 200, start=1000)
        self.tree.add(200, 100, start=1000)
        self.assertEqual(self.up(200), [100])

    def test_a_process_that_is_its_own_parent_has_none(self):
        self.assertEqual(self.up(self.tree.add(100, 100)), [])

    def test_a_very_deep_tree_is_cut_short(self):
        leaf = self.tree.chain(*range(100, 100 + 400))
        got = self.up(leaf)
        self.assertEqual(len(got), procs.MAX_UP)
        self.assertEqual(got[0], leaf - 1)


if __name__ == "__main__":
    unittest.main()


TASK = "/home/alice/.claude/tmp/tasks/{}.output"


class Task(unittest.TestCase):
    """A background command of a Claude session writes to `tasks/<id>.output`, and
    what that command starts sits below it: so the run knows which task holds it."""

    def setUp(self):
        self.tree = Tree()

    def above(self, pid, up):
        return procs.task_above(self.tree.root, pid, up)

    def test_the_task_of_the_shell_above_a_run_is_the_one_that_holds_it(self):
        self.tree.add(100, 1, 900)
        self.tree.add(200, 100, 950, stdout=TASK.format("bg1"))
        self.tree.add(300, 200, 1000)
        self.assertEqual(self.above(300, [200, 100]), "bg1")

    def test_the_run_may_be_the_shell_itself_when_the_shell_ran_it_in_its_place(self):
        self.tree.add(100, 1, 900)
        self.tree.add(300, 100, 1000, stdout=TASK.format("bg2"))
        self.assertEqual(self.above(300, [100]), "bg2")

    def test_the_nearest_task_wins(self):
        self.tree.add(200, 1, 900, stdout=TASK.format("outer"))
        self.tree.add(250, 200, 950, stdout=TASK.format("inner"))
        self.tree.add(300, 250, 1000)
        self.assertEqual(self.above(300, [250, 200]), "inner")

    def test_a_run_under_no_task_has_none(self):
        self.tree.add(100, 1, 900, stdout="/dev/pts/3")
        self.tree.add(200, 100, 950, stdout="pipe:[4242]")
        self.tree.add(300, 200, 1000)
        self.assertIsNone(self.above(300, [200, 100]))

    def test_only_a_file_named_for_a_task_in_a_folder_of_tasks_is_one(self):
        for target in ("/home/alice/notes/bg1.output", "/home/alice/tasks/bg1.txt", "/home/alice/tasks/.output",
                       "/home/alice/tasks/bg1.output/x", "tasks/bg1.output.bak", "/"):
            with self.subTest(target=target):
                tree = Tree()
                tree.add(300, 1, 1000, stdout=target)
                self.assertIsNone(procs.task_above(tree.root, 300, []))

    def test_a_process_that_cannot_be_read_is_passed_over(self):
        self.tree.add(100, 1, 900, stdout=TASK.format("bg3"))
        self.tree.add(200, 100, 950)                                    # no fd folder at all
        self.tree.add(300, 200, 1000)
        self.assertEqual(self.above(300, [200, 999, 100]), "bg3")

    def test_a_pid_that_is_not_a_pid_is_not_asked_about(self):
        self.tree.add(300, 1, 1000, stdout=TASK.format("bg4"))
        for pid in (None, "300", True, 0, 1, -3, 2.5, [300]):
            with self.subTest(pid=pid):
                self.assertIsNone(self.above(pid, [300]))

    def test_what_is_listed_above_that_is_not_a_pid_is_passed_over(self):
        self.tree.add(300, 1, 1000)
        self.tree.add(400, 1, 900, stdout=TASK.format("bg5"))
        self.assertEqual(self.above(300, [None, "400", True, 0, 1, -2, 2.5, [400], 400]), "bg5")
        for up in (None, "400", 400, {"a": 400}):
            with self.subTest(up=up):
                self.assertIsNone(self.above(300, up))
        for text in ("400", "0400", b"400", 400.0):
            with self.subTest(text=text):
                self.assertIsNone(self.above(300, [text]))

    def test_a_process_that_is_not_there_has_no_task(self):
        self.assertIsNone(self.above(999, [998]))
