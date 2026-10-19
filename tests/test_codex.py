"""Codex as a provider.

Codex gives the disk and withholds the state: a SQLite row per thread, a
JSONL rollout per session, and a lock file that appears when a session
starts -- and stays behind after a SIGKILL. So a session is live when its
lock exists *and* a process holds its rollout open, which `/proc` can say.
"""
import datetime
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
from providers import base
from providers import codex
from providers.codex import CodexProvider
import test_columns

TID = "01a0c8bb-a5c9-77c1-a3d6-975d3121bd61"
T0 = "2026-09-22T10:48:56.218Z"
T0_MS = 1790074136218


def rec(ts, kind, **payload):
    return {"timestamp": ts, "type": kind, "payload": payload}


def stamp(seconds):
    """An epoch in seconds as a rollout writes it: ISO, milliseconds, a Z."""
    when = datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc)
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


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

    def stat(self, pid, parent, start=1000):
        """The `stat` line of a process: who its parent is and when it started."""
        folder = self.proc / str(pid)
        folder.mkdir(exist_ok=True)
        (folder / "stat").write_text(
            f"{pid} (codex) S {parent} 1 1 0 -1 4194304 1 0 0 0 5 0 0 0 20 0 1 0 {start} 0 0\n")

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


class Fixture(unittest.TestCase):
    """One live exec thread, held by a process, whose rollout a test writes."""

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


class Rollout(Fixture):

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


class Reviews(Fixture):
    """A `codex exec review` run writes a thread of its own, whose `source` is an
    object, not a word (238 of 1,813 rollouts here). One such thread live must
    not take the provider down with it."""

    def test_a_review_subagent_thread_is_a_review_and_the_provider_survives_it(self):
        self.home.thread(source='{"subagent":"review"}')
        s = self.one(meta(source={"subagent": "review"}))
        self.assertEqual(s["kind"], "review")

    def test_an_object_source_the_provider_has_not_met_is_still_a_kind(self):
        self.home.thread(source='{"something":["else"]}')
        s = self.one(meta(source={"something": ["else"]}))
        self.assertEqual(s["kind"], "?")


class Writes(Fixture):
    """The strip: 30 per-minute counts of the records the rollout wrote, oldest
    first, this minute last. Every persisted record is stamped, and the file
    is flushed on each append, so the stamps are when the session wrote."""

    NOW = 1_790_000_020.0     # 40 s into a minute: this minute began at NOW - 40

    def writes(self, *ago, now=None):
        """The strip after records written `ago` seconds before NOW."""
        records = [meta(ts=stamp(self.NOW - 3 * 3600))]
        records += [rec(stamp(self.NOW - a), "event_msg", type="token_count") for a in ago]
        self.home.rollout(records=records)
        p = self.home.provider()
        p.clock = lambda: self.NOW if now is None else now
        got = p.live()
        self.assertEqual(len(got), 1)
        return got[0]["writes"]

    def test_a_session_whose_rollout_is_not_there_has_no_strip_rather_than_zeros(self):
        os.chmod(self.home.proc / "4242" / "fd", 0)          # not held: found by its date, and it is not there
        self.addCleanup(os.chmod, self.home.proc / "4242" / "fd", 0o755)
        for path in self.home.day.glob("*.jsonl"):
            path.unlink()
        con = sqlite3.connect(self.home.db)
        con.execute("delete from threads")
        con.commit()
        con.close()
        got = self.home.provider().live()
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0]["writes"])

    def test_a_big_rollout_read_from_its_tail_does_not_know_the_minutes_before_it(self):
        filler = "x" * 100
        records = [meta(ts=stamp(self.NOW - 3 * 3600))]
        records += [rec(stamp(self.NOW - 1700 + i * 0.065), "event_msg", type="token_count", pad=filler)
                    for i in range(30000)]
        self.home.rollout(records=records)
        self.assertGreater(os.path.getsize(next(self.home.day.glob("*.jsonl"))), 2_000_000)
        p = self.home.provider()
        p.clock = lambda: self.NOW
        got = p.live()[0]["writes"]
        self.assertIsNone(got[0])
        self.assertIsInstance(got[-1], int)

    def test_the_strip_has_thirty_slots_with_this_minute_last(self):
        got = self.writes(10, 20, 75, 75, 75)
        self.assertEqual(len(got), 30)
        self.assertEqual((got[-1], got[-2], sum(got)), (2, 3, 5))

    def test_a_record_older_than_thirty_minutes_is_not_in_it(self):
        got = self.writes(29 * 60 + 10, 29 * 60 + 50)
        self.assertEqual((got[0], sum(got)), (1, 1))

    def test_a_session_quiet_for_an_hour_has_a_strip_of_zeros(self):
        self.assertEqual(self.writes(), [0] * 30)

    def test_a_record_with_no_stamp_is_not_a_write(self):
        records = [meta(ts=stamp(self.NOW - 3 * 3600)),
                   {"type": "event_msg", "payload": {"type": "token_count"}},
                   rec("not a time", "event_msg", type="token_count")]
        self.home.rollout(records=records)
        p = self.home.provider()
        p.clock = lambda: self.NOW
        self.assertEqual(p.live()[0]["writes"], [0] * 30)

    def test_only_the_new_records_are_counted_the_second_time(self):
        self.writes(10)
        p = self.home.provider()
        p.clock = lambda: self.NOW
        p.live()
        self.home.rollout(records=[rec(stamp(self.NOW - 5), "event_msg", type="token_count")], mode="a")
        self.assertEqual(p.live()[0]["writes"][-1], 2)
        self.assertEqual(p.live()[0]["writes"][-1], 2)


