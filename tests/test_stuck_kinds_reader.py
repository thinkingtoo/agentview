"""What the Claude reader hands over for the stuck kinds Limit, Error and Hung:
the API error that is the last thing a session said, the last tool it called,
and whether /proc could say what runs under it.

Through `ClaudeProvider.live()` over a fake config folder and a fake `/proc`,
like the movement tests. The transcripts are invented, and so is every error
text in them: records have the shape Claude Code writes (checked against this
machine's transcripts for their keys, 2026-10-19), the words are not copied.

R18 is the case that matters most here: Claude Code writes bookkeeping records
after an error on its own (a turn duration, a title, a queue entry), and none
of them is the session moving on.
R17: /proc that cannot answer is not proof that nothing runs.
"""
import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
from providers import base, claude, procs
import test_columns
import test_movement_provider as mp
from test_movement_provider import stamp, text, call, accepted

RESET = 1792263600           # seconds; the record's own clock
LIMIT_TEXT = "Invented limit notice · resets 14:20"


def api_error(seconds_ago, error="rate_limit", status=429, words=LIMIT_TEXT, resets=RESET, **over):
    """An API error as Claude Code writes it: a synthetic assistant message with
    `isApiErrorMessage`, the error's name, and for a rate limit the quota."""
    rec = {"type": "assistant", "timestamp": stamp(seconds_ago), "isApiErrorMessage": True,
           "isSidechain": False, "error": error, "apiErrorStatus": status,
           "message": {"id": "msg_err", "role": "assistant", "model": "<synthetic>",
                       "content": [{"type": "text", "text": words}]}}
    if resets is not None:
        rec["apiError"] = "usage_limit_reached"
        rec["quotaLimits"] = {"status": "rejected", "resetsAt": resets, "rateLimitType": "five_hour"}
        rec["apiErrorParams"] = {"rate_limit_info": {"status": "rejected", "resetsAt": resets}}
    rec.update(over)
    return rec


def prompt(seconds_ago, words="carry on", **over):
    return {"type": "user", "timestamp": stamp(seconds_ago), "message": {"role": "user", "content": words}, **over}


def turn_end(seconds_ago, subtype="stop_hook_summary", **over):
    """What Claude Code writes when a turn is over: the stop hooks' summary, then
    the turn's duration (a session with no stop hooks has only the second)."""
    return {"type": "system", "subtype": subtype, "timestamp": stamp(seconds_ago),
            "isSidechain": False, **over}


# Everything Claude Code writes after an error that is not a turn (the types
# seen after real errors on this machine, by count).
BOOKKEEPING = [
    {"type": "queue-operation", "operation": "enqueue", "content": "an invented queued line"},
    {"type": "system", "subtype": "turn_duration", "durationMs": 1200},
    {"type": "system", "subtype": "informational", "content": "an invented notice"},
    {"type": "last-prompt", "lastPrompt": "carry on"},
    {"type": "cost-state", "costUSD": 1.5},
    {"type": "file-history-snapshot", "snapshot": {}},
    {"type": "attachment", "attachment": {"type": "an_invented_kind"}},
    {"type": "ai-title", "aiTitle": "An invented title"},
    {"type": "permission-mode", "permissionMode": "default"},
    {"type": "mode", "mode": "normal"},
    {"type": "pr-link", "prNumber": 1},
]


class Base(mp.Provider):
    def setUp(self):
        super().setUp()
        self.addCleanup(shutil.rmtree, self.fake.root, True)
        self.addCleanup(shutil.rmtree, self.cfg.parent, True)

    def failure(self, records, status="idle"):
        # Each call is a different session file; the reader's cache knows a
        # file by where it ends and what it begins with, and two files written
        # in the same millisecond begin alike.
        claude._cache.clear()
        self.session(records, status=status)
        return self.live()[0]["failure"]


