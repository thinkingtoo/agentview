"""What the Claude reader hands over about a dialog that is open: the question
with its options, or the permission prompt with its tool and command.

Through `ClaudeProvider.live()` over a fake config folder and a fake `/proc`,
like the movement tests. The transcripts are invented, and so is every
question and command in them: the real ones are read at runtime and never
copied into this repo.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import base, claude
import test_movement_provider as mp
from test_movement_provider import stamp, text

QUESTIONS = [{"question": "Publish the notes page under /docs?", "header": "Publish",
              "multiSelect": False,
              "options": [{"label": "Yes, under /docs", "description": "Linked from the sidebar"},
                          {"label": "No, keep it private", "description": "Stays a draft"}]}]


def tool(seconds_ago, name, inp, tool_id="toolu_1", message="msg_1"):
    """One tool call. Claude Code writes every call of a message as a record of
    its own, all with the message's id."""
    return {"type": "assistant", "timestamp": stamp(seconds_ago),
            "message": {"id": message,
                        "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": inp}]}}


def said(seconds_ago, message="msg_9"):
    return {"type": "assistant", "timestamp": stamp(seconds_ago),
            "message": {"id": message, "content": [{"type": "text", "text": "x"}]}}


def answered(seconds_ago, tool_id="toolu_1"):
    return {"type": "user", "timestamp": stamp(seconds_ago),
            "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id,
                                     "content": "ok"}]}}