LIMIT = "You've hit your usage limit. Upgrade or try again at %s."
ERR_AT = "2026-10-19T12:00:00.000Z"          # 1792411200000, a Monday


def done(ts=ERR_AT, **error):
    """A turn that ended, with the error that ended it if there is one."""
    return rec(ts, "event_msg", type="task_complete", **({"error": error} if error else {}))


class Failures(Fixture):
    """Limit and Error are what the last turn ended in: `task_complete` with an
    `error` object holding `message` and `codex_error_info`. It is the last
    record of the file when it happens, and gone with the next turn."""

    def setUp(self):
        super().setUp()
        was = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        self.addCleanup(lambda: (os.environ.pop("TZ") if was is None else os.environ.__setitem__("TZ", was),
                                 time.tzset()))

    def failure(self, *records):
        return self.one(meta(), rec(T0, "event_msg", type="task_started"), *records)["failure"]

    def limit(self, when):
        return self.failure(done(message=LIMIT % when, codex_error_info="usage_limit_exceeded"))

    def test_a_usage_limit_is_a_limit_with_the_words_it_came_with(self):
        got = self.limit("2:35 PM")
        self.assertEqual(got, {"kind": "limit", "type": "usage_limit_exceeded", "status": None,
                               "text": LIMIT % "2:35 PM", "at": 1792411200000,
                               "resetsAt": 1792420500000})

    def test_a_reset_time_that_is_already_past_today_is_tomorrow_s(self):
        self.assertEqual(self.limit("2:35 AM")["resetsAt"], 1792463700000)

    def test_a_reset_time_may_name_its_day(self):
        self.assertEqual(self.limit("Oct 21st, 2026 3:14 AM")["resetsAt"], 1792552440000)

    def test_twelve_in_the_morning_is_midnight_and_twelve_in_the_afternoon_is_noon(self):
        self.assertEqual(self.limit("12:05 AM")["resetsAt"], 1792368300000 + 86400000)   # tomorrow, 00:05
        self.assertEqual(self.limit("12:30 PM")["resetsAt"], 1792413000000)

    def test_a_reset_time_that_is_this_very_minute_is_today_s(self):
        # Codex writes the minute, not the second: a refusal at 12:00:40 for 12:00:50 says "12:00 PM".
        for stamp in ("12:00:00.000", "12:00:10.000", "12:00:59.900"):
            with self.subTest(stamp=stamp):
                got = self.failure(done(ts=f"2026-10-19T{stamp}Z", message=LIMIT % "12:00 PM",
                                        codex_error_info="usage_limit_exceeded"))
                self.assertEqual(got["resetsAt"], 1792411200000)

    def test_a_reset_time_that_was_the_minute_before_is_tomorrow_s(self):
        got = self.failure(done(ts="2026-10-19T12:01:10.000Z", message=LIMIT % "12:00 PM",
                                codex_error_info="usage_limit_exceeded"))
        self.assertEqual(got["resetsAt"], 1792411200000 + 86400000)

    def test_the_reset_time_is_read_in_the_time_of_the_machine(self):
        os.environ["TZ"] = "CET-1CEST,M3.5.0,M10.5.0/3"         # Brussels: UTC+2 until Oct 25
        time.tzset()
        self.assertEqual(self.limit("2:35 PM")["resetsAt"], 1792420500000 - 2 * 3600000)

    def test_a_limit_that_names_no_time_has_none(self):
        got = self.failure(done(message="You've hit your usage limit.", codex_error_info="usage_limit_exceeded"))
        self.assertEqual((got["kind"], got["resetsAt"]), ("limit", None))

    def test_a_time_that_cannot_be_is_none(self):
        for when in ("25:99 PM", "13:00 PM", "3:75 PM", "0:30 AM", "Foo 3rd, 2026 3:14 AM", "Feb 31st, 2026 3:14 AM"):
            with self.subTest(when=when):
                self.assertIsNone(self.limit(when)["resetsAt"])

    def test_any_other_error_is_an_error_with_its_type(self):
        got = self.failure(done(message="The servers are busy.", codex_error_info="server_overloaded"))
        self.assertEqual({k: got[k] for k in ("kind", "type", "status", "text", "resetsAt")},
                         {"kind": "error", "type": "server_overloaded", "status": None,
                          "text": "The servers are busy.", "resetsAt": None})

    def test_an_error_that_carries_a_status_says_it(self):
        got = self.failure(done(message="Bad gateway.",
                                codex_error_info={"http_connection_failed": {"http_status_code": 502}}))
        self.assertEqual((got["kind"], got["type"], got["status"]), ("error", "http_connection_failed", 502))

    def test_an_error_with_no_info_is_an_error_with_no_type(self):
        got = self.failure(done(message="Something broke."))
        self.assertEqual((got["kind"], got["type"], got["status"]), ("error", "", None))

    def test_an_error_that_is_not_an_object_is_no_error(self):
        for odd in ("boom", 7, ["x"], True):
            with self.subTest(odd=odd):
                self.assertIsNone(self.failure(rec(ERR_AT, "event_msg", type="task_complete", error=odd)))

    def test_a_turn_that_ended_well_has_none(self):
        self.assertIsNone(self.failure(done()))

    def test_the_next_turn_clears_it(self):
        got = self.failure(done(message=LIMIT % "2:35 PM", codex_error_info="usage_limit_exceeded"),
                           rec("2026-10-19T12:05:00.000Z", "event_msg", type="task_started"))
        self.assertIsNone(got)

    def test_words_that_just_fit_are_not_cut_and_one_more_is(self):
        fits = self.failure(done(message="y" * 200, codex_error_info="other"))
        over = self.failure(done(message="y" * 201, codex_error_info="other"))
        self.assertEqual(fits["text"], "y" * 200)
        self.assertEqual(over["text"], "y" * 199 + "…")

    def test_the_words_are_one_line_cut_to_what_a_tile_holds(self):
        got = self.failure(done(message="Too\n  many\tspaces " + "x" * 400, codex_error_info="other"))
        self.assertTrue(got["text"].startswith("Too many spaces xxx") and len(got["text"]) == 200
                        and got["text"].endswith("…"), got["text"])

    def test_a_stamp_that_is_not_a_time_gives_no_moment(self):
        got = self.failure(done(ts="soon", message="x", codex_error_info="other"))
        self.assertIsNone(got["at"])