class LastRecord(Base):
    def test_a_rate_limit_as_the_last_record_is_a_limit_with_its_reset_time(self):
        got = self.failure([text(300), api_error(120)])
        self.assertEqual({k: got[k] for k in ("kind", "type", "status", "text", "resetsAt")},
                         {"kind": "limit", "type": "rate_limit", "status": 429,
                          "text": LIMIT_TEXT, "resetsAt": RESET * 1000})
        self.assertAlmostEqual(got["at"] / 1000, time.time() - 120, delta=2)

    def test_the_reset_time_is_found_in_the_error_params_when_the_quota_is_not_there(self):
        rec = api_error(60)
        del rec["quotaLimits"]
        self.assertEqual(self.failure([rec])["resetsAt"], RESET * 1000)

    def test_a_limit_that_says_no_reset_time_has_none(self):
        self.assertIsNone(self.failure([api_error(60, resets=None)])["resetsAt"])

    def test_any_other_api_error_is_an_error_with_its_type_and_status(self):
        for error, status in (("authentication_failed", 401), ("server_error", 529),
                              ("server_error", None), ("invalid_request", 400)):
            with self.subTest(error=error, status=status):
                got = self.failure([text(300), api_error(60, error, status, "An invented failure", None)])
                self.assertEqual({k: got[k] for k in ("kind", "type", "status", "text", "resetsAt")},
                                 {"kind": "error", "type": error, "status": status,
                                  "text": "An invented failure", "resetsAt": None})

    def test_an_error_that_does_not_name_itself_is_still_an_error(self):
        rec = api_error(60, "x", None, "An invented failure", None)
        del rec["error"]
        got = self.failure([rec])
        self.assertEqual((got["kind"], got["type"]), ("error", ""))

    def test_a_session_that_is_busy_with_an_error_last_still_has_it(self):
        # The kind is the page's call; the reader says what the file says.
        self.assertEqual(self.failure([api_error(60)], status="busy")["kind"], "limit")

    def test_an_assistant_record_that_is_not_marked_as_an_api_error_is_none(self):
        # Claude Code also writes synthetic replies that are not errors.
        synthetic = {"type": "assistant", "timestamp": stamp(60), "isApiErrorMessage": False,
                     "message": {"model": "<synthetic>", "content": [{"type": "text", "text": "No response requested."}]}}
        self.assertIsNone(self.failure([text(120), synthetic]))
        self.assertIsNone(self.failure([text(120), api_error(60, isApiErrorMessage="yes")]))

    def test_a_user_record_that_claims_to_be_an_api_error_is_none(self):
        self.assertIsNone(self.failure([text(120), api_error(60, type="user")]))

    def test_no_error_at_all_is_none(self):
        self.assertIsNone(self.failure([text(120), call(60)]))


class Bookkeeping(Base):
    """R18: an error followed only by records Claude Code writes by itself is
    still the last record."""

    def test_each_kind_of_bookkeeping_after_a_limit_leaves_it_there(self):
        for extra in BOOKKEEPING:
            with self.subTest(extra=extra["type"] + str(extra.get("subtype", ""))):
                rec = {**extra, "timestamp": stamp(30)}
                got = self.failure([text(300), api_error(120), rec])
                self.assertEqual(got and got["kind"], "limit")

    def test_all_of_them_together_after_an_error_leave_it_there(self):
        tail = [{**extra, "timestamp": stamp(30 - i)} for i, extra in enumerate(BOOKKEEPING)]
        got = self.failure([text(300), api_error(120, "server_error", None, "An invented failure", None)] + tail)
        self.assertEqual((got["kind"], got["type"]), ("error", "server_error"))

    def test_a_record_with_no_stamp_and_a_blank_line_after_it_leave_it_there(self):
        self.session([text(300), api_error(120), {"type": "ai-title", "aiTitle": "x"}])
        with self.transcript.open("a") as fh:
            fh.write("\n{not json}\n")
        self.assertEqual(self.live()[0]["failure"]["kind"], "limit")

    def test_a_subagents_record_in_the_file_is_not_the_session_moving_on(self):
        sub = {**text(30), "isSidechain": True}
        self.assertEqual(self.failure([api_error(120), sub])["kind"], "limit")


