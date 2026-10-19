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


def typed(seconds_ago, words="carry on", **over):
    """The person typing at the prompt, as a Claude Code that writes `origin` does."""
    return {**prompt(seconds_ago, words), "isSidechain": False, "origin": {"kind": "human"}, **over}


def notification(seconds_ago, task="b1c2d3e4f", **over):
    """A background job or agent ending, as Claude Code writes it: a user record
    that nobody typed, with its origin (41760d93, a50c317b, 410d018a)."""
    words = (f"<task-notification>\n<task-id>{task}</task-id>\n<status>completed</status>\n"
             "<summary>an invented job finished</summary>\n</task-notification>")
    return {**prompt(seconds_ago, words), "isSidechain": False,
            "origin": {"kind": "task-notification", "producer": "session-task", "runId": "invented-run"}, **over}


def peer(seconds_ago, **over):
    """A message from another session: a meta user record, origin `peer`."""
    words = '<cross-session-message from="uds:/invented.sock">an invented message</cross-session-message>'
    return {**prompt(seconds_ago, words), "isSidechain": False, "isMeta": True,
            "origin": {"kind": "peer", "from": "uds:/invented.sock", "name": "invented",
                       "fromMode": "prompting", "body": "an invented message"}, **over}


def tool_result(seconds_ago, **over):
    return {"type": "user", "timestamp": stamp(seconds_ago), "isSidechain": False,
            "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}, **over}


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
    person types for the model, or the model's own reply, clears it."""

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

    def test_a_skills_command_message_then_its_expanded_prompt_leaves_it_until_the_model_answers(self):
        # The expanded prompt is a meta record the skill wrote, not the person
        # typing: the model has been asked, and its reply is what clears the error.
        tail = [local(60, NAME), local(59, "Base directory for this skill: /invented\n\nDo the invented thing.", isMeta=True)]
        got = self.failure([api_error(120)] + tail)
        self.assertEqual(got and got["kind"], "limit")
        self.assertIsNone(self.failure([api_error(120)] + tail + [text(30)]))

    def test_a_command_then_a_prompt_typed_clears_it(self):
        self.assertIsNone(self.failure([api_error(120), local(60, NAME), local(59, STDOUT), prompt(30)]))

    def test_each_thing_the_person_types_clears_it(self):
        for words in ("carry on",
                      "Your usage limit has reset. Invented, carry on.",
                      "a prompt that only mentions <command-name> half way through"):
            with self.subTest(words=words[:30]):
                self.assertIsNone(self.failure([api_error(120), local(60, words)]))
                self.assertIsNone(self.failure([api_error(120), typed(60, words)]))

    def test_the_models_own_reply_is_never_a_local_command_whatever_it_begins_with(self):
        # Only the person's records are local. A reply from the model that
        # happens to begin with one of the tags is the model speaking again.
        reply = {"type": "assistant", "timestamp": stamp(60),
                 "message": {"content": [{"type": "text", "text": NAME + " is what I ran"}]}}
        self.assertIsNone(self.failure([api_error(120), reply]))

    def test_a_tool_result_in_list_form_is_not_a_local_command(self):
        # What a tool printed is not the person's slash command, whatever it
        # begins with: after a turn that ended, it opens the turn again.
        result = tool_result(60)
        result["message"]["content"][0]["content"] = STDOUT
        claude._cache.clear()
        self.session([text(300), turn_end(200), result])
        self.assertFalse(self.live()[0]["turnOver"])
        claude._cache.clear()
        self.session([text(300), turn_end(200), local(60, STDOUT)])
        self.assertTrue(self.live()[0]["turnOver"])

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

    def test_the_session_resuming_by_itself_clears_it_when_the_model_answers(self):
        # Claude Code writes a meta prompt when the limit is over and goes on;
        # the prompt asks the model, the model's reply is the session moving on.
        resume = prompt(60, "an invented resume notice", isMeta=True)
        got = self.failure([api_error(120), resume])
        self.assertEqual(got and got["kind"], "limit")
        self.assertIsNone(self.failure([api_error(120), resume, text(30)]))

    def test_an_answer_after_the_error_clears_it(self):
        self.assertIsNone(self.failure([api_error(120), text(60)]))

    def test_a_typed_prompt_in_each_shape_claude_code_writes_clears_it(self):
        with_image = {"type": "user", "timestamp": stamp(60), "isSidechain": False, "origin": {"kind": "human"},
                      "message": {"content": [{"type": "text", "text": "look at this"}, {"type": "image", "source": {}}]}}
        older = {"type": "user", "timestamp": stamp(60), "isSidechain": False,
                 "message": {"content": [{"type": "text", "text": "look at this"}, {"type": "image", "source": {}}]}}
        image_only = {"type": "user", "timestamp": stamp(60), "isSidechain": False,
                      "message": {"content": [{"type": "image", "source": {}}]}}
        for rec in (typed(60), prompt(60), with_image, older, image_only):
            with self.subTest(rec=str(rec["message"]["content"])[:40], origin=rec.get("origin")):
                self.assertIsNone(self.failure([api_error(120), rec]))

    def test_a_compaction_after_the_error_clears_it(self):
        # The summary is written by a model call that worked.
        summary = prompt(60, "an invented summary", isCompactSummary=True)
        self.assertIsNone(self.failure([api_error(120), summary]))

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


class Automated(Base):
    """Hunt 08-4, note 3, ruled 2026-10-19: only what the person types, or the
    model's own reply, ends an Error or a Limit. A task notification and a
    message from another session are written by machines and do not call the
    model: 41760d93 got "Not logged in" and a notification in the same second
    and no model call for 18 minutes, a50c317b and 410d018a a notification
    hours after a rate limit (registry idle). The Error ended at once, with the
    account still logged out."""

    def test_a_task_notification_after_a_failed_login_leaves_the_error(self):
        # 41760d93: the error, the turn's duration, the notification.
        error = api_error(120, "authentication_failed", 401, "An invented failure", None)
        got = self.failure([text(300), error, turn_end(119, "turn_duration"), notification(60)])
        self.assertEqual((got["kind"], got["type"]), ("error", "authentication_failed"))

    def test_a_task_notification_after_a_rate_limit_leaves_the_limit(self):
        # a50c317b: the error, the duration, queue lines, hours later the notification.
        queue = [{"type": "queue-operation", "operation": op, "timestamp": stamp(50 - i)}
                 for i, op in enumerate(("enqueue", "dequeue"))]
        got = self.failure([text(300), api_error(120), turn_end(119, "turn_duration"), *queue, notification(40)])
        self.assertEqual((got["kind"], got["resetsAt"]), ("limit", RESET * 1000))

    def test_a_notification_then_a_peer_message_leave_it_and_the_models_reply_clears_it(self):
        # 410d018a: the error, a notification, a message from the boss, then the model.
        tail = [turn_end(119, "turn_duration"), notification(100), peer(90)]
        got = self.failure([text(300), api_error(120), *tail])
        self.assertEqual(got and got["kind"], "limit")
        self.assertIsNone(self.failure([text(300), api_error(120), *tail, text(60)]))

    def test_a_message_from_another_session_alone_leaves_it(self):
        got = self.failure([text(300), api_error(120, "server_error", None, "An invented failure", None), peer(60)])
        self.assertEqual((got["kind"], got["type"]), ("error", "server_error"))

    def test_the_same_two_written_by_an_older_claude_code_with_no_origin_leave_it(self):
        old_notice = prompt(60, notification(0)["message"]["content"])
        old_peer = prompt(50, '<teammate-message teammate_id="peer">an invented message</teammate-message>')
        for rec in (old_notice, old_peer):
            for blank in ("", "\n  "):
                with self.subTest(rec=rec["message"]["content"][:20], blank=blank):
                    rec = {**rec, "message": {"content": blank + rec["message"]["content"].lstrip()}}
                    got = self.failure([text(300), api_error(120), rec])
                    self.assertEqual(got and got["kind"], "limit")

    def test_the_notice_of_an_interrupt_is_not_a_prompt_typed(self):
        # 40 records of 14 days, all in list form and none with an origin: the
        # person pressed Escape, nothing was typed for the model.
        for words in ("[Request interrupted by user]", "[Request interrupted by user for tool use]"):
            for content in ([{"type": "text", "text": words}], words):
                with self.subTest(words=words, form=type(content).__name__):
                    rec = {"type": "user", "timestamp": stamp(60), "isSidechain": False, "message": {"content": content}}
                    got = self.failure([api_error(120), rec])
                    self.assertEqual(got and got["kind"], "limit")

    def test_a_tool_result_after_the_error_leaves_it(self):
        # It answers a call the model made before: the model has not spoken since.
        got = self.failure([api_error(120), tool_result(60)])
        self.assertEqual(got and got["kind"], "limit")

    def test_a_notification_that_says_it_is_not_typed_is_not_typed_whatever_its_words(self):
        # `origin` says who wrote a record; its words say nothing.
        for origin in ({"kind": "task-notification"}, {"kind": "peer"}, {"kind": "a-kind-not-yet-invented"}, {}, "human"):
            with self.subTest(origin=origin):
                got = self.failure([api_error(120), prompt(60, "carry on", origin=origin)])
                self.assertEqual(got and got["kind"], "limit")

    def test_a_subagents_typed_looking_record_is_not_the_person(self):
        got = self.failure([api_error(120), typed(60, isSidechain=True)])
        self.assertEqual(got and got["kind"], "limit")

    def test_what_is_written_to_the_file_later_clears_it_only_when_it_is_typed_or_a_reply(self):
        self.session([text(300), api_error(120)])
        for rec, held in ((notification(90), True), (peer(80), True), (tool_result(70), True),
                          ({"type": "system", "subtype": "turn_duration", "timestamp": stamp(60)}, True),
                          (typed(30), False)):
            with self.transcript.open("a") as fh:
                fh.write(json.dumps(rec) + "\n")
            got = self.live()[0]["failure"]
            self.assertEqual(got is not None, held, rec["type"])

    def test_a_reply_written_to_the_file_later_clears_it(self):
        self.session([text(300), api_error(120)])
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(notification(60)) + "\n")
        self.assertEqual(self.live()[0]["failure"]["kind"], "limit")
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(text(1)) + "\n")
        self.assertIsNone(self.live()[0]["failure"])

    def test_the_turn_stays_over_while_the_error_holds_and_opens_when_it_ends(self):
        # The same rule for `turnOver` (the reader's two fields agree): an error
        # nobody has answered is still the session's last word.
        claude._cache.clear()
        self.session([text(300), api_error(120), notification(60), peer(50), tool_result(40)])
        self.assertTrue(self.live()[0]["turnOver"])
        for rec in (typed(10), text(10)):
            claude._cache.clear()
            self.session([text(300), api_error(120), notification(60), rec])
            self.assertFalse(self.live()[0]["turnOver"])

    def test_after_an_ordinary_turn_end_a_notification_still_opens_the_turn(self):
        # Nothing here changes for a turn that did not end on an error.
        for rec in (notification(60), peer(60), tool_result(60)):
            claude._cache.clear()
            self.session([text(300), turn_end(200), rec])
            self.assertFalse(self.live()[0]["turnOver"], rec["type"])


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

    # Hunt 08-3, finding 1. A session whose turn ended on a rate limit has no
    # turn end after the error, and the registry goes on saying busy. It read
    # Limit for ten minutes and Hung after that, with the reset time and the
    # time held gone (034f15b5, e9f2fc08 and 04f28c2b, 2026-10-17 and 18).

    def test_a_busy_session_held_by_a_rate_limit_is_a_limit_however_long_it_is_held(self):
        for silent in (300, 900, 3600, 4 * 3600):
            with self.subTest(minutes=silent // 60):
                claude._cache.clear()
                self.over(silent, text(silent + 400), turn_end(silent + 380), prompt(silent + 100, "carry on"),
                          api_error(silent))
                got = self.tile()["stuck"]
                self.assertEqual((got["kind"], got["reason"]), ("limit", "Rate limit"))
                self.assertEqual(got["context"]["resetsAt"], RESET * 1000)
                self.assertAlmostEqual(got["context"]["held"], silent / 60, delta=0.2)

    # Hunt 08-4, note 3. Records nobody typed that arrive after the error ask
    # the model nothing (the limit still holds): Hung beats Limit in the order,
    # so a turn they opened would read Hung ten minutes on.

    def test_a_notification_or_a_peer_message_or_a_tool_result_after_the_limit_leaves_the_limit(self):
        for make in (notification, peer, tool_result):
            with self.subTest(record=make.__name__):
                claude._cache.clear()
                self.over(3000, text(3700), api_error(3600), make(3000))
                got = self.tile()["stuck"]
                self.assertEqual((got["kind"], got["reason"]), ("limit", "Rate limit"))
                self.assertAlmostEqual(got["context"]["held"], 60, delta=0.2)

    def test_the_same_after_another_api_error_leaves_the_error(self):
        claude._cache.clear()
        self.over(3000, text(3700), api_error(3600, "authentication_failed", 401, "An invented failure", None),
                  turn_end(3599, "turn_duration"), notification(3000))
        self.assertEqual(self.tile()["stuck"]["kind"], "error")

    def test_the_model_replying_after_them_and_then_going_quiet_is_hung(self):
        for last in (text(3000), typed(3000)):
            with self.subTest(last=last["type"]):
                claude._cache.clear()
                self.over(3000, text(3700), api_error(3600), notification(3300), peer(3200), last)
                self.assertEqual(self.tile()["stuck"]["kind"], "hung")

    def test_a_busy_session_that_ended_on_another_api_error_is_an_error_all_the_same(self):
        self.over(3600, text(3700), api_error(3600, "server_error", 529, "An invented failure", None))
        self.assertEqual(self.tile()["stuck"]["kind"], "error")

    def test_the_card_of_such_a_session_is_not_moving_and_not_hung(self):
        self.over(3600, text(3700), api_error(3600))
        tile = self.tile()
        self.assertFalse(tile["moving"])
        self.assertNotEqual(tile["stuck"]["kind"], "hung")

    def test_a_session_that_is_asked_something_after_an_error_and_goes_quiet_is_hung(self):
        self.over(900, text(1000), api_error(950), prompt(900, "carry on"))
        self.assertEqual(self.tile()["stuck"]["kind"], "hung")

    # Hunt 08-3, finding 2. Claude Code compacts an idle session, or the person
    # runs /compact; the summary is a user record with `isCompactSummary` and
    # nothing after it ends a turn. 35578b72, 2026-10-15: turn over at 12:25,
    # compacted idle at 13:20, registry busy until 13:36, Hung from 13:30.

    def compaction(self, seconds_ago):
        return [{"type": "system", "subtype": "compact_boundary", "timestamp": stamp(seconds_ago),
                 "isSidechain": False},
                prompt(seconds_ago, "This session is being continued from a previous conversation.",
                       isCompactSummary=True),
                {"type": "system", "subtype": "informational", "timestamp": stamp(seconds_ago - 1),
                 "content": "Compacted while idle, before the prompt cache expired"}]

    def test_a_lead_compacted_while_idle_after_its_turn_ended_is_not_hung(self):
        self.over(900, text(3700), turn_end(3600), *self.compaction(900))
        self.teammate(seconds_ago=3600)
        got = self.tile()
        self.assertIsNone(got["stuck"])
        self.assertFalse(got["moving"])

    def test_a_compaction_in_the_middle_of_a_turn_does_not_hide_a_hang_after_it(self):
        self.over(900, text(3700), *self.compaction(1000))
        self.assertEqual(self.tile()["stuck"]["kind"], "hung")

    def test_a_session_that_is_asked_something_after_a_compaction_and_goes_quiet_is_hung(self):
        self.over(900, text(3700), turn_end(3600), *self.compaction(1800), prompt(900, "carry on"))
        self.assertEqual(self.tile()["stuck"]["kind"], "hung")