def policy(ts, how="on-request"):
    """The record a turn opens with: what it may do without asking."""
    return rec(ts, "turn_context", approval_policy=how)


def call(ts, cid, name="exec_command", escalate=False, **args):
    """A call the model made. `arguments` is a JSON text, as Codex writes it."""
    if escalate:
        args["sandbox_permissions"] = "require_escalated"
    return rec(ts, "response_item", type="function_call", name=name,
               arguments=json.dumps(args), call_id=cid)


def answer(ts, cid, kind="function_call_output"):
    return rec(ts, "response_item", type=kind, call_id=cid, output="ok")


T1, T2, T3 = ("2026-09-22T10:49:00.000Z", "2026-09-22T10:49:30.000Z", "2026-09-22T10:50:00.000Z")


class Approvals(Fixture):
    """A request for approval is never written to a rollout, but the call it is
    about is: an `exec_command` that asks to leave the sandbox, with no output
    until the person decides. Inferred, so it is only ever believed of a session
    that can ask, in the middle of a turn."""

    def turn(self, *records, how="on-request"):
        return self.one(meta(), rec(T0, "event_msg", type="task_started"), policy(T0, how), *records)

    def test_a_call_that_asks_to_leave_the_sandbox_and_has_no_output_is_waiting_on_you(self):
        s = self.turn(call(T1, "c1", cmd="git push origin dev", escalate=True, justification="needs the network"))
        self.assertEqual(s["status"], "waiting")
        self.assertEqual(s["asking"], {"kind": "permission", "tool": "Shell",
                                       "command": "git push origin dev", "target": ""})
        self.assertEqual(s["updatedAt"], 1790074140000)           # since the call

    def test_the_moment_it_answers_it_is_busy_again(self):
        s = self.turn(call(T1, "c1", cmd="make", escalate=True), answer(T2, "c1"))
        self.assertEqual((s["status"], s.get("asking")), ("busy", None))
        self.assertEqual(s["updatedAt"], 1790074136218)

    def test_a_custom_tool_s_output_answers_the_call_too(self):
        s = self.turn(call(T1, "c1", cmd="make", escalate=True), answer(T2, "c1", "custom_tool_call_output"))
        self.assertEqual(s["status"], "busy")

    def test_a_call_that_stays_in_the_sandbox_is_not_a_question(self):
        s = self.turn(call(T1, "c1", cmd="ls"))
        self.assertEqual((s["status"], s.get("asking")), ("busy", None))

    def test_a_session_that_cannot_ask_is_not_waiting_on_you(self):
        for how in ("never", "", None, 7):
            with self.subTest(how=how):
                s = self.turn(call(T1, "c1", cmd="make", escalate=True), how=how)
                self.assertEqual((s["status"], s.get("asking")), ("busy", None))

    def test_a_session_that_has_not_said_what_it_may_do_is_not_waiting_on_you(self):
        s = self.one(meta(), rec(T0, "event_msg", type="task_started"),
                     call(T1, "c1", cmd="make", escalate=True))
        self.assertEqual((s["status"], s.get("asking")), ("busy", None))

    def test_a_turn_that_ended_leaves_nothing_to_approve(self):
        for end in (rec(T3, "event_msg", type="task_complete"), rec(T3, "event_msg", type="turn_aborted")):
            with self.subTest(end=end["payload"]["type"]):
                s = self.turn(call(T1, "c1", cmd="make", escalate=True), end)
                self.assertEqual((s["status"], s.get("asking")), ("idle", None))

    def test_the_next_turn_does_not_inherit_the_last_one_s_call(self):
        s = self.turn(call(T1, "c1", cmd="make", escalate=True), rec(T2, "event_msg", type="turn_aborted"),
                      rec(T3, "event_msg", type="task_started"), policy(T3))
        self.assertEqual((s["status"], s.get("asking")), ("busy", None))

    def test_the_oldest_call_still_waiting_is_the_one_shown(self):
        s = self.turn(call(T1, "c1", cmd="first one", escalate=True),
                      call(T2, "c2", cmd="second one", escalate=True))
        self.assertEqual(s["asking"]["command"], "first one")
        self.assertEqual(s["updatedAt"], 1790074140000)

    def test_one_that_was_answered_is_not_the_one_shown(self):
        s = self.turn(call(T1, "c1", cmd="first one", escalate=True),
                      call(T2, "c2", cmd="second one", escalate=True), answer(T3, "c1"))
        self.assertEqual(s["asking"]["command"], "second one")

    def test_a_command_may_be_a_list_of_words(self):
        s = self.turn(call(T1, "c1", command=["git", "push", "origin", "dev"], escalate=True))
        self.assertEqual(s["asking"]["command"], "git push origin dev")

    def test_a_call_with_no_command_still_asks_and_has_nothing_to_copy(self):
        s = self.turn(call(T1, "c1", escalate=True))
        self.assertEqual(s["asking"], {"kind": "permission", "tool": "Shell", "command": "", "target": ""})

    def test_a_command_longer_than_a_prompt_can_hold_comes_with_one_character_more(self):
        s = self.turn(call(T1, "c1", cmd="x" * (base.COMMAND_LIMIT + 500), escalate=True))
        self.assertEqual(len(s["asking"]["command"]), base.COMMAND_LIMIT + 1)

    def test_arguments_that_are_not_json_make_a_plain_call(self):
        s = self.turn(rec(T1, "response_item", type="function_call", name="exec_command",
                          arguments="{not json require_escalated", call_id="c1"))
        self.assertEqual((s["status"], s.get("asking")), ("busy", None))

    def test_a_call_that_only_mentions_the_word_in_its_command_is_not_an_escalation(self):
        s = self.turn(call(T1, "c1", cmd="echo require_escalated"))
        self.assertEqual((s["status"], s.get("asking")), ("busy", None))

    def test_a_call_written_after_the_turn_ended_is_not_asked_about(self):
        s = self.turn(rec(T2, "event_msg", type="task_complete"), call(T3, "c1", cmd="make", escalate=True))
        self.assertEqual((s["status"], s.get("asking")), ("idle", None))

    def test_a_flood_of_escalations_nobody_answers_is_kept_to_what_a_tile_can_use(self):
        p = self.home.provider()
        self.home.rollout(records=[meta(), rec(T0, "event_msg", type="task_started"), policy(T0),
                                   *[call(T1, f"f{i}", cmd=f"make {i}", escalate=True) for i in range(500)]])
        got = p.live()[0]
        state = next(iter(p.tail.cache.values()))
        self.assertLessEqual(len(state["calls"]), codex.MAX_CALLS)
        self.assertEqual(got["asking"]["command"], f"make {500 - codex.MAX_CALLS}")

    def test_a_flood_of_calls_nobody_answers_does_not_hide_the_one_that_asks(self):
        flood = [call(T1, f"f{i}", cmd="ls") for i in range(500)]
        s = self.turn(*flood, call(T2, "ask", cmd="make", escalate=True))
        self.assertEqual(s["asking"]["command"], "make")

    def test_the_command_is_text_and_is_not_touched(self):
        hostile = '<img src=x onerror=alert(1)> "; rm -rf / #'
        s = self.turn(call(T1, "c1", cmd=hostile, escalate=True))
        self.assertEqual(s["asking"]["command"], hostile)