# What Claude Code writes when the person runs a slash command or a `!` line
# at the prompt: user records, but nothing is asked of the model (R18).
CAVEAT = {"isMeta": True, "message": {"role": "user", "content":
          "<local-command-caveat>Caveat: invented, the messages below were generated locally.</local-command-caveat>"}}
NAME = "<command-name>/model</command-name>\n<command-message>model</command-message>\n<command-args></command-args>"
STDOUT = "<local-command-stdout>An invented output line</local-command-stdout>"


def local(seconds_ago, words, **over):
    return {"type": "user", "timestamp": stamp(seconds_ago),
            "message": {"role": "user", "content": words}, **over}


class LocalCommands(Base):
    """R18: a slash command run locally leaves the error where it is; what the
    person sends to the model, or what the model is sent, clears it."""

    def test_the_caveat_alone_leaves_the_error_there(self):
        got = self.failure([api_error(120), {"type": "user", "timestamp": stamp(60), **CAVEAT}])
        self.assertEqual(got and got["kind"], "limit")

    def test_the_caveat_the_command_and_its_output_together_leave_it_there(self):
        tail = [{"type": "user", "timestamp": stamp(60), **CAVEAT},
                local(59, NAME), local(58, STDOUT)]
        got = self.failure([text(300), api_error(120)] + tail)
        self.assertEqual(got and got["kind"], "limit")

    def test_the_same_records_in_list_form_leave_it_there(self):
        def part(words):
            return {"type": "user", "timestamp": stamp(50), "message": {"role": "user", "content": [{"type": "text", "text": words}]}}
        got = self.failure([api_error(120), part(NAME), part(STDOUT)])
        self.assertEqual(got and got["kind"], "limit")

    def test_the_command_message_alone_leaves_it_there(self):
        got = self.failure([api_error(120, "server_error", None, "An invented failure", None),
                            local(60, "<command-message>model</command-message>")])
        self.assertEqual(got and got["kind"], "error")

    def test_a_shell_line_typed_at_the_prompt_leaves_it_there(self):
        tail = [local(60, "<bash-input>ls</bash-input>"), local(59, "<bash-stdout>an invented line</bash-stdout><bash-stderr></bash-stderr>")]
        got = self.failure([api_error(120)] + tail)
        self.assertEqual(got and got["kind"], "limit")

    def test_each_tag_claude_code_opens_a_local_record_with_leaves_it_there(self):
        # Read out of Claude Code 2.1.295 and out of real transcripts: the first
        # six are written by slash commands, the last three by a `!` line.
        for tag in ("local-command-caveat", "local-command-stdout", "local-command-stderr",
                    "command-name", "command-message", "bash-input", "bash-stdout", "bash-stderr"):
            with self.subTest(tag=tag):
                got = self.failure([api_error(120), local(60, f"<{tag}>an invented line</{tag}>")])
                self.assertEqual(got and got["kind"], "limit")

    def test_leading_blank_space_does_not_change_what_the_record_is(self):
        got = self.failure([api_error(120), local(60, "\n  " + NAME)])
        self.assertEqual(got and got["kind"], "limit")

    def test_a_skills_command_message_then_its_expanded_prompt_clears_it(self):
        # The skill is the person asking the model: the expanded prompt is the turn.
        tail = [local(60, NAME), local(59, "Base directory for this skill: /invented\n\nDo the invented thing.", isMeta=True)]
        self.assertIsNone(self.failure([api_error(120)] + tail))

    def test_a_command_then_a_prompt_typed_clears_it(self):
        self.assertIsNone(self.failure([api_error(120), local(60, NAME), local(59, STDOUT), prompt(30)]))

    def test_each_thing_sent_to_the_model_clears_it(self):
        for words in ("carry on",
                      "<task-notification>an invented job finished</task-notification>",
                      '<teammate-message teammate_id="peer">an invented message</teammate-message>',
                      "Your usage limit has reset. Invented, carry on.",
                      "a prompt that only mentions <command-name> half way through"):
            with self.subTest(words=words[:30]):
                self.assertIsNone(self.failure([api_error(120), local(60, words)]))

    def test_a_tool_result_in_list_form_is_not_a_local_command(self):
        result = {"type": "user", "timestamp": stamp(60),
                  "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": STDOUT}]}}
        self.assertIsNone(self.failure([api_error(120), result]))

    def test_a_local_command_written_before_the_error_changes_nothing(self):
        got = self.failure([local(300, NAME), api_error(120)])
        self.assertEqual(got and got["kind"], "limit")

    def test_a_local_command_does_not_clear_an_error_written_later_to_the_file(self):
        self.session([text(300), api_error(120)])
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(local(30, NAME)) + "\n")
        self.assertEqual(self.live()[0]["failure"]["kind"], "limit")
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(prompt(1)) + "\n")
        self.assertIsNone(self.live()[0]["failure"])


