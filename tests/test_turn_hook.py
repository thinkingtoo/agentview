"""The hook that starts a turn.

It runs when you press enter. Two jobs: forget the line from the turn before
-- your prompt is the answer to whatever it asked -- and tell the session, in
one short paragraph, to say where it leaves things before the turn ends.

Nothing here blocks and nothing here is an error. That is the whole point:
a Stop hook that blocks is rendered to you as `Stop hook error:` in every
session, at every stop, and no setting changes that.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "hooks"))
import ask_commands
import lines
import turn_line


class Starting(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_a_prompt_starts_a_turn(self):
        turn_line.begin({"session_id": "s1", "prompt": "do the thing"}, root=self.root)
        self.assertTrue(lines.current_turn("s1", self.root))

    def test_a_prompt_forgets_the_line_before_it(self):
        lines.write("s1", did="x", ask="Which first?", n=1, root=self.root)
        turn_line.begin({"session_id": "s1", "prompt": "the second one"}, root=self.root)
        self.assertEqual(lines.read("s1", self.root), {})

    def test_the_session_is_told_what_to_run(self):
        got = turn_line.begin({"session_id": "s1", "prompt": "go"}, root=self.root)
        said = got["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(got["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("team-line", said)
        self.assertIn("s1", said)
        self.assertIn("--n", said)

    def test_the_instruction_stays_short(self):
        # It is injected on every turn of every session on this machine, so
        # its size is what every turn pays. Measured the way it is injected:
        # with a real session id (36 characters), and a writer path of fixed
        # length so the number does not depend on where the checkout lives.
        # With "s1" and whatever path the checkout had, this passed at 697 in
        # the main checkout and failed at 703 in any worktree, while the real
        # injection was 731. That size was approved on 2026-09-25 (n counts
        # what is left for the user), and the owner approved one more
        # sentence on 2026-10-19 (where a command goes, so the page can offer
        # it to copy) and, the same day, one clause for it (how a single quote
        # is written inside the ask, because the ask sits inside the hook's
        # own single quotes); the ceiling leaves room for one more sentence
        # and no more.
        sid = "00000000-0000-4000-8000-000000000000"
        with mock.patch.object(turn_line, "WRITER", Path("/home/alice/Projects/agentview/hooks/team-line")):
            said = turn_line.begin({"session_id": sid, "prompt": "go"},
                                   root=self.root)["hookSpecificOutput"]["additionalContext"]
        self.assertLess(len(said), 915, len(said))
        self.assertGreater(len(said), 860, "the budget was 750 before 2026-10-19; if the text got "
                                          "shorter, tighten the ceiling above to match")

    def test_the_size_does_not_depend_on_where_the_checkout_lives(self):
        sizes = set()
        for where in ("/a/hooks/team-line", "/home/alice/Projects/agentview-wt-06/hooks/team-line"):
            with mock.patch.object(turn_line, "WRITER", Path(where)):
                said = turn_line.begin({"session_id": "s1", "prompt": "go"},
                                       root=self.root)["hookSpecificOutput"]["additionalContext"]
            sizes.add(len(said) - len(where))
        self.assertEqual(len(sizes), 1)

    def test_a_payload_with_no_session_does_nothing(self):
        self.assertEqual(turn_line.begin({"prompt": "go"}, root=self.root), {})

    def test_it_never_blocks(self):
        got = turn_line.begin({"session_id": "s1", "prompt": "go"}, root=self.root)
        self.assertNotIn("decision", got)
        self.assertNotIn("continue", got)

    def test_a_command_the_person_must_run_is_asked_for_in_double_quotes_or_after_a_dollar(self):
        said = turn_line.begin({"session_id": "s1", "prompt": "go"},
                               root=self.root)["hookSpecificOutput"]["additionalContext"]
        sentence = ('A command the user must run goes inside double quotes, or after "$ " at '
                    "the end of the ask, within the single-quoted text, where a single quote is "
                    "written as '\\''.")
        self.assertIn(sentence, said)
        # Straight after the sentence on plain text, which is where a session reads how to quote.
        self.assertIn("in plain text (single quotes, no backticks). " + sentence, said)

    def test_backticks_stay_banned(self):
        # A session that slipped into double quotes around the whole ask would run them.
        said = turn_line.begin({"session_id": "s1", "prompt": "go"},
                               root=self.root)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("no backticks", said)
        self.assertNotIn("backticks around", said)
        self.assertNotIn("in backticks", said)


class WhatTheSessionThenWrites(unittest.TestCase):
    """The hook's own command line, run by real bash, and what the guesser makes of the ask.

    The sentence the hook says and the guesser behind the copy button are one
    agreement. These run the call as a session would (the placeholders of the
    hook's own line filled in, in bash itself) so that neither can move
    without the other: what bash hands `team-line` is what is stored, whole,
    and the commands the guesser then offers are the ones the sentence names.
    """
    SID = "00000000-0000-4000-8000-000000000000"

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.state = Path(self.dir.name)
        self.root = self.state / "agentview" / "lines"

    def command_line(self, ask):
        """The line the hook tells the session to run, its three placeholders filled, the
        ask written the way the hook's sentence says (a single quote inside it as the
        sentence spells it), which is what a session that follows the sentence runs."""
        said = turn_line.begin({"session_id": self.SID, "prompt": "go"},
                               root=self.root)["hookSpecificOutput"]["additionalContext"]
        spelled = re.search(r"a single quote is written as (\S+?)\. ", said)
        self.assertIsNotNone(spelled, said)
        escaped = ask.replace("'", spelled.group(1))
        found = [l for l in said.splitlines() if l.startswith(str(turn_line.WRITER))]
        self.assertEqual(len(found), 1, said)
        line = found[0]
        self.assertEqual(line.count("<"), 3, line)
        filled = line.replace("<number>", "1")
        self.assertEqual(filled.count("--did '<"), 1, line)
        filled = re.sub(r"--did '[^']*'", "--did 'where it stands'", filled)
        self.assertEqual(filled.count("--ask '<"), 1, line)
        return re.sub(r"--ask '[^']*'", lambda _: "--ask '" + escaped + "'", filled)

    def run_in_bash(self, ask):
        """Run the hook's call in bash, the way a session's Bash tool does; what is stored."""
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "XDG_STATE_HOME": str(self.state),
               "HOME": str(self.state), "PYTHONDONTWRITEBYTECODE": "1"}
        done = subprocess.run(["bash", "-c", self.command_line(ask)], env=env, cwd=self.dir.name,
                              capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual((done.returncode, done.stderr), (0, ""), done.stdout)
        got = lines.read(self.SID, self.root)
        self.assertEqual(got["n"], 1)
        self.assertEqual(got["by"], "session")
        return got["ask"]

    def check(self, ask, commands):
        stored = self.run_in_bash(ask)
        self.assertEqual(stored, ask)                      # byte for byte: nothing run, nothing expanded
        self.assertEqual(ask_commands.guess(stored), commands)

    def test_a_command_in_double_quotes_is_stored_whole_and_offered(self):
        self.check('Run "git status" or "make test" and tell me what comes out.',
                   ["git status", "make test"])

    def test_double_quotes_work_anywhere_in_the_ask(self):
        self.check('Before anything else, "git pull origin dev" has to run here, and then say which test failed.',
                   ["git pull origin dev"])

    def test_a_command_after_a_dollar_at_the_end_is_stored_whole_and_offered(self):
        self.check("Tests are green, and the last step is yours: $ make deploy", ["make deploy"])
        self.check("Run this and tell me the result: $ git log --oneline.", ["git log --oneline"])

    def test_both_forms_in_one_ask(self):
        self.check('Pull first with "git pull origin dev", then run $ make test',
                   ["git pull origin dev", "make test"])

    def test_a_dollar_inside_double_quotes_stays_what_it_is(self):
        # The hook's own single quotes hold the ask, so bash expands nothing in it.
        # HOME is the state folder here: an expansion would show.
        ask = 'Run "ls $HOME/projects" and "echo $(echo EXPANDED) > /tmp/stamp.txt" before you answer.'
        stored = self.run_in_bash(ask)
        self.assertEqual(stored, ask)
        self.assertIn("$HOME/projects", stored)
        self.assertNotIn(str(self.state), stored)
        self.assertEqual(ask_commands.guess(stored),
                         ["ls $HOME/projects", "echo $(echo EXPANDED) > /tmp/stamp.txt"])

    def test_a_command_after_a_dollar_with_words_behind_it_is_stored_whole_and_offered_nothing(self):
        # Where such a command ends cannot be told from the sentence going on, so the
        # sentence asks for it at the end of the ask, and a mid-mention is not guessed at.
        self.check("Run $ make test and say what it prints.", [])
        self.check("When the build is done, run $ make test and then tell me what it printed.", [])

    def test_the_two_forms_together_with_a_mid_mention_offer_only_what_the_sentence_names(self):
        self.check('Run "git status" first and $ make test after that, then tell me.', ["git status"])

    # A single quote inside the ask. The ask sits inside the hook's own single quotes, so the
    # sentence tells the session to write one as `'\\''`; `command_line` does exactly that.
    # What these pin is what bash then does with it: it hands `team-line` the ask whole.

    def plant(self):
        """Things that would show if bash did anything with the text but store it: a file a
        glob would expand to, a token a command substitution would read (HOME is the
        state folder here, so `~` is too)."""
        Path(self.dir.name, "x.md").write_text("")
        token = Path(self.dir.name, ".config", "maple", "token")
        token.parent.mkdir(parents=True)
        token.write_text("INVENTED-TOKEN-0001")

    def nothing_ran(self, stored):
        self.assertNotIn("INVENTED-TOKEN", stored)
        self.assertNotIn("x.md", stored)
        for stamp in ("STAMP", "STAMP2"):
            self.assertFalse(Path(self.dir.name, stamp).exists(), stamp)
        for found in (self.state / "agentview").rglob("*"):
            if found.is_file():
                self.assertNotIn(b"INVENTED-TOKEN", found.read_bytes(), str(found))

    def test_a_quoted_glob_in_a_command_is_stored_whole_and_offered(self):
        self.plant()
        ask = """Run "find . -name '*.md'" and tell me what it lists."""
        self.check(ask, ["find . -name '*.md'"])
        self.nothing_ran(self.run_in_bash(ask))

    def test_a_quoted_message_in_a_command_is_stored_whole_and_offered(self):
        self.plant()
        ask = """Run "git commit -m 'fix the build'" and tell me what it says."""
        self.check(ask, ["git commit -m 'fix the build'"])
        self.nothing_ran(self.run_in_bash(ask))

    def test_a_command_substitution_inside_single_quotes_is_stored_not_run(self):
        # An invented header that reads a token file. Run by bash it would store the token.
        self.plant()
        ask = """Run "curl -H 'X-Token:$(cat ~/.config/maple/token)' https://maple.example/api" and tell me."""
        self.check(ask, ["curl -H 'X-Token:$(cat ~/.config/maple/token)' https://maple.example/api"])
        self.nothing_ran(self.run_in_bash(ask))
        # Neither does a `;` inside the quotes start another command, or a substitution that writes.
        for ask in ("""Run "curl -H 'X-Note:a; touch STAMP' https://maple.example/api" and tell me.""",
                    """Run "curl -H 'X-Note:$(touch STAMP2)' https://maple.example/api" and tell me."""):
            self.nothing_ran(self.run_in_bash(ask))
            self.assertEqual(self.run_in_bash(ask), ask)

    def test_a_command_with_single_quotes_after_a_dollar_is_stored_whole_and_offered(self):
        self.plant()
        ask = "The last step is yours: $ git commit -m 'fix the build'"
        self.check(ask, ["git commit -m 'fix the build'"])
        self.nothing_ran(self.run_in_bash(ask))

    def test_an_apostrophe_is_stored_whole_and_offers_nothing(self):
        # What the README says: a command with a lone apostrophe gets no button (to a shell it
        # opens a quote), and a sentence with one is stored whole like any other.
        self.check("""Run "echo don't panic" and tell me what it prints.""", [])
        self.check("Don't merge before I look at it, it's the owner's call.", [])