def script(ts, cid, code, name="exec"):
    """A call as Codex has written it since August 2026: a `custom_tool_call` whose
    `input` is JavaScript that calls a tool, not a JSON text of arguments."""
    return rec(ts, "response_item", type="custom_tool_call", name=name, input=code,
               call_id=cid, status="completed")


def code_of(cmd, escalate=True, before="", **more):
    """The script Codex writes for one command; the shape is the real one, the words are made up."""
    fields = [f"cmd:{json.dumps(cmd)}", '"workdir":"/work/maple"', '"yield_time_ms":30000']
    if escalate:
        fields += ['"sandbox_permissions":"require_escalated"', '"justification":"needs the network"']
    fields += [f"{json.dumps(k)}:{v}" for k, v in more.items()]
    fields.append('"prefix_rule":["git","push"]')
    return before + "const r = await tools.exec_command({" + ",".join(fields) + "}); text(r.output)\n"


class Scripts(Fixture):
    """The same question asked of the shape Codex writes now. A command that merely
    talks about escalating is not one, and nothing in the script can hide one."""

    def turn(self, *records):
        return self.one(meta(), rec(T0, "event_msg", type="task_started"), policy(T0), *records)

    def asked(self, code, name="exec"):
        s = self.turn(script(T1, "c1", code, name))
        return s["status"], (s.get("asking") or {}).get("command")

    def test_a_script_that_asks_to_leave_the_sandbox_and_has_no_output_is_waiting_on_you(self):
        s = self.turn(script(T1, "c1", code_of("git push origin dev")))
        self.assertEqual(s["status"], "waiting")
        self.assertEqual(s["asking"], {"kind": "permission", "tool": "Shell",
                                       "command": "git push origin dev", "target": ""})
        self.assertEqual(s["updatedAt"], 1790074140000)

    def test_its_output_answers_it(self):
        s = self.turn(script(T1, "c1", code_of("make")), answer(T2, "c1", "custom_tool_call_output"))
        self.assertEqual((s["status"], s.get("asking")), ("busy", None))

    def test_a_script_that_stays_in_the_sandbox_is_not_a_question(self):
        self.assertEqual(self.asked(code_of("ls", escalate=False)), ("busy", None))

    def test_a_command_that_only_says_the_words_is_not_a_question(self):
        said = 'echo \'"sandbox_permissions":"require_escalated"\' && echo sandbox_permissions: "require_escalated"'
        self.assertEqual(self.asked(code_of(said, escalate=False)), ("busy", None))

    def test_a_call_that_asks_for_something_other_than_to_leave_the_sandbox_is_not_a_question(self):
        code = code_of("ls", escalate=False).replace(
            '"yield_time_ms"', '"sandbox_permissions":"use_default","justification":"require_escalated","yield_time_ms"')
        self.assertEqual(self.asked(code), ("busy", None))

    def test_the_words_in_a_comment_are_not_a_question(self):
        for comment in ('// sandbox_permissions: "require_escalated" is what the next one would say\n',
                        '/* tools.exec_command({"sandbox_permissions":"require_escalated"}) */\n',
                        '/*\n tools.exec_command({"sandbox_permissions":"require_escalated"})\n*/\n'):
            with self.subTest(comment=comment[:12]):
                self.assertEqual(self.asked(comment + code_of("ls", escalate=False)), ("busy", None))

    def test_an_apostrophe_in_a_comment_does_not_hide_the_question(self):
        for comment in ("// don't wait for me\n", "/* don't wait for me */\n", "/* it's the one that won't fit */\n"):
            with self.subTest(comment=comment):
                self.assertEqual(self.asked(code_of("git push", before=comment)), ("waiting", "git push"))

    def test_the_words_in_an_object_that_is_not_the_call_s_are_not_a_question(self):
        other = 'const o = {"sandbox_permissions":"require_escalated"};\n' + code_of("ls", escalate=False)
        inside = code_of("ls", escalate=False, env='{"sandbox_permissions":"require_escalated"}')
        for code in (other, inside):
            with self.subTest(code=code[:40]):
                self.assertEqual(self.asked(code), ("busy", None))

    def test_a_tool_that_is_not_exec_command_is_not_a_question(self):
        code = code_of("ls").replace("tools.exec_command", "tools.write_stdin")
        self.assertEqual(self.asked(code), ("busy", None))
        self.assertEqual(self.asked(code_of("ls"), name="apply_patch"), ("busy", None))

    def test_the_second_call_of_a_script_may_be_the_one_that_asks(self):
        code = code_of("ls", escalate=False) + code_of("git push")
        self.assertEqual(self.asked(code), ("waiting", "git push"))

    def test_keys_and_texts_may_be_written_any_of_the_ways_javascript_allows(self):
        code = ("const r = await tools.exec_command({'cmd': 'echo \\'hi\\'', sandbox_permissions: `require_escalated`});")
        self.assertEqual(self.asked(code), ("waiting", "echo 'hi'"))
        code = 'await tools.exec_command({"cmd":"echo \\"hi\\"\\n","sandbox_permissions":"require_escalated"})'
        self.assertEqual(self.asked(code), ("waiting", 'echo "hi"\n'))

    def test_a_script_that_is_broken_or_too_long_is_not_a_question_and_not_a_crash(self):
        for code in ('await tools.exec_command({cmd:"unfinished, "sandbox_permissions":"require_escalated"',
                     'await tools.exec_command({cmd:"x", "sandbox_permissions":"require_escalated"',
                     'await tools.exec_command({{{{', "'", "`", "/*", "tools.exec_command({",
                     code_of("x" * 200_000)):
            with self.subTest(code=code[:30]):
                self.assertEqual(self.asked(code), ("busy", None))

    def test_a_script_with_no_text_for_a_command_still_asks(self):
        code = 'await tools.exec_command({"sandbox_permissions":"require_escalated"})'
        self.assertEqual(self.asked(code), ("waiting", ""))

    def test_an_input_that_is_not_text_is_nothing(self):
        for bad in (None, 7, ["x"], {"cmd": "ls"}):
            with self.subTest(bad=bad):
                s = self.turn(rec(T1, "response_item", type="custom_tool_call", name="exec",
                                  input=bad, call_id="c1", status="completed"))
                self.assertEqual((s["status"], s.get("asking")), ("busy", None))

    # A `/` that opens a regular expression holds quotes and slashes that are not the script's.

    def test_what_a_regular_expression_holds_hides_no_question(self):
        reading = 'const r = await tools.exec_command({cmd: "cat package.json"});\n'
        for regex in ('/"name": "([^"]+)"/', "/['\"]/g", "/^https?:\\/\\//", "/[/\"]/", "/'/gi"):
            with self.subTest(regex=regex):
                code = reading + f"const name = r.output.match({regex})[1];\n" + code_of("npm publish")
                self.assertEqual(self.asked(code), ("waiting", "npm publish"))
                code = reading + code_of("npm publish", before=f"const name = r.output.match({regex}); ")
                self.assertEqual(self.asked(code), ("waiting", "npm publish"))

    def test_a_regular_expression_may_follow_a_word_that_leaves_a_value(self):
        for word in ("return", "typeof", "yield", "await", "void", "throw", "case", "in", "of", "delete"):
            with self.subTest(word=word):
                code = code_of("git push", before=f'const f = (s) => {{ {word} /"/.test(s); }}; ')
                self.assertEqual(self.asked(code), ("waiting", "git push"))

    def test_the_words_after_a_regular_expression_are_still_only_words(self):
        code = ('const r = await tools.exec_command({cmd: "make test"});\n'
                'const clean = r.output.replace(/"/g, "");\n'
                'text("next: tools.exec_command({cmd: \'git push\', sandbox_permissions: \'require_escalated\'}) once tests pass");\n')
        self.assertEqual(self.asked(code), ("busy", None))

    def test_a_script_may_begin_with_a_regular_expression(self):
        self.assertEqual(self.asked('/"/.test(s);\n' + code_of("git push")), ("waiting", "git push"))

    def test_a_slash_that_divides_opens_no_regular_expression(self):
        call = 'await tools.exec_command({cmd: "git push", sandbox_permissions: "require_escalated"});'
        for left, right in (("a", "b"), ("(a)", "(b)"), ("xs[0]", "ys[1]"), ("4", "5"), ('"x"', '"y"')):
            with self.subTest(left=left):
                self.assertEqual(self.asked(f"const h = {left} / 2; {call} const k = {right} / 3;"),
                                 ("waiting", "git push"))

    def test_a_slash_with_no_closing_slash_on_its_line_is_a_division_and_no_crash(self):
        for tail in ("const h = /\n", "const h = /abc\n", "const h = /ab\\\n/\n", "const h = /[/\n", "x = (/\n",
                     'const h = /ab\\\nx = "a/b"; ', "x = /\\\n"):
            with self.subTest(tail=tail):
                self.assertEqual(self.asked(tail + code_of("git push")), ("waiting", "git push"))
                self.assertEqual(self.asked(code_of("git push") + tail.rstrip("\n")), ("waiting", "git push"))

    def test_slashes_opening_nothing_are_read_in_linear_time(self):
        started = time.monotonic()
        self.assertEqual(self.asked("require_escalated " + "/[" * 6_000), ("busy", None))
        self.assertLess(time.monotonic() - started, 2)

    # A value is one whole text, or it is not a text at all.

    def test_a_command_built_from_pieces_is_no_command(self):
        for cmd in ('"git push origin " + b', "`git push origin ${b}`", "`git ${a} push ${b}`",
                    '"git push" + " origin"', '"git push" ? 1 : 2'):
            with self.subTest(cmd=cmd):
                code = f'await tools.exec_command({{cmd: {cmd}, sandbox_permissions: "require_escalated"}})'
                self.assertEqual(self.asked(code), ("waiting", ""))

    def test_a_template_that_interpolates_nothing_is_a_text(self):
        for cmd in ("`echo \\${b}`", "`echo $ {b} \\\\\\${c}`", "`echo $\\n{b}`"):
            with self.subTest(cmd=cmd):
                code = f'await tools.exec_command({{cmd: {cmd}, sandbox_permissions: "require_escalated"}})'
                self.assertEqual(self.asked(code)[0], "waiting")
                self.assertNotEqual(self.asked(code)[1], "")
        code = 'await tools.exec_command({cmd: `git push`, sandbox_permissions: "require_escalated"})'
        self.assertEqual(self.asked(code), ("waiting", "git push"))

    def test_a_permission_built_from_pieces_is_no_request(self):
        for how in ('"require_escalated" + ""', "`require_escalated${x}`", '"require_escalated" || "x"'):
            with self.subTest(how=how):
                code = f'await tools.exec_command({{cmd: "ls", sandbox_permissions: {how}}})'
                self.assertEqual(self.asked(code), ("busy", None))

    # Every call is read once, whatever is nested in it or left open.

    def test_calls_left_open_cost_no_more_than_their_length(self):
        started = time.monotonic()
        self.assertEqual(self.asked("require_escalated " + "tools.exec_command({" * 9999), ("busy", None))
        self.assertLess(time.monotonic() - started, 2)

    def test_a_call_inside_another_call_s_object_is_read_on_its_own(self):
        inner = 'tools.exec_command({cmd:"x", sandbox_permissions:"require_escalated"})'
        self.assertEqual(self.asked(f'tools.exec_command({{a: {inner}, cmd:"y"}})'), ("waiting", "x"))
        self.assertEqual(self.asked(f'tools.exec_command({{cmd:"y", a: {inner}}})'), ("waiting", "x"))
        outer = 'tools.exec_command({cmd:"y", sandbox_permissions:"require_escalated", a: tools.exec_command({cmd:"x"})})'
        self.assertEqual(self.asked(outer), ("waiting", "y"))
        both = ('tools.exec_command({cmd:"outer", sandbox_permissions:"require_escalated", '
                'a: tools.exec_command({cmd:"inner", sandbox_permissions:"require_escalated"})})')
        self.assertEqual(self.asked(both), ("waiting", "outer"))

    def test_a_key_of_an_object_inside_the_call_is_not_the_call_s(self):
        code = 'tools.exec_command({cmd:"y", a: {sandbox_permissions:"require_escalated"}})'
        self.assertEqual(self.asked(code), ("busy", None))

    def test_two_calls_that_ask_show_the_first_one(self):
        self.assertEqual(self.asked(code_of("first") + code_of("second")), ("waiting", "first"))

    def test_a_call_never_closed_asks_for_nothing_whatever_follows_it(self):
        code = 'tools.exec_command({cmd:"x", sandbox_permissions:"require_escalated", prefix_rule:["git"]'
        self.assertEqual(self.asked(code), ("busy", None))
        self.assertEqual(self.asked(code + "\n" + code_of("git push")), ("waiting", "git push"))


