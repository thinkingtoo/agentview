"""Codex as a provider.

Codex gives the disk and withholds the state: a SQLite row per thread, a
JSONL rollout per session, and a lock file that appears when a session
starts -- and stays behind after a SIGKILL. So a session is live when its
lock exists *and* a process holds its rollout open, which `/proc` can say.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import base
from providers.codex import CodexProvider

TID = "01a0c8bb-a5c9-77c1-a3d6-975d3121bd61"
T0 = "2026-09-22T10:48:56.218Z"
T0_MS = 1790074136218


def rec(ts, kind, **payload):
    return {"timestamp": ts, "type": kind, "payload": payload}


def meta(ts=T0, cwd="/home/alice/Projects/maple", source="exec"):
    return rec(ts, "session_meta", id=TID, cwd=cwd, source=source, originator="codex_exec")


class Home:
    """A fake `~/.codex` and a fake `/proc`, built in a temp dir."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp())
        self.codex = self.root / ".codex"
        self.proc = self.root / "proc"
        (self.codex / "thread-writer-locks").mkdir(parents=True)
        self.day = self.codex / "sessions" / "2026" / "09" / "22"
        self.day.mkdir(parents=True)
        self.proc.mkdir()
        self.db = self.codex / "state_5.sqlite"
        con = sqlite3.connect(self.db)
        con.execute("""create table threads (id text primary key, rollout_path text,
            cwd text, title text, git_branch text, model text, tokens_used integer,
            created_at_ms integer, updated_at_ms integer, source text)""")
        con.commit()
        con.close()

    def rollout(self, tid=TID, records=(), mode="w"):
        path = self.day / f"rollout-2026-09-22T12-48-56-{tid}.jsonl"
        with path.open(mode, encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        return path

    def thread(self, tid=TID, **cols):
        row = {"id": tid, "rollout_path": str(self.rollout(tid, [], "a")),
               "cwd": "/home/alice/Projects/maple", "title": "Review the plan",
               "git_branch": "dev", "model": "gpt-5.6-sol", "tokens_used": 65290,
               "created_at_ms": T0_MS, "updated_at_ms": T0_MS, "source": "exec"}
        row.update(cols)
        con = sqlite3.connect(self.db)
        con.execute(f"insert or replace into threads ({','.join(row)}) values "
                    f"({','.join('?' * len(row))})", list(row.values()))
        con.commit()
        con.close()

    def lock(self, tid=TID):
        (self.codex / "thread-writer-locks" / f"{tid}.lock").touch()

    def holder(self, pid, tid=TID, comm="codex", fd=48):
        d = self.proc / str(pid)
        (d / "fd").mkdir(parents=True, exist_ok=True)
        (d / "comm").write_text(comm + "\n")
        os.symlink(self.rollout(tid, [], "a"), d / "fd" / str(fd))
        os.symlink(self.codex / "thread-writer-locks" / f"{tid}.lock", d / "fd" / "41")

    def provider(self):
        return CodexProvider(home=self.codex, proc=self.proc)


class Liveness(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.home.thread()

    def test_a_lock_with_a_process_behind_it_is_a_live_session_with_a_pid(self):
        self.home.lock()
        self.home.holder(4242)
        got = self.home.provider().live()
        self.assertEqual([(s["id"], s["pid"]) for s in got], [(TID, 4242)])

    def test_a_lock_nobody_holds_is_an_orphan(self):
        # Verified 2026-09-22: a SIGKILL leaves the lock file behind.
        self.home.lock()
        self.assertEqual(self.home.provider().live(), [])

    def test_no_locks_means_nothing_is_read_at_all(self):
        os.remove(self.home.db)          # would raise if touched
        self.assertEqual(self.home.provider().live(), [])

    def test_a_process_that_cannot_be_looked_into_degrades_to_no_pid(self):
        # hidepid, a container, another user's process: the lock is the only
        # evidence, and the session shows without a jump. No pid is invented.
        self.home.lock()
        self.home.holder(4242)
        os.chmod(self.home.proc / "4242" / "fd", 0)
        self.addCleanup(os.chmod, self.home.proc / "4242" / "fd", 0o755)
        got = self.home.provider().live()
        self.assertEqual([(s["id"], s.get("pid")) for s in got], [(TID, None)])

    def test_the_holder_is_remembered_so_proc_is_not_walked_every_poll(self):
        self.home.lock()
        self.home.holder(4242)
        p = self.home.provider()
        p.live()
        walked = []
        p._codex_pids = lambda: walked.append(1) or []
        self.assertEqual(p.live()[0]["pid"], 4242)
        self.assertEqual(walked, [])

    def test_a_remembered_holder_that_let_go_is_checked_again(self):
        self.home.lock()
        self.home.holder(4242)
        p = self.home.provider()
        p.live()
        os.remove(self.home.proc / "4242" / "fd" / "48")     # the process moved on
        self.assertEqual(p.live(), [])


class Rollout(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.home.thread()
        self.home.lock()
        self.home.holder(4242)

    def one(self, *records, mode="w"):
        self.home.rollout(records=records, mode=mode)
        got = self.home.provider().live()
        self.assertEqual(len(got), 1)
        return got[0]

    def test_task_started_is_busy_since_that_moment(self):
        s = self.one(meta(), rec(T0, "event_msg", type="task_started"))
        self.assertEqual(s["status"], "busy")
        self.assertEqual(s["updatedAt"], T0_MS)

    def test_task_complete_is_idle_with_what_it_said(self):
        s = self.one(meta(), rec(T0, "event_msg", type="task_started"),
                     rec("2026-09-22T10:51:54.675Z", "event_msg", type="agent_message",
                         message="Done.\n\nMerge it?"),
                     rec("2026-09-22T10:51:54.703Z", "event_msg", type="task_complete"))
        self.assertEqual(s["status"], "idle")
        self.assertEqual(s["updatedAt"], 1790074314703)
        self.assertEqual(s["said"], "Done.\n\nMerge it?")

    def test_an_interrupted_turn_is_idle_too(self):
        s = self.one(meta(), rec(T0, "event_msg", type="task_started"),
                     rec("2026-09-22T10:49:00.000Z", "event_msg", type="turn_aborted",
                         reason="interrupted"))
        self.assertEqual(s["status"], "idle")

    def test_a_new_prompt_forgets_the_last_thing_it_said(self):
        s = self.one(meta(), rec(T0, "event_msg", type="agent_message", message="Done."),
                     rec("2026-09-22T10:52:00.000Z", "event_msg", type="user_message",
                         message="now the other thing"))
        self.assertEqual(s["said"], "")
        self.assertEqual(s["prompt"], "now the other thing")

    def test_facts_from_the_thread_table(self):
        s = self.one(meta())
        self.assertEqual(s["branch"], "dev")
        self.assertEqual(s["title"], "Review the plan")
        self.assertEqual(s["kind"], "exec")
        self.assertEqual(s["cwd"], "/home/alice/Projects/maple")
        self.assertEqual(s["startedAt"], T0_MS)
        self.assertEqual(s["extras"]["model"], "gpt-5.6-sol")

    def test_an_interactive_session_is_interactive(self):
        self.home.thread(source="cli")
        s = self.one(meta(source="cli"))
        self.assertEqual(s["kind"], "interactive")

    def test_only_the_new_lines_are_read_the_second_time(self):
        self.one(meta(), rec(T0, "event_msg", type="task_started"))
        p = self.home.provider()
        p.live()
        reads = []
        original = base.read_from
        base.read_from = lambda path, off: (reads.append(off), original(path, off))[1]
        try:
            self.home.rollout(records=[rec("2026-09-22T10:52:00.000Z", "event_msg",
                                           type="task_complete")], mode="a")
            self.assertEqual(p.live()[0]["status"], "idle")
        finally:
            base.read_from = original
        self.assertTrue(reads and reads[0] > 0, f"read again from {reads}")

    def test_a_row_the_table_does_not_have_yet_still_shows(self):
        # The rollout is written at start-up, before the model answers; the
        # table row may lag a poll behind it.
        con = sqlite3.connect(self.home.db)
        con.execute("delete from threads")
        con.commit()
        s = self.one(meta(cwd="/home/alice/Projects/pmd"))
        self.assertEqual(s["cwd"], "/home/alice/Projects/pmd")
        self.assertEqual(s["branch"], "")


if __name__ == "__main__":
    unittest.main()