class MovingOn(Base):
    def test_a_prompt_typed_after_the_error_clears_it(self):
        self.assertIsNone(self.failure([api_error(120), prompt(60)]))

    def test_the_session_resuming_by_itself_clears_it(self):
        # Claude Code writes a meta prompt when the limit is over and goes on.
        resume = prompt(60, "an invented resume notice", isMeta=True)
        self.assertIsNone(self.failure([api_error(120), resume]))

    def test_an_answer_after_the_error_clears_it(self):
        self.assertIsNone(self.failure([api_error(120), text(60)]))

    def test_a_tool_result_after_the_error_clears_it(self):
        result = {"type": "user", "timestamp": stamp(60),
                  "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}}
        self.assertIsNone(self.failure([api_error(120), result]))

    def test_a_second_error_replaces_the_first(self):
        got = self.failure([api_error(300), prompt(200), api_error(60, "server_error", 529, "An invented failure", None)])
        self.assertEqual((got["kind"], got["type"]), ("error", "server_error"))

    def test_an_error_written_later_is_found_and_a_prompt_written_later_clears_it(self):
        self.session([text(300)])
        self.assertIsNone(self.live()[0]["failure"])
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(api_error(60)) + "\n")
        self.assertEqual(self.live()[0]["failure"]["kind"], "limit")
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(BOOKKEEPING[1]) + "\n")
        self.assertEqual(self.live()[0]["failure"]["kind"], "limit")
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(prompt(1)) + "\n")
        self.assertIsNone(self.live()[0]["failure"])


class Bounds(Base):
    def test_what_an_error_says_is_cut_to_what_a_tile_holds(self):
        got = self.failure([api_error(60, words="w" * 5000)])
        self.assertLessEqual(len(got["text"]), base.FAILURE_LEN)
        self.assertGreater(len(got["text"]), 0)

    def test_an_error_with_no_words_has_empty_text(self):
        rec = api_error(60)
        rec["message"]["content"] = "just a string"
        self.assertEqual(self.failure([rec])["text"], "")

    def test_a_reset_time_that_is_not_a_time_is_none(self):
        for junk in ("tomorrow", True, None, -5, 0, float("inf"), 10 ** 30, [1], {"a": 1}):
            with self.subTest(junk=junk):
                rec = api_error(60)
                rec["quotaLimits"]["resetsAt"] = junk
                rec["apiErrorParams"]["rate_limit_info"]["resetsAt"] = junk
                self.assertIsNone(self.failure([rec])["resetsAt"])

    def test_junk_where_the_quota_should_be_is_no_reset_time_and_no_crash(self):
        for junk in ("x", 7, None, [], {"resetsAt": "x"}):
            with self.subTest(junk=junk):
                rec = api_error(60)
                rec["quotaLimits"] = junk
                rec["apiErrorParams"] = junk
                self.assertIsNone(self.failure([rec])["resetsAt"])

    def test_a_status_that_is_not_a_number_is_none(self):
        for junk in ("429", True, 1.5, [429]):
            with self.subTest(junk=junk):
                self.assertIsNone(self.failure([api_error(60, apiErrorStatus=junk)])["status"])

    def test_a_name_that_is_not_text_is_empty_and_the_error_an_error(self):
        got = self.failure([api_error(60, error=["rate_limit"])])
        self.assertEqual((got["kind"], got["type"]), ("error", ""))

    def test_a_stamp_that_is_not_a_time_gives_no_time(self):
        self.assertIsNone(self.failure([api_error(60, timestamp="yesterday")])["at"])