class Runs(Fixture):
    """A `codex exec` run is started by something -- usually a Claude session --
    and the roster folds it into that session's tile. The provider says which
    process it is and which processes are above it; it does not know Claude."""

    def setUp(self):
        super().setUp()
        self.home.stat(100, 1, 900)             # a session
        self.home.stat(200, 100, 950)           # its shell
        self.home.stat(4242, 200, 1000)         # the run

    def test_a_run_says_which_processes_are_above_it_nearest_first(self):
        s = self.one(meta())
        self.assertEqual((s["kind"], s["ancestors"]), ("exec", [200, 100]))

    def test_a_review_run_says_so_and_a_plain_run_does_not(self):
        plain = self.one(meta())
        review = self.one(meta(), rec(T0, "event_msg", type="entered_review_mode"))
        self.assertEqual((plain["run"], review["run"]), ("codex exec", "codex review"))

    def test_a_review_thread_is_a_review_run_too(self):
        self.home.thread(source='{"subagent":"review"}')
        s = self.one(meta(source={"subagent": "review"}))
        self.assertEqual((s["kind"], s["run"], s["ancestors"]), ("review", "codex review", [200, 100]))

    def stdout(self, pid, target):
        folder = self.home.proc / str(pid) / "fd"
        folder.mkdir(parents=True, exist_ok=True)
        os.symlink(target, folder / "1")

    def test_a_run_under_a_background_task_says_which_task_holds_it(self):
        self.stdout(200, "/home/alice/.claude/tmp/tasks/bg1.output")
        self.assertEqual(self.one(meta())["task"], "bg1")

    def test_a_run_that_is_the_shell_s_own_command_says_so_too(self):
        self.stdout(4242, "/home/alice/.claude/tmp/tasks/bg2.output")
        self.assertEqual(self.one(meta())["task"], "bg2")

    def test_a_run_under_no_task_names_none(self):
        self.stdout(200, "/dev/pts/3")
        self.assertNotIn("task", self.one(meta()))

    def test_a_review_thread_holds_the_same_task_as_its_run(self):
        self.stdout(200, "/home/alice/.claude/tmp/tasks/bg3.output")
        self.home.thread(source='{"subagent":"review"}')
        self.assertEqual(self.one(meta(source={"subagent": "review"}))["task"], "bg3")

    def test_an_interactive_session_names_no_task(self):
        self.stdout(200, "/home/alice/.claude/tmp/tasks/bg1.output")
        self.home.thread(source="cli")
        self.assertNotIn("task", self.one(meta(source="cli")))

    def test_an_interactive_session_is_nobody_s_run(self):
        self.home.thread(source="cli")
        s = self.one(meta(source="cli"))
        self.assertNotIn("ancestors", s)
        self.assertNotIn("run", s)

    def test_a_run_whose_process_cannot_be_looked_into_has_no_ancestors_to_name(self):
        os.chmod(self.home.proc / "4242" / "fd", 0)
        self.addCleanup(os.chmod, self.home.proc / "4242" / "fd", 0o755)
        s = self.one(meta())
        self.assertEqual((s.get("pid"), s["ancestors"]), (None, []))

    def test_a_run_whose_parents_cannot_be_read_has_the_ones_it_could(self):
        os.remove(self.home.proc / "100" / "stat")
        self.assertEqual(self.one(meta())["ancestors"], [200])

    def test_a_run_started_a_moment_ago_has_the_moment_it_started(self):
        s = self.one(meta())
        self.assertEqual(s["startedAt"], T0_MS)


