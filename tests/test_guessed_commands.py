"""Commands a session leaves for the person in its session line.

The hook that writes the line is unchanged, so `ask` is free text and the
roster guesses which words in it are a command to run: text in quotes, or
after a `$`, that reads as a command. The tile reports them as `guessedCommands`, and
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
        return self.tile(session("a"))["guessedCommands"]

    def test_a_command_in_quotes_is_offered(self):
        self.assertEqual(self.commands('Run "git push origin feature/maple-notes" for me?'),
                         ["git push origin feature/maple-notes"])

    def test_prose_in_quotes_is_not_a_command(self):
        self.assertEqual(
            self.commands('Should the page be called "release notes" or "what changed"?'), [])

    def test_one_quoted_word_is_a_name_not_a_command(self):
        self.assertEqual(self.commands('Keep the "git" prefix on the branch names?'), [])

    def test_a_command_after_a_dollar_is_offered_whatever_its_program(self):
        self.assertEqual(self.commands("When you are back, run: $ ./deploy-maple.sh --dry-run"),
                         ["./deploy-maple.sh --dry-run"])

    def test_a_dollar_command_is_offered_when_it_ends_the_line(self):
        # A full stop, a question mark or an exclamation mark after it is the
        # end of the sentence, not part of the command.
        for ask in ("Run $ systemctl --user restart maple-notes.", "Could you run $ make test?",
                    "Run $ make test!", "Run $ make test ?"):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask)[0].split()[0], ask.split("$ ")[1].split()[0])

    def test_a_dollar_command_with_more_words_after_it_is_not_offered(self):
        # Where it ends cannot be told from a comma or a full stop: half a
        # command is worse than none, so nothing is offered.
        for ask in ("Run $ systemctl --user restart maple-notes. Then tell me how it went.",
                    "Run $ make test, then tell me what it says?",
                    "Run $ maple-sync next , please."):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_an_amount_of_money_is_not_a_command(self):
        self.assertEqual(self.commands("Is $5 a month fine for the notes hosting?"), [])
        self.assertEqual(self.commands("Is $ 5 a month fine for the notes hosting?"), [])

    def test_two_commands_are_offered_in_the_order_they_were_written(self):
        self.assertEqual(self.commands('Run "make build" and then "make test", please?'),
                         ["make build", "make test"])
        self.assertEqual(self.commands('Run "git pull" first, then $ make test'),
                         ["git pull", "make test"])
        # A `$` command with words after it is not offered, the quoted one is.
        self.assertEqual(self.commands('Run $ make build, then "git push origin main" for me.'),
                         ["git push origin main"])
        self.assertEqual(self.commands("Run $ make build $ make test"), ["make build", "make test"])

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
        self.assertEqual((tile["stuck"]["source"], tile["guessedCommands"]), ("question", []))

    def test_several_things_left_quote_nothing_and_so_offer_nothing(self):
        self.assertEqual(self.commands('Run "make test", and may I push it?', n=2), [])

    def test_words_read_out_of_the_transcript_offer_no_command(self):
        # `ask_from` takes out `*`, `_`, backticks and `#` to make a sentence of
        # the last words, so a command in them is not what the session wrote:
        # "pip install my_package" would be offered as "pip install mypackage".
        tile = self.tile(session("a", said='Done. Should I run "pip install my_package" next?'))
        self.assertEqual((tile["need"], tile["guessedCommands"]), (
            'Should I run "pip install mypackage" next?', []))

    def test_a_line_the_hook_read_for_the_session_offers_no_command_either(self):
        self.assertEqual(self.commands('Should I run "make test" first?', by="read"), [])

    def test_a_command_cut_short_by_the_length_of_the_line_is_not_offered(self):
        # A line holds 160 characters and ends in an ellipsis when it was cut.
        # Half a command pasted into a terminal is worse than none.
        ask = "Please run $ python3 scripts/rebuild-the-maple-notes-index.py " + "--section=intro " * 10
        self.line("a", ask)
        tile = self.tile(session("a"))
        self.assertTrue(tile["stuck"]["context"]["text"].endswith("\u2026"))
        self.assertEqual(tile["guessedCommands"], [])

    def test_a_command_closed_before_the_cut_is_still_offered(self):
        ask = 'Run "make test" and then read what it says about ' + "the maple notes " * 12
        self.line("a", ask)
        tile = self.tile(session("a"))
        self.assertTrue(tile["stuck"]["context"]["text"].endswith("\u2026"))
        self.assertEqual(tile["guessedCommands"], ["make test"])

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

    def test_an_amount_with_a_dollar_after_it_is_not_a_command(self):
        self.assertEqual(self.commands("Le budget est de 20 $ / mois, ok ?"), [])
        self.assertEqual(self.commands("Is 20 $ . a month fine?"), [])

    def test_a_dollar_command_may_be_a_program_of_the_projects_own(self):
        self.assertEqual(self.commands("Run $ maple-sync next."), ["maple-sync next"])
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

    def test_a_line_with_nothing_in_its_quotes_still_gets_a_tile_and_offers_nothing(self):
        for ask in ('Is " " enough?', "Is `` or ` ` enough?", 'Run "$ " now?', "Run $ now?", "$", "$ ",
                    "Is \u00ab \u00bb a quote?", "\u201c\u201d", "'", '"', "Run \"", "Run $ \u2026"):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_a_program_followed_by_a_plain_word_needs_to_be_a_known_subcommand(self):
        # Titles and tags that happen to start with a tool's name.
        for phrase in ("git history", "ssh keys", "docker setup", "python notes", "node status",
                       "touch base", "echo chamber", "npm package", "systemctl units", "uv tips"):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.commands(f'Name the page "{phrase}" or "release notes"?'), [])

    def test_commands_of_many_shapes_are_offered(self):
        for command in ("git status", "git push origin main", "git switch -c feature/maple-notes",
                        "docker compose up -d", "npm run build", "npm test", "uv run pytest",
                        "pip install -r requirements.txt", "kubectl get pods", "gh pr merge 12",
                        "systemctl restart maple-notes", "sudo systemctl restart maple-notes",
                        "python3 scripts/rebuild.py", "cd ~/maple", "ls notes", "ssh root@maple.example",
                        "ssh-add -l", "brew install jq", "ollama run llama3", "/home/alice/bin/sync.py now",
                        "MAPLE_ENV=test make test", "tar xzf notes.tar.gz", "grep -rn TODO notes"):
            with self.subTest(command=command):
                self.assertEqual(self.commands(f"Could you run `{command}` for me?"), [command])

    def test_quotes_inside_a_command_cut_by_the_length_limit_are_not_offered_on_their_own(self):
        # The line is cut at 160 characters. What is left of the `$` command
        # is not offered, and neither is the quoted half of it.
        for ask in ('Clear the cache in the container: $ docker exec -it maple-notes sh -c '
                    '"rm -rf /srv/maple/cache/*" && docker restart maple-notes && docker logs -f '
                    '--tail 50 maple-notes',
                    'On the VPS, run $ ssh root@maple.example "sudo systemctl restart maple-notes" && '
                    'ssh root@maple.example "journalctl -u maple-notes -n 50 --no-pager" | tail -n 20'):
            with self.subTest(ask=ask):
                self.line("a", ask)
                tile = self.tile(session("a"))
                self.assertTrue(tile["stuck"]["context"]["text"].endswith("\u2026"))
                self.assertEqual(tile["guessedCommands"], [])

    def test_a_quoted_argument_may_hold_a_comma_a_bracket_or_a_question_mark(self):
        for ask, command in (
                ('Commit with $ git commit -m "Ticket 14: copy buttons, tests".',
                 'git commit -m "Ticket 14: copy buttons, tests"'),
                ('Open the PR with $ gh pr create --title "Copy buttons (ticket 14)" --base dev?',
                 'gh pr create --title "Copy buttons (ticket 14)" --base dev'),
                ('Run $ git log --format="%h, %s" -5?', 'git log --format="%h, %s" -5'),
                ("Run $ grep -rn 'one. two' notes.", "grep -rn 'one. two' notes")):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [command])

    def test_a_command_with_a_quote_left_open_is_not_offered(self):
        # Pasted into a terminal it would leave the shell waiting for more.
        self.assertEqual(self.commands('Run $ git commit -m "fix typo, then push it'), [])
        self.assertEqual(self.commands("Run $ echo `date, then tell me"), [])

    def test_a_contraction_a_hyphen_or_a_comma_is_prose_not_a_flag(self):
        for phrase in ("find who's using it", "find what\u2019s stuck", "find long-running jobs",
                       "source of truth, v2", "find out, then tell me", "claude code's name"):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.commands(f'Is "{phrase}" the title you want?'), [])

    def test_a_flag_a_path_a_dot_a_number_or_a_string_still_marks_the_command(self):
        for command in ("find . -name '*.md'", "kill 1234", "touch notes.md", "claude --resume maple",
                        'echo "done" > out.txt', "curl https://maple.example/health", "source ~/.profile"):
            with self.subTest(command=command):
                self.assertEqual(self.commands(f"Could you run `{command}` for me?"), [command])

    def test_a_command_written_twice_is_offered_once(self):
        self.assertEqual(self.commands('Run "make test" now, and "make test" again after the push?'),
                         ["make test"])

    def test_a_dot_or_two_standing_alone_in_a_command_do_not_end_it(self):
        # `.` is the folder, `./...` every package: a period ends the sentence
        # only after a word, never after a space or another dot.
        for ask, command in (
                ("Tests are written. Could you run $ go test ./...?", "go test ./..."),
                ('Run $ find . -name "*.md" -mtime -1?', 'find . -name "*.md" -mtime -1'),
                ("Then run $ pip install -e .?", "pip install -e ."),
                ("Run $ cd .. && make test.", "cd .. && make test"),
                ('Run $ git add . && git commit -m "wip".', 'git add . && git commit -m "wip"'),
                ('Could you run $ docker build -t maple . && docker run --rm maple sh -c '
                 '"pytest -q tests/"?',
                 'docker build -t maple . && docker run --rm maple sh -c "pytest -q tests/"'),
                ("Run $ ls ./deploy.sh.", "ls ./deploy.sh")):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [command])

    def test_a_single_quote_left_open_is_not_offered_either(self):
        self.assertEqual(self.commands("Run $ git commit -m 'fix typo, then push it"), [])
        self.line("a", "On the VPS run $ ssh root@maple.example 'sudo systemctl restart maple-notes; "
                       "journalctl -u maple-notes -n 50, then tail the log and tell me what it says "
                       "about the notes service and the sync job that runs at night'")
        tile = self.tile(session("a"))
        self.assertTrue(tile["stuck"]["context"]["text"].endswith("\u2026"))
        self.assertEqual(tile["guessedCommands"], [])

    def test_an_apostrophe_inside_a_dollar_command_is_not_an_open_quote(self):
        self.assertEqual(self.commands("Run $ echo it's done."), ["echo it's done"])
        self.assertEqual(self.commands("Run $ git commit -m 'wip' --author 'Alice <a@maple.example>'."),
                         ["git commit -m 'wip' --author 'Alice <a@maple.example>'"])

    def test_names_that_are_also_words_need_a_sign_in_quotes_too(self):
        for phrase in ("diff view", "sudo access", "cd into the repo", "tailscale setup", "bash scripting",
                       "brew coffee", "apt choice", "tar pit"):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.commands(f'Is "{phrase}" or "release notes" the title?'), [])

    def test_a_wrapper_such_as_sudo_gives_way_to_the_command_it_runs(self):
        for command in ("sudo systemctl restart maple-notes", "sudo apt install jq", "sudo tar xzf notes.tar.gz",
                        "sudo diff a.txt b.txt", "nohup make build", "watch ls -l"):
            with self.subTest(command=command):
                self.assertEqual(self.commands(f"Could you run `{command}` for me?"), [command])

    def test_a_dollar_command_cut_by_a_comma_or_a_bracket_of_its_own_is_not_offered(self):
        # A quote glued to a flag is not seen as a quoted unit, so the comma in
        # it looks like the end of the clause and the rest is words: nothing is
        # offered, because the part before the comma is a different command.
        for ask in ("Could you run $ awk -F', ' '{print $3}' leads.csv?",
                    "Could you run $ git commit -m'wip, notes page' && git push?",
                    "Run $ make test && (cd docs && make html), then tell me?"):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_a_comma_on_a_flag_and_a_bang_between_words_belong_to_the_command(self):
        for ask, command in (
                ('Run $ psql -A -F, -c "select id, name from notes" notes?',
                 'psql -A -F, -c "select id, name from notes" notes'),
                ('Run $ find ~/notes -type f ! -name "*.md" -delete?', 'find ~/notes -type f ! -name "*.md" -delete'),
                ("Peux-tu lancer $ make test ?", "make test"),
                ("Lance $ make test !", "make test")):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [command])

    def test_a_command_ending_the_line_with_quotes_of_every_kind_is_offered_whole(self):
        for ask, command in (
                ("Could you run $ awk -F, '{print $2}' leads.csv", "awk -F, '{print $2}' leads.csv"),
                ('Run $ find ~/notes -type f ! -name "*.md" -delete', 'find ~/notes -type f ! -name "*.md" -delete'),
                ('Run $ psql -A -F, -c "select id, name from notes" notes', 'psql -A -F, -c "select id, name from notes" notes')):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [command])

    def test_a_program_the_lists_do_not_know_keeps_its_arguments_to_itself(self):
        # The click would otherwise put a command meant for a remote host, or
        # for the shell inside another program, on the local clipboard.
        for ask in ('Could you run $ fly ssh console -C "rm -rf /data/cache" on the prod app?',
                    'Run $ gcloud compute ssh maple --command "sudo systemctl restart maple-notes"?',
                    'Run $ heroku run "python manage.py migrate" -a maple, then tell me?',
                    'Should I add "alias deploy=\'ssh maple ./deploy.sh --prod\'" to your ~/.bashrc?',
                    'Run `sudo -u www-data bash -c "rm -rf /var/cache/maple/*"` now?'):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_a_known_program_in_quotes_is_offered_whole_with_its_inner_quote(self):
        # The outer quote is the command the session wrote; the inner one is
        # part of it and is never offered alone.
        self.assertEqual(self.commands("Run 'ssh maple \"rm -rf /srv/maple/cache\"' now?"),
                         ['ssh maple "rm -rf /srv/maple/cache"'])

    def test_quotes_nested_without_escapes_offer_nothing_cut_in_half(self):
        # `"git commit -m "` is one phrase's closing quote paired with the
        # next one's opening quote.
        self.assertEqual(self.commands('Run "git commit -m "Ticket 14: done"" for me?'), [])
        self.assertEqual(self.commands('Run git status" and "git log" now?'), [])
        self.assertEqual(self.commands('Run "git status" and "git log" now?'), ["git status", "git log"])

    def test_a_backtick_in_a_dollar_command_is_not_offered(self):
        # Pasted, the ticks would run what they hold.
        self.assertEqual(self.commands("Run $ make test and then `git push` if it passes?"), [])
        self.assertEqual(self.commands("Run $ echo `date`"), [])

    def test_an_amount_written_with_a_dollar_after_it_is_never_a_prompt(self):
        for ask in ("Les 20 $ du mois dernier, je les rembourse ?", "Le plan Pro co\u00fbte 20 $ US/mois, on le garde ?",
                    "\u00c7a co\u00fbte 20 $ du mois", "Total 1.5 $ ls"):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_go_has_its_own_subcommands_and_make_its_own_targets(self):
        for phrase in ("go deploy", "go check", "go all in", "go lint", "make all the difference",
                       "make sure it passes"):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.commands(f'You said "{phrase}": staging or prod?'), [])
        for command in ("go test", "go vet", "go mod tidy", "make test", "make build"):
            with self.subTest(command=command):
                self.assertEqual(self.commands(f"Could you run `{command}` for me?"), [command])

    def test_a_quote_escaped_inside_a_quote_is_not_cut_in_half(self):
        self.assertEqual(self.commands('Run "git commit -m \\"wip\\"" now?'), [])
        self.assertEqual(self.commands('Run `git commit -m \\"wip\\"` now?'), [])
        self.assertEqual(self.commands('Run $ git commit -m "say \\"hi, there\\"".'),
                         ['git commit -m "say \\"hi, there\\""'])

    def test_a_bracket_a_guillemet_or_a_path_before_a_full_stop_ends_the_command(self):
        for ask in ("(with $ make test), please?", "(run $ make test)", "\u00ab $ make test \u00bb et me dire ce que ca donne",
                    "Run $ rm -rf ~/.cache/maple/. Then restart the service.",
                    "Run $ rm -rf ~/.cache/maple/*. Then restart the service."):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])


if __name__ == "__main__":
    unittest.main()
