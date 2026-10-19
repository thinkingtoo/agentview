"""Commands a session leaves for the person in its session line.

The hook that writes the line is unchanged, so `ask` is free text and the
roster guesses which words in it are a command to run: text in quotes, or
after a `$`, that reads as a command. The tile reports them as `commands`, and
the page puts a copy button on each. A guess is sometimes wrong and that is
accepted; a guess never answers the session and never runs anything.

Through `roster()` with fake providers, like `test_needs_you`. Sessions,
branches and commands are all invented.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lines
from test_columns import Base, session


class Guess(Base):
    def line(self, sid, ask, n=1, by="session"):
        """The session has written its own line for the turn it is in."""
        lines.begin_turn(sid, self.lines)
        lines.write(sid, did="Notes page built.", ask=ask, n=n, by=by, root=self.lines)

    def commands(self, ask, **kw):
        self.line("a", ask, **kw)
        return self.tile(session("a"))["commands"]

    def test_a_command_in_quotes_is_offered(self):
        self.assertEqual(self.commands('Run "git push origin feature/maple-notes" for me?'),
                         ["git push origin feature/maple-notes"])

    def test_prose_in_quotes_is_not_a_command(self):
        self.assertEqual(
            self.commands('Should the page be called "release notes" or "what changed"?'), [])

    def test_a_single_quoted_word_is_a_name_not_a_command(self):
        self.assertEqual(self.commands('Keep the "git" prefix on the branch names?'), [])

    def test_a_command_after_a_dollar_is_offered_whatever_its_program(self):
        self.assertEqual(self.commands("When you are back, run: $ ./deploy-maple.sh --dry-run"),
                         ["./deploy-maple.sh --dry-run"])

    def test_a_dollar_command_ends_where_the_sentence_does(self):
        self.assertEqual(
            self.commands("Run $ systemctl --user restart maple-notes. Then tell me how it went."),
            ["systemctl --user restart maple-notes"])
        self.assertEqual(self.commands("Run $ make test, then tell me what it says?"),
                         ["make test"])

    def test_an_amount_of_money_is_not_a_command(self):
        self.assertEqual(self.commands("Is $5 a month fine for the notes hosting?"), [])
        self.assertEqual(self.commands("Is $ 5 a month fine for the notes hosting?"), [])

    def test_two_commands_are_offered_in_the_order_they_were_written(self):
        self.assertEqual(self.commands('Run "make build" and then "make test", please?'),
                         ["make build", "make test"])
        self.assertEqual(self.commands('Run "git pull" first, then $ make test'),
                         ["git pull", "make test"])
        self.assertEqual(self.commands('Run $ make build, then "git push origin main" for me.'),
                         ["make build", "git push origin main"])

    def test_a_dollar_inside_quotes_is_one_command_without_the_sign(self):
        self.assertEqual(self.commands('Could you run "$ make test" now?'), ["make test"])

    def test_a_quote_inside_a_dollar_command_does_not_make_a_second_one(self):
        self.assertEqual(self.commands('When ready, run $ git commit -m "update notes".'),
                         ['git commit -m "update notes"'])

    def test_a_command_in_backticks_or_other_quotes_is_offered(self):
        for ask in ("Run `make test` and tell me what it says?",
                    "Run 'make test' and tell me what it says?",
                    "Run \u201cmake test\u201d and tell me what it says?",
                    "Run \u2018make test\u2019 and tell me what it says?",
                    "Run \u00abmake test\u00bb and tell me what it says?"):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), ["make test"])

    def test_an_apostrophe_is_not_a_quote(self):
        self.assertEqual(self.commands("Don't run it yet, but isn't \"git status\" clean?"),
                         ["git status"])
        self.assertEqual(self.commands("It's the owner's call: is 'make test' enough?"),
                         ["make test"])
        self.assertEqual(self.commands("Is it the owner's call or the team's call?"), [])

    def test_a_quote_never_closed_is_not_a_command(self):
        self.assertEqual(self.commands('Run "git push origin feature/maple-no'), [])

    def test_an_open_dialog_hides_the_line_and_its_commands(self):
        # The tile shows the question, not the line written a turn ago, so a
        # command in that line has no place on it.
        self.line("a", 'Run "make test" for me?')
        asking = {"kind": "question", "questions": [{"question": "Publish the notes page?",
                                                     "header": "", "multi": False, "options": []}]}
        tile = self.tile(session("a", status="waiting", waitingFor="input needed", asking=asking))
        self.assertEqual((tile["stuck"]["source"], tile["commands"]), ("question", []))

    def test_several_things_left_quote_nothing_and_so_offer_nothing(self):
        self.assertEqual(self.commands('Run "make test", and may I push it?', n=2), [])

    def test_a_command_in_the_last_words_of_a_session_with_no_line_is_offered_too(self):
        tile = self.tile(session("a", said='Done. Should I run "make test" before I push?'))
        self.assertEqual((tile["need"], tile["commands"]), (
            'Should I run "make test" before I push?', ["make test"]))

    def test_a_line_read_out_of_the_transcript_offers_the_same_commands(self):
        self.assertEqual(self.commands('Should I run "make test" first?', by="read"), ["make test"])

    def test_a_command_cut_short_by_the_length_of_the_line_is_not_offered(self):
        # A line holds 160 characters and ends in an ellipsis when it was cut.
        # Half a command pasted into a terminal is worse than none.
        ask = "Please run $ python3 scripts/rebuild-the-maple-notes-index.py " + "--section=intro " * 10
        self.line("a", ask)
        tile = self.tile(session("a"))
        self.assertTrue(tile["stuck"]["context"]["text"].endswith("\u2026"))
        self.assertEqual(tile["commands"], [])

    def test_a_command_closed_before_the_cut_is_still_offered(self):
        ask = 'Run "make test" and then read what it says about ' + "the maple notes " * 12
        self.line("a", ask)
        tile = self.tile(session("a"))
        self.assertTrue(tile["stuck"]["context"]["text"].endswith("\u2026"))
        self.assertEqual(tile["commands"], ["make test"])

    def test_a_script_run_by_its_path_is_a_command_when_it_has_arguments(self):
        self.assertEqual(self.commands('Run "./deploy-maple.sh --dry-run" first?'),
                         ["./deploy-maple.sh --dry-run"])
        self.assertEqual(self.commands('Run "~/bin/maple-sync now" first?'),
                         ["~/bin/maple-sync now"])
        # A folder or a file in quotes is a name.
        self.assertEqual(self.commands('Should the notes live in "./notes" or "~/notes"?'), [])

    def test_markup_in_a_guessed_command_arrives_unchanged(self):
        # The page puts it in as text. Here it is whatever the session wrote,
        # character for character.
        literal = "echo <img src=x onerror=alert(1)> && echo &amp; \"done\""
        self.assertEqual(self.commands(f"Run $ {literal}."), [literal])

    def test_a_dollar_sign_followed_by_a_word_of_prose_is_not_a_command(self):
        self.assertEqual(self.commands("Should we charge in $ or in euros?"), [])
        self.assertEqual(self.commands("Is the price in $ per month the one we agreed?"), [])

    def test_a_dollar_command_may_be_a_program_of_the_projects_own(self):
        self.assertEqual(self.commands("Run $ maple-sync next , please."), ["maple-sync next"])
        self.assertEqual(self.commands("Could you type $ ls ?"), ["ls"])

    def test_a_script_alone_is_a_command_when_its_name_says_it_is_a_script(self):
        self.assertEqual(self.commands("Run `./scripts/deploy-maple.sh` on the server?"),
                         ["./scripts/deploy-maple.sh"])
        self.assertEqual(self.commands('Run "~/bin/sync-maple.py" on the server?'),
                         ["~/bin/sync-maple.py"])

    def test_words_that_are_also_programs_need_more_than_a_second_word_to_count(self):
        # Prose that happens to start with the name of a program.
        for ask in ('Reply "go ahead" and I will push it.',
                    'Should I "make sure" the tests ran first?',
                    'Do you want me to "find out" who owns it?',
                    'Is "claude code" the name you want in the title?',
                    'Is "source code" the name you want in the title?'):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_the_same_words_are_commands_with_a_target_flag_or_path(self):
        for command in ("make test", "go test ./...", "find . -name '*.md'",
                        "claude --resume maple", "tail -f /var/log/maple.log"):
            with self.subTest(command=command):
                self.assertEqual(self.commands(f"Run `{command}` for me?"), [command])

    def test_whatever_the_line_holds_the_tile_still_gets_its_commands(self):
        for ask in ('Is " " enough?', "Is `` or ` ` enough?", 'Run "$ " now?', "Run $ now?", "$", "$ ",
                    "Is \u00ab \u00bb a quote?", "\u201c\u201d", "'", '"', "Run \"", "Run $ \u2026"):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])


if __name__ == "__main__":
    unittest.main()