class Hung(test_columns.Base):
    """Hung is a claim that waits for a look that can tell (ticket 08). Codex
    writes nothing to its rollout while a command runs, and this provider never
    looks at the processes under a session, so an hour of silence in a busy
    session is not proof of anything: a rollout of 2026-05-28 has a busy
    stretch of 60 minutes that ends in the command's output."""

    def setUp(self):
        super().setUp()
        self.home = Home()
        self.home.thread()
        self.home.lock()
        self.home.holder(4242)

    def tile(self, silent):
        path = self.home.rollout(records=[meta(), rec(T0, "event_msg", type="task_started")])
        then = time.time() - silent
        os.utime(path, (then, then))
        fleet.CONFIG.write_text("{}")
        return fleet.roster(providers=[self.home.provider()])["columns"][0]["sessions"][0]

    def test_a_busy_session_whose_rollout_has_been_quiet_for_an_hour_is_not_called_hung(self):
        got = self.tile(silent=3600)
        self.assertEqual(got["status"], "busy")
        self.assertIsNone(got["stuck"])


class Tiles(test_columns.Base):
    """What the overview says about a Codex session: through `roster()`, the way
    a Claude session's stuck kinds are checked, over rollouts written to a fake
    `~/.codex`."""

    def setUp(self):
        super().setUp()
        self.home = Home()
        self.home.thread(source="cli")
        self.home.lock()
        self.home.holder(4242)

    def tile(self, *records, silent=0):
        path = self.home.rollout(records=[meta(source="cli"), rec(T0, "event_msg", type="task_started"),
                                          policy(T0), *records])
        then = time.time() - silent
        os.utime(path, (then, then))
        fleet.CONFIG.write_text("{}")
        return fleet.roster(providers=[self.home.provider()])["columns"][0]["sessions"][0]

    def test_a_pending_escalated_command_reads_as_needs_you_however_long_it_has_waited(self):
        for silent in (30, 3600, 6 * 3600):
            with self.subTest(silent=silent):
                got = self.tile(call(T1, "c1", cmd="git push origin dev", escalate=True), silent=silent)
                self.assertEqual(got["status"], "waiting")
                self.assertEqual(got["stuck"], {
                    "kind": "needs", "source": "permission", "reason": "Permission prompt",
                    "context": {"tool": "Shell", "command": "git push origin dev",
                                "target": "", "copy": True}})
                self.assertEqual((got["counted"], got["moving"]), ("needs", False))

    def test_once_the_person_has_decided_it_is_not_needs_you(self):
        got = self.tile(call(T1, "c1", cmd="make", escalate=True), answer(T2, "c1"))
        self.assertIsNone(got["stuck"])

    def test_a_pending_escalated_command_is_not_hung_whatever_the_provider_can_see(self):
        self.tile(call(T1, "c1", cmd="make", escalate=True), silent=3600)
        row = fleet.sessions(providers=[self.home.provider()])[0]
        self.assertFalse(fleet.is_hung(row))

    def test_a_usage_limit_is_limit_with_its_reset_time(self):
        got = self.tile(done(message=LIMIT % "2:35 PM", codex_error_info="usage_limit_exceeded"))
        self.assertEqual(got["stuck"]["kind"], "limit")
        self.assertIsNotNone(got["stuck"]["context"]["resetsAt"])
        self.assertEqual(got["counted"], "otherStuck")

    def test_any_other_terminal_error_is_error_with_its_type(self):
        got = self.tile(done(message="Busy.", codex_error_info="server_overloaded"))
        self.assertEqual((got["stuck"]["kind"], got["stuck"]["reason"]), ("error", "Overloaded"))

    def test_the_next_turn_clears_the_limit(self):
        got = self.tile(done(message=LIMIT % "2:35 PM", codex_error_info="usage_limit_exceeded"),
                        rec(T3, "event_msg", type="task_started"))
        self.assertIsNone(got["stuck"])


if __name__ == "__main__":
    unittest.main()