class Asking(mp.Provider):
    def open(self, records, status="waiting", waiting_for="input needed"):
        """A session whose registry record says what Claude Code says."""
        self.session(records, status=status)
        path = self.cfg / "sessions" / "100.json"
        rec = json.loads(path.read_text())
        rec["waitingFor"] = waiting_for
        path.write_text(json.dumps(rec))
        return self.live()[0]["asking"]

    def test_an_unanswered_question_is_the_question_with_its_options(self):
        got = self.open([text(60), tool(30, "AskUserQuestion", {"questions": QUESTIONS})])
        self.assertEqual(got, {"kind": "question", "questions": [{
            "question": "Publish the notes page under /docs?", "header": "Publish",
            "multi": False,
            "options": [{"label": "Yes, under /docs", "description": "Linked from the sidebar"},
                        {"label": "No, keep it private", "description": "Stays a draft"}]}]})

    def test_a_question_that_has_been_answered_is_not_open(self):
        got = self.open([tool(30, "AskUserQuestion", {"questions": QUESTIONS}), answered(20)])
        self.assertIsNone(got)

    def test_a_question_the_session_has_talked_past_is_not_open(self):
        got = self.open([tool(30, "AskUserQuestion", {"questions": QUESTIONS}), said(10)])
        self.assertIsNone(got)

    def test_a_question_is_open_only_while_the_session_says_it_is_waiting(self):
        got = self.open([tool(30, "AskUserQuestion", {"questions": QUESTIONS})],
                        status="busy", waiting_for="")
        self.assertIsNone(got)

    def test_a_multiple_choice_question_says_so(self):
        many = [{**QUESTIONS[0], "multiSelect": True}]
        got = self.open([tool(30, "AskUserQuestion", {"questions": many})])
        self.assertTrue(got["questions"][0]["multi"])

    def test_several_questions_in_one_call_are_all_there(self):
        two = [QUESTIONS[0], {"question": "Which folder?", "header": "Folder", "multiSelect": False,
                              "options": [{"label": "docs", "description": ""},
                                          {"label": "site", "description": ""}]}]
        got = self.open([tool(30, "AskUserQuestion", {"questions": two})])
        self.assertEqual([q["question"] for q in got["questions"]],
                         ["Publish the notes page under /docs?", "Which folder?"])

    def test_a_pending_bash_call_under_a_permission_prompt_is_the_tool_and_its_command(self):
        got = self.open([said(60), tool(30, "Bash", {"command": "git push origin feature/maple-notes",
                                                     "description": "Push the branch"})],
                        waiting_for="permission prompt")
        self.assertEqual(got, {"kind": "permission", "tool": "Bash",
                               "command": "git push origin feature/maple-notes", "target": ""})

    def test_the_whole_command_is_kept_not_the_first_words_of_it(self):
        command = "python3 - <<'EOF'\n" + "print('line')\n" * 60 + "EOF"
        self.assertGreater(len(command), 200)
        got = self.open([tool(30, "Bash", {"command": command})], waiting_for="permission prompt")
        self.assertEqual(got["command"], command)

    def test_a_command_beyond_the_limit_arrives_with_one_character_over(self):
        got = self.open([tool(30, "Bash", {"command": "x" * (base.COMMAND_LIMIT + 500)})],
                        waiting_for="permission prompt")
        self.assertEqual(len(got["command"]), base.COMMAND_LIMIT + 1)

    def test_a_prompt_for_another_tool_names_what_it_would_touch_and_has_no_command(self):
        got = self.open([tool(30, "Edit", {"file_path": "/home/alice/Projects/maple/notes.md",
                                           "old_string": "a", "new_string": "b"})],
                        waiting_for="permission prompt")
        self.assertEqual(got, {"kind": "permission", "tool": "Edit",
                               "command": "", "target": "/home/alice/Projects/maple/notes.md"})

    def test_another_tools_field_called_command_is_not_a_shell_command(self):
        got = self.open([tool(30, "mcp__vault__open", {"command": "open the vault"})],
                        waiting_for="permission prompt")
        self.assertEqual((got["tool"], got["command"], got["target"]),
                         ("mcp__vault__open", "", ""))

    def test_the_prompt_is_for_the_oldest_call_still_waiting(self):
        got = self.open([tool(40, "Bash", {"command": "make build"}, "toolu_1"),
                         tool(30, "Bash", {"command": "make test"}, "toolu_2")],
                        waiting_for="permission prompt")
        self.assertEqual(got["command"], "make build")

    def test_a_sibling_call_that_came_back_does_not_close_the_one_still_waiting(self):
        # Two calls in one message: a read that ran at once, and a command that
        # asks first. The read's result is newer than the command's record.
        got = self.open([tool(40, "Read", {"file_path": "/x/a.md"}, "toolu_1"),
                         tool(39, "Bash", {"command": "make test"}, "toolu_2"),
                         answered(38, "toolu_1")], waiting_for="permission prompt")
        self.assertEqual((got["tool"], got["command"]), ("Bash", "make test"))

    def test_a_call_from_an_earlier_message_that_never_came_back_is_not_the_prompt(self):
        got = self.open([tool(90, "Bash", {"command": "make old"}, "toolu_1", "msg_1"),
                         tool(30, "Bash", {"command": "make new"}, "toolu_2", "msg_2")],
                        waiting_for="permission prompt")
        self.assertEqual(got["command"], "make new")

    def test_a_prompt_with_no_call_behind_it_is_still_a_permission_prompt(self):
        got = self.open([text(30)], waiting_for="permission prompt")
        self.assertEqual(got, {"kind": "permission", "tool": "", "command": "", "target": ""})

    def test_a_running_bash_call_is_not_a_permission_prompt(self):
        # The same pending call, but the session is working: nothing is asked.
        got = self.open([tool(30, "Bash", {"command": "make test"})],
                        status="busy", waiting_for="")
        self.assertIsNone(got)

    def test_a_menu_that_is_open_is_not_a_question_or_a_prompt(self):
        got = self.open([tool(30, "Bash", {"command": "make test"})], waiting_for="dialog open")
        self.assertIsNone(got)

    def test_input_needed_with_no_question_behind_it_is_nothing_to_show(self):
        self.assertIsNone(self.open([text(30)], waiting_for="input needed"))

    def test_a_session_that_is_idle_asks_nothing(self):
        self.assertIsNone(self.open([text(30)], status="idle", waiting_for=""))

    def test_a_question_arriving_in_a_later_read_is_found_and_its_answer_closes_it(self):
        self.assertIsNone(self.open([text(60)]))
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(tool(30, "AskUserQuestion", {"questions": QUESTIONS})) + "\n")
        self.assertEqual(self.live()[0]["asking"]["kind"], "question")
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(answered(10)) + "\n")
        self.assertIsNone(self.live()[0]["asking"])

    def test_a_big_dialog_does_not_make_the_reader_remember_it_whole(self):
        # State lives for the life of the session, times every session on the
        # page: a model that wrote an essay into a question costs a bound.
        big = [{"question": "q" * 20000, "header": "h" * 20000, "multiSelect": False,
                "options": [{"label": "l" * 20000, "description": "d" * 20000}] * 50}] * 30
        self.open([tool(30, "AskUserQuestion", {"questions": big})])
        state = claude._cache[("state", str(self.transcript))]
        self.assertLess(len(json.dumps(state["uses"], default=str)), 20000)


if __name__ == "__main__":
    unittest.main()
