"""Which peer records are still sessions.

Claude Code writes a file per session under `~/.claude/sessions/` and leaves
it there. For a session that exits, the pid goes with it and the file stops
mattering. For a session whose window was closed under it, the pid stays:
orphaned, stopped on its first read from a terminal that is gone, answering
signal 0 exactly like a working one. That is the case these cover -- Petra,
sixteen hours on the page in the `waiting` her last turn left behind.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import base, claude

# `/dev/pts/54` and `/dev/tty1` as the kernel numbers them, and a real stat
# line from a stopped orphan: `claude`, state T, seventh field 0.
PTS_54 = 34870
TTY1 = 1025
STOPPED = ("742884 (claude) T 1859 742884 742539 0 -1 4194304 1 0 0 0 "
           "1 2 0 0 20 0 15 0 1640779 0 0")


class Stat(unittest.TestCase):
    def setUp(self):
        self.proc = Path(tempfile.mkdtemp())

    def write(self, pid, line):
        (self.proc / str(pid)).mkdir()
        (self.proc / str(pid) / "stat").write_text(line + "\n")

    def test_the_terminal_is_read_out_of_the_stat_line(self):
        self.write(1, STOPPED.replace(" T 1859 742884 742539 0 ",
                                      f" S 1859 742884 742539 {PTS_54} "))
        self.assertEqual(base.controlling_tty(1, self.proc), PTS_54)
        self.assertTrue(base.on_a_terminal(1, self.proc))

    def test_a_process_with_no_terminal_reads_zero(self):
        self.write(1, STOPPED)
        self.assertEqual(base.controlling_tty(1, self.proc), 0)
        self.assertFalse(base.on_a_terminal(1, self.proc))

    def test_a_command_full_of_brackets_does_not_shift_the_fields(self):
        # The second field is the command, unquoted and unescaped. Counting
        # from the left puts the terminal wherever the parentheses happen to
        # land; counting from the last one is why this passes.
        self.write(1, STOPPED.replace("(claude)", "(cl (a) ud e)")
                   .replace(" T 1859 742884 742539 0 ",
                            f" S 1859 742884 742539 {PTS_54} "))
        self.assertEqual(base.controlling_tty(1, self.proc), PTS_54)

    def test_a_process_that_is_gone_answers_nothing_rather_than_none_terminal(self):
        # Absent is not "has no terminal": one drops the session, the other
        # is a question `/proc` declined to answer.
        self.assertIsNone(base.controlling_tty(404, self.proc))

    def test_a_terminal_that_is_not_a_pty_is_no_route_to_a_window(self):
        # `/dev/tty1` is a real console. There is no emulator to raise.
        self.write(1, STOPPED.replace(" T 1859 742884 742539 0 ",
                                      f" S 1859 742884 742539 {TTY1} "))
        self.assertFalse(base.on_a_terminal(1, self.proc))


class Present(unittest.TestCase):
    """Which peer records the Claude provider lists, over a fake `/proc`.

    The rule itself is cc-agent-names' registry (vendored as
    `providers/registry.py`, tested there); these hold the provider to it.
    """

    def setUp(self):
        base_dir = Path(tempfile.mkdtemp())
        self.cfg, self.proc = base_dir / "claude", base_dir / "proc"
        (self.cfg / "sessions").mkdir(parents=True)
        self.proc.mkdir()

    def session(self, pid, sid, tty=PTS_54, state="S", start="1640779", **over):
        fields = STOPPED.replace(" T 1859 742884 742539 0 ",
                                 f" {state} 1859 742884 742539 {tty} ")
        (self.proc / str(pid)).mkdir()
        (self.proc / str(pid) / "stat").write_text(fields.replace("742884 (", f"{pid} (", 1) + "\n")
        rec = {"pid": pid, "sessionId": sid, "kind": "interactive", "entrypoint": "cli",
               "status": "waiting", "procStart": start, "cwd": "/tmp", "name": sid}
        rec.update(over)
        (self.cfg / "sessions" / f"{pid}.json").write_text(__import__("json").dumps(rec))

    def ids(self):
        return sorted(s["id"] for s in claude.ClaudeProvider(self.cfg, proc=self.proc).live())

    def test_a_session_on_its_terminal_is_there(self):
        self.session(10, "on-terminal")
        self.assertEqual(self.ids(), ["on-terminal"])

    def test_a_pid_that_is_gone_is_gone(self):
        self.session(10, "here")
        (self.cfg / "sessions" / "11.json").write_text('{"pid": 11, "sessionId": "gone", "procStart": "1"}')
        self.assertEqual(self.ids(), ["here"])

    def test_a_reused_pid_is_not_the_session_it_used_to_be(self):
        self.session(10, "reused", start="999")
        self.assertEqual(self.ids(), [])

    def test_a_terminal_session_without_a_terminal_is_over(self):
        # Petra: the pid still answers, stopped, with no terminal left.
        self.session(10, "orphan", tty=0, state="T")
        self.assertEqual(self.ids(), [])

    def test_a_headless_session_never_had_a_terminal_to_lose(self):
        # A routine runs from a timer with no terminal at all. Asking it the
        # question would wipe every routine off the page.
        self.session(10, "routine", tty=0, entrypoint="sdk-cli")
        self.assertEqual(self.ids(), ["routine"])

    def test_find_answers_only_for_a_live_session(self):
        self.session(10, "orphan", tty=0)
        self.session(12, "on-terminal")
        provider = claude.ClaudeProvider(self.cfg, proc=self.proc)
        self.assertIsNone(provider.find("orphan"))
        self.assertEqual(provider.find("on-terminal")["id"], "on-terminal")


if __name__ == "__main__":
    unittest.main()