class LastTool(Base):
    def test_the_last_call_the_session_made_is_the_last_tool_with_when(self):
        self.session([call(900, tool_id="t1"), text(800), call(600, tool_id="t2", description="Build the docs")])
        got = self.live()[0]["lastTool"]
        self.assertEqual(got["text"], "Build the docs")
        self.assertAlmostEqual(got["at"] / 1000, time.time() - 600, delta=2)

    def test_a_call_that_came_back_is_still_the_last_tool(self):
        result = {"type": "user", "timestamp": stamp(890),
                  "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}
        self.session([call(900, tool_id="t1"), result, text(880)])
        self.assertEqual(self.live()[0]["lastTool"]["text"], "Run the unit tests")

    def test_a_subagents_call_in_the_file_is_not_the_sessions(self):
        sub = {**call(100, tool_id="t9", description="Subagent work"), "isSidechain": True}
        self.session([call(900, tool_id="t1"), sub])
        self.assertEqual(self.live()[0]["lastTool"]["text"], "Run the unit tests")

    def test_a_session_that_never_called_a_tool_has_none(self):
        self.session([text(120)])
        self.assertIsNone(self.live()[0]["lastTool"])

    def test_the_words_are_cut_to_what_a_line_holds(self):
        self.session([call(60, description="d" * 900)])
        self.assertLessEqual(len(self.live()[0]["lastTool"]["text"]), claude.ASK_LIMIT)

    def test_a_call_with_no_stamp_is_no_last_tool(self):
        rec = call(60)
        del rec["timestamp"]
        self.session([rec])
        self.assertIsNone(self.live()[0]["lastTool"])


class ProcsUnknown(Base):
    """R17: the provider says when /proc could not answer, and the core does
    not read that as a session with nothing under it."""

    def test_a_session_with_nothing_a_process_could_belong_to_is_known(self):
        self.session([text(60)], status="idle")
        (self.fake.root / "100" / "task" / "100" / "children").unlink()
        self.assertFalse(self.live()[0]["procsUnknown"])

    def test_a_children_list_that_cannot_be_read_is_unknown(self):
        self.session([call(900)], status="busy")
        (self.fake.root / "100" / "task" / "100" / "children").unlink()
        self.assertTrue(self.live()[0]["procsUnknown"])

    def test_open_tasks_with_a_children_list_that_cannot_be_read_are_unknown(self):
        self.session([call(300), accepted(299, "toolu_1", "bk7q2m9xa")], status="idle")
        (self.fake.root / "100" / "task" / "100" / "children").unlink()
        self.assertTrue(self.live()[0]["procsUnknown"])

    def test_the_first_look_at_a_command_has_nothing_to_compare_with_and_is_unknown(self):
        # Right after a restart every session is looked at for the first time:
        # no CPU can be seen yet, and that is not "uses none".
        self.session([call(900)], status="busy")
        self.shell()
        self.assertTrue(self.live()[0]["procsUnknown"])
        self.assertFalse(self.live()[0]["procsUnknown"])

    def test_a_command_whose_shell_exits_after_it_was_found_is_unknown(self):
        # The shell is named and its command line read; then it is gone.
        self.session([call(900)], status="busy")
        shell = self.fake.add(200, 100, cmd=mp.BASH)
        self.live()
        (self.fake.root / str(shell) / "stat").unlink()
        self.assertTrue(self.live()[0]["procsUnknown"])

    def test_a_call_in_flight_with_no_command_under_it_is_known(self):
        self.session([call(900)], status="busy")
        self.assertFalse(self.live()[0]["procsUnknown"])

    def test_a_look_that_was_made_twice_in_a_row_is_known(self):
        self.session([call(900)], status="busy")
        self.shell()
        self.live()
        self.assertFalse(self.live()[0]["procsUnknown"])


class CpuAgo(Base):
    """The provider says when CPU was last seen moving, not only whether it moves
    now: Hung counts silence from the last sign of life, and CPU a minute ago is one."""

    def burning(self):
        self.session([call(1800)], status="busy")
        worker = self.shell()
        self.live()                       # the baseline
        return worker

    def test_a_session_nothing_was_looked_at_for_has_no_time(self):
        self.session([text(60)], status="idle")
        self.assertIsNone(self.live()[0]["shellCpuAgo"])

    def test_cpu_that_was_never_seen_moving_has_no_time(self):
        self.burning()
        got = self.live()[0]
        self.assertEqual((got["shellCpu"], got["shellCpuAgo"]), (False, None))

    def test_cpu_moving_now_is_nought_minutes_ago(self):
        worker = self.burning()
        self.fake.burn(worker, 900)
        got = self.live()[0]
        self.assertTrue(got["shellCpu"])
        self.assertAlmostEqual(got["shellCpuAgo"], 0.0, delta=0.1)

    def test_cpu_that_moved_five_minutes_ago_says_so_while_it_is_not_moving_now(self):
        worker = self.burning()
        self.fake.burn(worker, 900)
        self.live()
        shells = self.provider.shells
        shells.cpu_seen[100] -= 300          # five minutes pass: the flicker guard is long over
        shells.cpu_at.pop(100)
        got = self.live()[0]
        self.assertFalse(got["shellCpu"])
        self.assertAlmostEqual(got["shellCpuAgo"], 5.0, delta=0.1)

    def test_a_session_whose_processes_could_not_be_read_has_no_time(self):
        self.session([call(900)], status="busy")
        (self.fake.root / "100" / "task" / "100" / "children").unlink()
        self.assertIsNone(self.live()[0]["shellCpuAgo"])


class Unreadable(Base):
    """R17: a transcript that cannot be read says nothing about writes."""

    def busy_without_transcript(self):
        (self.cfg / "sessions" / "100.json").write_text(json.dumps({
            "pid": 100, "sessionId": mp.SID, "kind": "interactive", "entrypoint": "cli",
            "status": "busy", "procStart": "1640779", "cwd": "/tmp", "name": "Ilse",
            "statusUpdatedAt": int((time.time() - 3600) * 1000)}))
        return self.live()[0]

    def test_a_busy_session_with_no_transcript_reports_no_quiet_time_and_no_failure(self):
        got = self.busy_without_transcript()
        self.assertEqual((got["quietFor"], got["subQuiet"], got["failure"], got["lastTool"]),
                         (None, None, None, None))

    def test_a_transcript_that_goes_between_the_stat_and_the_read_reports_no_quiet_time(self):
        self.session([text(30)], status="busy")
        self.transcript.unlink()
        self.assertIsNone(self.live()[0]["quietFor"])


class PidReuse(Base):
    """R17: a pid the kernel handed to another process is not the session."""

    def test_a_registry_record_whose_pid_is_now_another_process_is_not_listed(self):
        self.session([text(1200)], status="busy")
        record = self.cfg / "sessions" / "100.json"
        was = json.loads(record.read_text())
        record.write_text(json.dumps({**was, "procStart": "999999"}))
        self.assertEqual(self.live(), [])


class Baseline(unittest.TestCase):
    """`Shells.look` says `cpu: None` when it could not compare with an earlier look."""

    def setUp(self):
        import test_movement_procs as tp
        self.fake = tp.FakeProc()
        self.addCleanup(shutil.rmtree, self.fake.root, True)
        self.fake.add(tp.SESSION, cmd="claude\0")
        self.shells = procs.Shells(proc=self.fake.root)
        self.tp = tp

    def cpu(self, at):
        return self.shells.look(self.tp.SESSION, now=at)["cpu"]

    def test_no_commands_means_nothing_to_compare_and_none_used_cpu(self):
        self.assertIs(self.cpu(1000.0), False)

    def test_the_first_look_at_a_command_says_nothing_and_the_second_says_none(self):
        shell = self.fake.add(200, self.tp.SESSION, cmd=self.tp.BASH)
        self.fake.add(300, shell, cmd="python3\0", ticks=5)
        self.assertIsNone(self.cpu(1000.0))
        self.assertIs(self.cpu(1003.0), False)

    def test_a_command_that_burns_between_two_looks_is_cpu_and_stays_cpu_through_a_new_one(self):
        shell = self.fake.add(200, self.tp.SESSION, cmd=self.tp.BASH)
        worker = self.fake.add(300, shell, cmd="python3\0", ticks=5)
        self.cpu(1000.0)
        self.fake.burn(worker, 500)
        self.assertIs(self.cpu(1003.0), True)

    def test_a_baseline_from_long_ago_is_none(self):
        self.fake.add(200, self.tp.SESSION, cmd=self.tp.BASH)
        self.cpu(1000.0)
        self.assertIsNone(self.cpu(1000.0 + procs.STALE + 5))

    def test_a_walk_that_could_read_none_of_the_commands_says_nothing(self):
        shell = self.fake.add(200, self.tp.SESSION, cmd=self.tp.BASH)
        (self.fake.root / str(shell) / "stat").unlink()
        got = self.shells.look(self.tp.SESSION, now=1000.0)
        self.assertEqual((got["shells"], got["cpu"]), (1, None))
        self.assertIsNone(self.cpu(1003.0))


if __name__ == "__main__":
    unittest.main()


class OtherSubagents(Base):
    """Box 2, from the files up to the tile: a session waiting on a named
    teammate or on the agents of a workflow is waiting on subagents, and is not
    Hung. They write where a background agent does not: a teammate a transcript
    of its own beside the session's, a workflow's agents one folder deeper than
    `subagents/`. Found on a live session, 2026-10-19: its turn over, its
    teammate writing every few seconds, and the tile said Hung."""

    def setUp(self):
        super().setUp()
        test_columns.Base.setUp(self)

    def tile(self):
        fleet.CONFIG.write_text("{}")
        return fleet.roster(providers=[self.provider])["columns"][0]["sessions"][0]

    def lead(self, silent):
        """A busy session whose transcript was last written `silent` seconds ago."""
        self.session([text(silent)], status="busy")
        then = time.time() - silent
        os.utime(self.transcript, (then, then))

    def teammate(self, seconds_ago=5, team=f"session-{mp.SID[:8]}"):
        mate = self.transcript.parent / "22222222-aaaa-4bbb-8ccc-333333333333.jsonl"
        mate.write_text("".join(json.dumps(r) + "\n" for r in (
            {"type": "agent-setting", "agentSetting": "general-purpose"},
            {**text(seconds_ago), "type": "user", "teamName": team, "agentName": "hunt"})))
        then = time.time() - seconds_ago
        os.utime(mate, (then, then))

    def workflow_agent(self, seconds_ago=5):
        agent = self.transcript.with_suffix("") / "subagents" / "workflows" / "wf_1" / "agent-a1.jsonl"
        agent.parent.mkdir(parents=True)
        agent.write_text(json.dumps(text(seconds_ago)) + "\n")
        then = time.time() - seconds_ago
        os.utime(agent, (then, then))

    def test_a_busy_session_that_wrote_fifteen_minutes_ago_and_nothing_else_is_hung(self):
        self.lead(900)
        got = self.tile()
        self.assertEqual((got["stuck"]["kind"], got["stuck"]["reason"]), ("hung", "Not moving for 15 min"))

    def test_the_same_session_waiting_on_a_teammate_that_writes_is_not_hung(self):
        self.lead(900)
        self.teammate()
        got = self.tile()
        self.assertIsNone(got["stuck"])
        self.assertTrue(got["moving"])

    def test_the_same_session_waiting_on_a_workflows_agent_that_writes_is_not_hung(self):
        self.lead(900)
        self.workflow_agent()
        got = self.tile()
        self.assertIsNone(got["stuck"])
        self.assertTrue(got["moving"])

    def test_a_teammate_that_went_quiet_is_a_sign_of_life_only_for_as_long_as_a_write_is(self):
        self.lead(1800)
        self.teammate(seconds_ago=900)
        got = self.tile()
        self.assertEqual((got["stuck"]["kind"], got["stuck"]["reason"]), ("hung", "Not moving for 15 min"))

    def test_another_sessions_teammate_beside_it_is_not_this_sessions(self):
        self.lead(900)
        self.teammate(team="session-99999999")
        self.assertEqual(self.tile()["stuck"]["kind"], "hung")

    # Hunt 08-2, finding 1. Once a session has a teammate, the registry keeps it
    # `busy` through every end of turn until the session itself ends (d6f1a6ca:
    # 12 hours; 9524b377 today: 50 minutes), so a lead whose turn is over, and
    # whose team has nothing to say, read Hung for as long as that lasted.

    def over(self, silent, *records, status="busy"):
        """A session whose last words were `records`, the newest `silent` seconds ago."""
        self.session([*records], status=status)
        then = time.time() - silent
        os.utime(self.transcript, (then, then))

    def test_a_lead_whose_turn_is_over_is_not_hung_however_long_the_registry_says_busy(self):
        for ending in ("stop_hook_summary", "turn_duration"):
            with self.subTest(ending=ending):
                claude._cache.clear()
                self.over(3 * 3600, text(3 * 3600 + 2), turn_end(3 * 3600, ending))
                self.teammate(seconds_ago=3 * 3600)
                got = self.tile()
                self.assertIsNone(got["stuck"])
                self.assertFalse(got["moving"])

    def test_the_card_of_a_lead_whose_turn_is_over_is_all_idle(self):
        self.over(3 * 3600, text(3 * 3600 + 2), turn_end(3 * 3600))
        fleet.CONFIG.write_text("{}")
        column = fleet.roster(providers=[self.provider])["columns"][0]
        self.assertEqual((column["state"], column["summary"]), ("idle", {"moving": 0, "stuck": 0, "idle": 1}))

    def test_a_lead_whose_turn_is_over_is_moving_while_its_teammate_writes(self):
        self.over(900, text(902), turn_end(900))
        self.teammate(seconds_ago=5)
        got = self.tile()
        self.assertIsNone(got["stuck"])
        self.assertTrue(got["moving"])

    def test_a_teammate_that_wrote_and_went_quiet_starts_no_hung_clock_for_it(self):
        self.over(3600, text(3602), turn_end(3600))
        self.teammate(seconds_ago=900)
        got = self.tile()
        self.assertIsNone(got["stuck"])
        self.assertFalse(got["moving"])

    def test_records_claude_code_writes_after_the_end_of_a_turn_do_not_reopen_it(self):
        for record in (*BOOKKEEPING, prompt(60, "<command-name>/status</command-name>")):
            with self.subTest(type=record["type"], subtype=record.get("subtype")):
                claude._cache.clear()
                self.over(900, text(905), turn_end(900), record)
                self.assertIsNone(self.tile()["stuck"])

    def test_a_message_to_the_lead_opens_the_turn_again(self):
        # A teammate's message, a typed prompt, a task notification: the model
        # is asked something, and a lead that then goes quiet is hung.
        for words in ("<teammate-message teammate_id=\"hunt\">done</teammate-message>", "carry on"):
            with self.subTest(words=words):
                claude._cache.clear()
                self.over(900, text(905), turn_end(903), prompt(900, words))
                self.assertEqual(self.tile()["stuck"]["kind"], "hung")

    def test_a_stop_hook_that_sends_the_session_on_does_not_end_the_turn(self):
        # 455 of the 8,648 stop-hook summaries on this machine are followed by
        # the model speaking again, within 15 seconds.
        self.over(900, text(905), turn_end(903), text(900))
        self.assertEqual(self.tile()["stuck"]["kind"], "hung")

    def test_a_subagents_turn_end_in_the_sessions_file_is_not_the_sessions(self):
        self.over(900, text(905), turn_end(900, isSidechain=True))
        self.assertEqual(self.tile()["stuck"]["kind"], "hung")
