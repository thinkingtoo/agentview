"""What the person sees when a session waits on them: the Needs you mark on a
tile, its reason and its context, and the state word on the card.

Through `roster()` with fake providers, the way the rest of the columns are
tested. What a provider hands over is `asking` -- the open question or the
open permission prompt, with its content -- and the session line (`n`, `ask`)
the hook writes. Names, questions and commands are all invented: they come
from real transcripts at runtime and must never come from one into this repo.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import lines
from test_columns import Base, session

NOW_MS = time.time() * 1000

INJECTION = "<img src=x onerror=alert(1)>"


def question(text="Publish the notes page under /docs?", **over):
    got = {"question": text, "header": "Publish", "multi": False,
           "options": [{"label": "Yes, under /docs", "description": "Linked from the sidebar"},
                       {"label": "No, keep it private", "description": ""}]}
    got.update(over)
    return got


def asks(*questions):
    return {"kind": "question", "questions": list(questions) or [question()]}


def prompt(tool="Bash", command="git push origin feature/maple-notes"):
    got = {"kind": "permission", "tool": tool}
    if command is not None:
        got["command"] = command
    return got


def waiting(sid="a", **over):
    return session(sid, status="waiting", waitingFor="input needed", **over)


class Sources(Base):
    def stuck(self, *sessions, **kw):
        return self.tile(*sessions, **kw)["stuck"]

    def test_an_open_question_is_needs_you_with_the_question_and_its_options(self):
        got = self.stuck(waiting(asking=asks()))
        self.assertEqual(got, {
            "kind": "needs", "source": "question", "reason": "Question",
            "context": {"questions": [{
                "question": "Publish the notes page under /docs?", "header": "Publish",
                "multi": False,
                "options": [{"label": "Yes, under /docs", "description": "Linked from the sidebar"},
                            {"label": "No, keep it private", "description": ""}]}]}})

    def test_an_open_permission_prompt_is_needs_you_with_the_tool_and_its_command(self):
        got = self.stuck(session("a", status="waiting", waitingFor="permission prompt",
                                 asking=prompt()))
        self.assertEqual(got, {
            "kind": "needs", "source": "permission", "reason": "Permission prompt",
            "context": {"tool": "Bash", "command": "git push origin feature/maple-notes",
                        "target": "", "copy": True}})

    def test_a_prompt_for_a_tool_with_no_command_has_nothing_to_copy(self):
        got = self.stuck(session("a", status="waiting", waitingFor="permission prompt",
                                 asking={"kind": "permission", "tool": "Edit",
                                         "target": "/home/alice/Projects/maple/notes.md"}))
        self.assertEqual(got["context"], {"tool": "Edit", "command": "",
                                          "target": "/home/alice/Projects/maple/notes.md",
                                          "copy": False})

    def test_a_prompt_whose_tool_could_not_be_read_is_still_a_permission_prompt(self):
        got = self.stuck(session("a", status="waiting", waitingFor="permission prompt",
                                 asking={"kind": "permission"}))
        self.assertEqual((got["reason"], got["context"]["tool"], got["context"]["copy"]),
                         ("Permission prompt", "", False))

    def test_what_a_provider_calls_a_command_is_copyable_whatever_the_tool_is_called(self):
        # The provider decides what is a shell command (Claude: Bash; Codex
        # will have its own). The roster does not know tool names.
        got = self.stuck(session("a", status="waiting", waitingFor="permission prompt",
                                 asking=prompt(tool="exec_command", command="make test")))
        self.assertEqual((got["context"]["command"], got["context"]["copy"]), ("make test", True))

    def test_a_command_cut_short_is_shown_but_not_offered_for_copying(self):
        # Half a command pasted into a terminal is worse than none.
        whole = "echo " + "x" * fleet.COMMAND_LIMIT
        got = self.stuck(session("a", status="waiting", waitingFor="permission prompt",
                                 asking=prompt(command=whole)))
        self.assertEqual(len(got["context"]["command"]), fleet.COMMAND_LIMIT)
        self.assertFalse(got["context"]["copy"])


class SessionLine(Base):
    def line(self, sid, ask="", n=0, by="session"):
        """The session has written its own line for the turn it is in."""
        lines.begin_turn(sid, self.lines)
        lines.write(sid, did="Notes page built.", ask=ask, n=n, by=by, root=self.lines)

    def stuck(self, *sessions):
        return self.tile(*sessions)["stuck"]

    def test_one_thing_left_shows_what_it_is(self):
        self.line("a", ask="Should the notes page go under /docs?", n=1)
        self.assertEqual(self.stuck(session("a")), {
            "kind": "needs", "source": "line", "reason": "1 thing left for you",
            "context": {"text": "Should the notes page go under /docs?"}})

    def test_several_things_left_say_how_many_and_quote_none(self):
        # `ask` carries words only when there is one thing; quoting the first
        # of three would misrepresent the size of the job.
        self.line("a", ask="", n=3)
        got = self.stuck(session("a"))
        self.assertEqual((got["source"], got["reason"], got["context"]),
                         ("line", "3 things left for you", {"text": ""}))

    def test_an_idle_session_with_things_left_needs_you_all_the_same(self):
        self.line("a", ask="Which branch?", n=1)
        self.assertEqual(self.stuck(session("a", status="idle"))["kind"], "needs")

    def test_a_line_that_wants_nothing_is_not_needs_you(self):
        self.line("a", n=0)
        self.assertIsNone(self.stuck(session("a")))

    def test_a_line_read_out_of_the_transcript_is_a_guess_and_does_not_mark_the_session(self):
        # The same rule as the chime's: only a session speaking for itself.
        self.line("a", ask="Which branch?", n=1, by="read")
        self.assertIsNone(self.stuck(session("a")))

    def test_a_question_found_in_the_last_words_does_not_mark_the_session_either(self):
        got = self.stuck(session("a", said="Done. Should I push this to the remote?"))
        self.assertIsNone(got)

    def test_the_open_dialog_is_shown_over_a_line_written_a_turn_ago(self):
        self.line("a", ask="Which branch?", n=2)
        got = self.stuck(waiting(asking=asks()))
        self.assertEqual((got["source"], got["reason"]), ("question", "Question"))

    def test_a_session_waiting_on_nothing_it_can_name_is_not_needs_you(self):
        # `dialog open` is a menu, not a question: the old flag still shows it.
        self.assertIsNone(self.stuck(session("a", status="waiting", waitingFor="dialog open")))

    def test_a_busy_session_with_nothing_open_is_not_needs_you(self):
        self.assertIsNone(self.stuck(session("a", status="busy", quietFor=0.1)))


class Chime(Base):
    """The chime reads `blocks`: the flag of each session and the counts of
    each block. Needs you is for the page, and adds nothing to what rings."""

    READ = ("key", "status", "flag", "blocked", "waitingFor", "n", "ask")

    def heard(self, *sessions):
        got = self.roster(*sessions)["blocks"]
        return [{"alarms": b["alarms"], "blocked": b["blocked"], "ready": b["ready"],
                 "busy": b["busy"],
                 "members": [{k: m[k] for k in self.READ} for m in b["members"]]}
                for b in got]

    def test_an_open_question_rings_exactly_as_it_did_without_the_content(self):
        with_content = self.heard(waiting(asking=asks()))
        without = self.heard(waiting())
        self.assertEqual(with_content, without)
        self.assertEqual((with_content[0]["alarms"], with_content[0]["members"][0]["flag"]),
                         (1, "waiting"))

    def test_an_open_permission_prompt_rings_exactly_as_it_did_without_the_content(self):
        waits = dict(status="waiting", waitingFor="permission prompt")
        self.assertEqual(self.heard(session("a", asking=prompt(), **waits)),
                         self.heard(session("a", **waits)))

    def test_a_session_line_with_things_left_still_counts_as_blocked_for_the_chime(self):
        lines.begin_turn("a", self.lines)
        lines.write("a", did="Built.", ask="Which branch?", n=1, root=self.lines)
        got = self.heard(session("a"))[0]
        self.assertEqual((got["blocked"], got["alarms"], got["members"][0]["flag"]),
                         (1, 1, "ready"))

    def test_content_handed_over_by_a_session_that_is_not_waiting_rings_nothing(self):
        # Needs you is the page's word. A busy session that a provider says
        # is asking gets the mark on the page and no alarm from the chime.
        got = self.heard(session("a", status="busy", quietFor=0.1, asking=asks()))[0]
        self.assertEqual((got["alarms"], got["blocked"], got["members"][0]["flag"]),
                         (0, 0, None))

    def test_the_tile_keeps_the_flag_the_chime_has(self):
        tile = self.tile(waiting(asking=asks()))
        self.assertEqual((tile["flag"], tile["stuck"]["kind"]), ("waiting", "needs"))


class Card(Base):
    def state(self, *sessions):
        return self.roster(*sessions)["columns"][0]["state"]

    def writing(self, sid, **over):
        return session(sid, status="busy", quietFor=0.1, **over)

    def test_a_card_with_a_session_that_needs_you_is_needs_you(self):
        self.assertEqual(self.state(waiting("a", asking=asks())), "needs")

    def test_needs_you_beats_moving(self):
        self.assertEqual(self.state(self.writing("a"), waiting("b", asking=asks())), "needs")

    def test_a_session_line_with_things_left_makes_the_card_needs_you(self):
        lines.begin_turn("b", self.lines)
        lines.write("b", did="Built.", ask="Which branch?", n=1, root=self.lines)
        self.assertEqual(self.state(self.writing("a"), session("b")), "needs")

    def test_a_card_with_a_session_moving_and_none_waiting_is_moving(self):
        self.assertEqual(self.state(self.writing("a"), session("b", status="idle")), "moving")

    def test_a_card_with_nothing_moving_is_all_idle(self):
        self.assertEqual(self.state(session("a", status="idle"), session("b", status="idle")), "idle")

    def test_every_card_has_a_state_and_the_no_project_one_too(self):
        got = self.roster(self.writing("a"), session("b", None, status="idle"))["columns"]
        self.assertEqual([(c["name"], c["state"]) for c in got],
                         [("maple", "moving"), ("No project", "idle")])


class Literal(Base):
    """R7: what a session says is text. The roster passes it on as the text it
    is -- neither escaped nor stripped -- and the page prints it as text."""

    def test_markup_in_a_question_its_options_and_a_command_arrives_unchanged(self):
        q = question(INJECTION, header=INJECTION, options=[
            {"label": INJECTION, "description": INJECTION}])
        got = self.tile(waiting(asking=asks(q)))["stuck"]["context"]["questions"][0]
        self.assertEqual((got["question"], got["header"], got["options"]),
                         (INJECTION, INJECTION, [{"label": INJECTION, "description": INJECTION}]))
        got = self.tile(session("b", status="waiting", waitingFor="permission prompt",
                                asking=prompt(command=f"echo {INJECTION}")))["stuck"]["context"]
        self.assertEqual(got["command"], f"echo {INJECTION}")

    def test_markup_in_the_ask_of_a_session_line_arrives_unchanged(self):
        lines.begin_turn("a", self.lines)
        lines.write("a", did="Built.", ask=INJECTION, n=1, root=self.lines)
        self.assertEqual(self.tile(session("a"))["stuck"]["context"], {"text": INJECTION})

    def test_a_command_keeps_its_line_breaks_and_quotes_for_the_copy(self):
        command = "git commit -m \"Add notes\n\nBody line\" && echo 'done'"
        got = self.tile(session("a", status="waiting", waitingFor="permission prompt",
                                asking=prompt(command=command)))["stuck"]["context"]
        self.assertEqual(got["command"], command)


class Bounds(Base):
    def stuck(self, asking):
        return self.tile(waiting(asking=asking))["stuck"]

    def test_what_cannot_be_read_marks_nothing(self):
        for junk in ("a question", 7, [], {}, {"kind": "poll"}, {"kind": "question"},
                     {"kind": "question", "questions": "why"},
                     {"kind": "question", "questions": [None, 3, {"question": ""}]}):
            with self.subTest(junk=junk):
                self.assertIsNone(self.stuck(junk))

    def test_a_prompt_whose_fields_are_not_text_is_a_prompt_with_nothing_in_it(self):
        got = self.stuck({"kind": "permission", "tool": 7, "command": ["ls"], "target": {"a": 1}})
        self.assertEqual((got["reason"], got["context"]),
                         ("Permission prompt", {"tool": "", "command": "", "target": "", "copy": False}))

    def test_a_row_that_is_not_text_where_text_is_expected_still_gets_a_tile(self):
        # The row is made field by field from what the provider said; what the
        # tile derives from it (`attach`, the state) never sees the raw value.
        for junk in (7, ["x"], {"a": 1}, None, True):
            with self.subTest(attach=junk):
                got = self.tile(waiting(asking=asks(), attach=junk, canJump=False))
                self.assertEqual(got["jump"]["via"], "none")
                self.assertEqual(got["stuck"]["source"], "question")

    def test_options_that_are_not_options_are_left_out_and_the_question_stays(self):
        q = question(options=[None, "yes", {"label": 3, "description": None}, {"label": "Yes"}])
        got = self.stuck(asks(q))["context"]["questions"][0]["options"]
        self.assertEqual(got, [{"label": "Yes", "description": ""}])

    def test_a_dialog_with_a_lot_in_it_is_cut_to_what_fits_a_tile(self):
        many = [question(f"Question {i}?", options=[{"label": f"Option {j}", "description": "d"}
                                                    for j in range(20)]) for i in range(9)]
        got = self.stuck(asks(*many))["context"]["questions"]
        self.assertEqual(len(got), fleet.MAX_QUESTIONS)
        self.assertEqual(len(got[0]["options"]), fleet.MAX_OPTIONS)

    def test_long_words_are_cut(self):
        got = self.stuck(asks(question("q" * 5000)))["context"]["questions"][0]["question"]
        self.assertEqual(len(got), fleet.QUESTION_LEN)


class Shapes(Base):
    """What the code downstream of the row may rely on: `stuck_of` and
    `state_of` do not re-check these, because the producer makes them true for
    anything a provider hands over."""
    JUNK = ("a question", 7, None, [], {}, {"kind": "poll"}, {"kind": "permission"},
            {"kind": "permission", "tool": 7, "command": ["ls"], "target": {"a": 1}},
            {"kind": "question"}, {"kind": "question", "questions": [None, "x", {"question": 4}]},
            {"kind": "question", "questions": [{"question": "Which?", "options": "docs"}]},
            {"kind": "question", "questions": [{"question": "Which?"}]})

    def test_asking_is_nothing_or_a_dict_with_every_key_the_tile_reads(self):
        for junk in self.JUNK + (asks(), prompt(), prompt("Edit", None)):
            with self.subTest(junk=junk):
                got = fleet.asking_of(junk)
                if got is None:
                    continue
                if got["kind"] == "permission":
                    self.assertEqual(set(got), {"kind", "tool", "command", "cut", "target"})
                    self.assertTrue(all(isinstance(got[k], str) for k in ("tool", "command", "target")))
                    self.assertIsInstance(got["cut"], bool)
                else:
                    self.assertEqual(set(got), {"kind", "questions"})
                    self.assertTrue(got["questions"])
                    for q in got["questions"]:
                        self.assertEqual(set(q), {"question", "header", "multi", "options"})
                        self.assertTrue(q["question"])
                        self.assertTrue(all(set(o) == {"label", "description"} for o in q["options"]))

    def test_a_tile_has_no_stuck_or_a_whole_one_whatever_the_provider_sent(self):
        for junk in self.JUNK + (asks(), prompt()):
            for status, waiting_for in (("waiting", "input needed"), ("waiting", "permission prompt"),
                                        ("idle", ""), ("busy", "")):
                with self.subTest(junk=junk, status=status):
                    got = self.tile(session("a", status=status, waitingFor=waiting_for, asking=junk))["stuck"]
                    if got is not None:
                        self.assertEqual(set(got), {"kind", "source", "reason", "context"})
                        self.assertEqual(got["kind"], "needs")
                        self.assertIsInstance(got["context"], dict)


if __name__ == "__main__":
    unittest.main()
