"""Commands a session leaves for the person in its session line.

The hook that writes the line is unchanged, so `ask` is free text and the
roster guesses which words in it are a command to run: text in quotes, or
after a `$`, that reads as a command. The tile reports them as `guessedCommands`, and
the page puts a copy button on each. A guess is sometimes wrong and that is
accepted; a guess never answers the session and never runs anything.

Through `roster()` with fake providers, like `test_needs_you`. Sessions,
branches and commands are all invented.
"""
import json
import random
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ask_commands
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
        # Only the last `$` command can be told from the words around it: what
        # stands between two prompts could be an argument of the first.
        self.assertEqual(self.commands("Run $ make build $ make test"), ["make test"])

    def test_a_dollar_inside_quotes_is_one_command_without_the_sign(self):
        self.assertEqual(self.commands('Could you run "$ make test" now?'), ["make test"])

    def test_a_dollar_after_the_start_of_a_quote_stays_in_the_command_as_written(self):
        # Only the prompt at the start of a quote is taken off. A `$ ` further in is
        # part of the command, and what is copied is the piece of the ask.
        for ask, command in (('Run "ls -la $ -x" now?', "ls -la $ -x"),
                             ('Run "echo $ -n x" now?', "echo $ -n x")):
            self.assertEqual(self.commands(ask), [command])
            self.assertIn(command, ask)

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
        self.assertEqual(self.commands('Run "~/bin/maple-sync --now" first?'),
                         ["~/bin/maple-sync --now"])
        # A folder or a file in quotes is a name, and so is a path with spaces
        # in it; a program of the project's own, with no flag and no script
        # name, is told from them by nothing.
        for ask in ('Should the notes live in "./notes" or "~/notes"?',
                    'Is "~/Google Drive/My Drive/notes.md" the file you mean?',
                    'Is "~/Library/Application Support/Code/User/settings.json" the file?',
                    'Back up "/srv/maple/data and /var/lib/maple" first?',
                    'Run "~/bin/maple-sync now" first?'):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

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
        self.assertEqual(self.commands("Run $ maple-sync --next."), ["maple-sync --next"])
        self.assertEqual(self.commands("Could you type $ ls -l ?"), ["ls -l"])

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
                        "python3 scripts/rebuild.py", "cd ~/maple", "ls -l notes", "ssh root@maple.example",
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

    def test_a_quote_pair_inside_a_dollar_command_keeps_its_apostrophes(self):
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


    def test_a_comma_after_the_last_flag_ends_the_command(self):
        # `-F,` belongs to the command only when a quote or another flag comes
        # after it; "-d, then tell me" is a clause.
        for ask in ("Run $ docker compose up -d, then tell me how it went.",
                    "Puoi lanciare $ ./scripts/deploy.sh --dry-run, then tell me how it went.",
                    "Run $ git log --oneline -5, then tell me.", "Run $ crontab -l, then tell me.",
                    "Run $ gh pr merge 12 --squash, then tell me.", "Run $ uv run pytest -q, then tell me."):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_a_full_stop_after_dots_before_a_new_sentence_leaves_the_end_unknown(self):
        for ask in ("Then run $ pip install -e . Then restart the server.",
                    "Then run $ pip install -e .. Then restart the server.",
                    "Tests are written. Could you run $ go test ./.... Then tell me what fails.",
                    "Then run $ pip install -e ..", "Could you run $ go test ./....",
                    "Run $ ls ... Then restart."):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])
        for ask, command in (("Could you run $ go test ./...", "go test ./..."),
                             ("Then run $ pip install -e .", "pip install -e ."),
                             ("Run $ go test ./pkg/...?", "go test ./pkg/...")):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [command])

    def test_a_full_stop_that_may_be_part_of_the_last_word_leaves_the_end_unknown(self):
        for ask in ("Clear the cache: $ rm -rf ~/.cache/maple/*.", "Clear the cache: $ rm -rf ~/.cache/maple/.",
                    "Draai $ cd ~.", "Go back: $ cd -."):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])
        self.assertEqual(self.commands("Run $ echo ${HOME}."), ["echo ${HOME}"])
        self.assertEqual(self.commands("Run $ git push origin <branch>."), ["git push origin <branch>"])

    def test_a_word_between_two_dollar_commands_is_not_glued_to_the_first(self):
        for ask in ("Run $ make build and $ make test.", "Run $ rm -rf ~/.cache/maple and $ make test.",
                    "Lance $ make build puis $ make test.", "Lancia $ make build e poi $ make test.",
                    "Draai $ make build en dan $ make test.", "Run $ make build, then $ make test."):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), ["make test"])

    def test_a_quote_nested_in_a_quote_of_the_same_kind_offers_nothing_in_half(self):
        for ask in ('Run "git clean -fd --exclude="notes/"" and tell me?',
                    'Run "gh pr create --title="Copy buttons" --base dev" now?',
                    'Run "docker run -e MAPLE_ENV="prod" maple-notes" for me?',
                    "Run \"jq '.items[] | select(.name==\"maple\")' notes.json\" and tell me?",
                    "Run 'git log --format='%h %s' -5'",
                    'Run "ssh maple "df -h" now" for me?',
                    "Run 'ssh maple 'df -h' now' for me?"):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_single_quotes_inside_single_quotes_do_not_offer_the_inner_command(self):
        for ask in ("Please run 'ssh maple 'sudo systemctl restart maple-notes'' and tell me?",
                    "Run 'sudo -u www-data bash -c 'rm -rf /var/cache/maple/*'' now?",
                    "Please run 'ssh maple 'df -h'' and tell me?"):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_a_quote_that_stands_alone_makes_the_others_of_its_kind_untrustworthy(self):
        # A single unmatched `"` may be the closing quote of a phrase the
        # session opened with another mark; which pairs are real is unknown.
        self.assertEqual(self.commands('Run "make test" and then say "done'), [])
        # The other kinds, and quotes inside a claimed region, are not strays.
        self.assertEqual(self.commands("Run \"make test\" and `make build`, it's the owner's call?"),
                         ["make test", "make build"])
        self.assertEqual(self.commands('Run `echo "hi"` and "git status" now?'), ['echo "hi"', "git status"])

    def test_a_backtick_inside_a_quote_is_not_offered(self):
        self.assertEqual(self.commands('The runbook says "ssh maple, then `sudo reboot`" - ok to do it?'), [])
        self.assertEqual(self.commands("The runbook says 'ssh maple, then `sudo reboot`' - ok to do it?"), [])

    def test_a_quoted_command_that_ends_in_a_comma_is_the_typography_of_the_quote(self):
        self.assertEqual(self.commands('Please run "git push origin main," then tell me.'), [])

    def test_a_nested_curly_quote_or_guillemet_is_not_a_command(self):
        for ask in ("Run “git clean -fd --exclude=“notes/”” and tell me?",
                    "Run «git clean -fd --exclude=«notes/»» et dis-moi?"):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_a_dollar_followed_by_a_word_with_a_slash_or_a_dot_in_it_is_prose(self):
        for ask in ("Should we charge in $ A/B or in euros?", "The budget is $ N/A for now, right?",
                    "Is it $ and/or euros?", "Prices in $ e.g. for the US?", "Is $ Node.js the stack?"):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])
        for ask, command in (("Run $ maple-sync --next.", "maple-sync --next"), ("Run $ deploy.sh --dry-run.", "deploy.sh --dry-run"),
                             ("Run $ /usr/local/bin/maple next.", "/usr/local/bin/maple next"),
                             ("Run $ tiroir_work --next.", "tiroir_work --next")):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [command])

    def test_a_quote_right_after_a_flag_is_the_argument_of_that_flag(self):
        # Pasted alone it would run on this machine what was meant for the
        # container, the remote host or the shell inside another program.
        for ask in ('Run docker exec -it maple-notes sh -c "rm -rf /srv/maple/cache/*" for me?',
                    'Run ssh maple --command "sudo systemctl restart maple-notes" for me?',
                    'Run git commit -m "rm -rf build" for me?',
                    'Run ($ docker exec -it maple-notes sh -c "rm -rf /srv/maple/cache/*") for me?',
                    'Run [$ docker exec -it maple-notes sh -c "rm -rf /srv/maple/cache/*"] for me?'):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])
        # A flag earlier in the sentence does not reach a quote after other words.
        self.assertEqual(self.commands('Use the -v flag, then run "make test" for me?'), ["make test"])

    def test_a_tool_that_nobody_says_in_a_sentence_still_needs_a_sign_in_quotes(self):
        for phrase in ("rm stale notes", "pytest fixtures", "certbot renewal", "grep results", "ls maple",
                       "mkdir build", "jq notes"):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.commands(f'Commit with the message "{phrase}" and push?'), [])
        for command in ("rm -rf build", "pytest -q tests", "grep -rn TODO notes", "mkdir -p build/maple",
                        "ls ~/maple", "chmod +x deploy.sh"):
            with self.subTest(command=command):
                self.assertEqual(self.commands(f"Could you run `{command}` for me?"), [command])


    def test_a_quoted_command_cut_by_the_length_limit_hides_the_quotes_inside_it(self):
        # The cut leaves the outer mark open, so the pair inside looks like a
        # command of its own: `rm -rf` meant for the VPS would run here.
        lead = "The cache on the VPS is stale after the deploy, and I have no ssh key for it. "
        for ask in (lead + 'Please run `ssh maple "rm -rf /srv/maple/cache/*" && ssh maple sudo systemctl '
                           'restart maple-notes` and tell me.',
                    "Deploy is done, but the restart needs your ssh key. Please run `ssh root@maple.example "
                    '"sudo systemctl restart maple-notes" && ssh root@maple.example journalctl -u maple-notes`.',
                    "Il deploy e finito ma il riavvio richiede la tua chiave ssh. Puoi lanciare 'ssh maple "
                    "\"rm -rf /srv/maple/cache/*\" && ssh maple sudo systemctl restart maple-notes' per favore?",
                    lead + 'Please run “ssh maple "rm -rf /srv/maple/cache/*" && ssh maple sudo systemctl '
                           'restart maple-notes” and tell me.'):
            with self.subTest(ask=ask):
                self.line("a", ask)
                tile = self.tile(session("a"))
                self.assertTrue(tile["stuck"]["context"]["text"].endswith("…"))
                self.assertEqual(tile["guessedCommands"], [])

    def test_a_dollar_command_that_starts_with_a_bracket_claims_the_quotes_inside_it(self):
        for ask in ('Run $ [ -f ~/.ssh/maple ] && ssh maple "rm -rf /srv/maple/cache/*"?',
                    'Could you run $ (cd /srv/maple && ssh maple "sudo systemctl restart maple-notes")?',
                    'Run $ { cd /srv/maple; ssh maple "sudo reboot"; }?'):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_a_quote_after_a_program_that_runs_commands_is_its_argument(self):
        for ask in ('Run ssh maple "sudo systemctl restart maple-notes" for me?',
                    'Run timeout 30 ssh maple "df -h" for me?',
                    'Run watch -n 5 "kubectl get pods" and tell me when they are all ready?',
                    'Run ssh -p 2222 maple "df -h" for me?',
                    'Run tmux send-keys -t maple "make test" Enter and tell me?',
                    'Run $ make deploy && (ssh maple "sudo systemctl restart maple-notes")?',
                    'Run docker exec maple-notes "ls -la" for me?'):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])
        # Another clause, or a quote that stands before the program, is not its argument.
        self.assertEqual(self.commands('Run "make test", then ssh maple and tell me.'), ["make test"])
        self.assertEqual(self.commands('Run "ssh maple" and then "df -h" on it?'), ["df -h"])

    def test_money_with_a_space_after_the_sign_is_not_a_prompt(self):
        for ask in ("Should the table show the $ diff or the % diff?", "Is the plan billed in $ per-seat?",
                    "Should prices be shown in $ pre-tax or tax-included?", "Is it the $ source column?",
                    "Is the bound $ n-1 $?", "The cost is $ cat food per month, right?"):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_a_dollar_command_needs_the_evidence_a_quoted_one_needs(self):
        # A path is a program by itself; a program of the project's own needs a
        # script name or a sign; a lone known word is a word.
        for ask, command in (("Run $ ./deploy-maple.", "./deploy-maple"), ("Run $ ~/bin/maple-sync.", "~/bin/maple-sync"),
                             ("Run $ maple-sync --next.", "maple-sync --next"), ("Run $ deploy.sh.", "deploy.sh")):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [command])
        for ask in ("Run $ maple-sync next.", "Could you type $ ls ?", "Run $ make.", "Run $ pytest."):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])

    def test_an_assignment_in_prose_is_not_a_command(self):
        for ask in ('The sample is small ("N=12 users"), keep going?',
                    'Should the label say "CTR=2.1% (was 1.8%)"?', 'Is "A=1 and B=2" the condition you meant?'):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), [])
        self.assertEqual(self.commands('Run "MAPLE_ENV=test make test" for me?'), ["MAPLE_ENV=test make test"])

    def test_a_double_bang_is_the_shells_not_a_sentence_end(self):
        self.assertEqual(self.commands("If it says permission denied, run $ sudo !!"), [])
        self.assertEqual(self.commands("If it says permission denied, run $ sudo !!?"), [])

    def test_a_markdown_bold_around_a_command_is_not_part_of_it(self):
        self.assertEqual(self.commands("**Run $ make test**"), ["make test"])
        self.assertEqual(self.commands("Run **$ make test**."), [])
        self.assertEqual(self.commands("Please run $ make test**, then tell me."), [])
        # A glob that ends in `*` and a bold that closes after it cannot be told apart.
        self.assertEqual(self.commands("**Run $ rm -rf /srv/maple/cache/***"), [])

    def test_an_apostrophe_in_a_dollar_command_is_an_open_quote_to_the_shell(self):
        self.assertEqual(self.commands("Run $ make test if that's ok?"), [])
        self.assertEqual(self.commands("Run $ git commit -m \"it's done\"."), ["git commit -m \"it's done\""])

    def test_french_guillemets_may_hold_a_space_each_side(self):
        for ask in ("Lance « make test » ?", "Lance « make test » ?",
                    "Lance « make test » ?"):
            with self.subTest(ask=ask):
                self.assertEqual(self.commands(ask), ["make test"])

    def test_an_apostrophe_at_the_end_of_a_word_only_doubts_the_single_quotes(self):
        self.assertEqual(self.commands('Run "make test" for the users\' notes?'), ["make test"])
        self.assertEqual(self.commands('Lancia "make test" tra un po\' di tempo?'), ["make test"])
        self.assertEqual(self.commands("Run 'make test' for the users' notes?"), [])


class GuessStore(Base):
    """The roster hands the guesser what the store gives it, and the store is a
    folder anyone can write a file in by hand: whatever is there, the guesser sees
    one clipped line of text, or nothing, and the roster does not raise."""

    def by_hand(self, text=None, **fields):
        lines.begin_turn("a", self.lines)
        if text is None:
            text = json.dumps({"did": "Notes page built.", "n": 1, "at": time.time(), "by": "session",
                               "turn": lines.current_turn("a", self.lines), **fields})
        (self.lines / "a.json").write_text(text, encoding="utf-8")
        return self.tile(session("a"))

    def test_a_line_longer_than_the_hook_allows_is_cut_before_it_is_guessed_on(self):
        tile = self.by_hand(ask='Run "make test" now? ' + "x " * 5000)
        self.assertLessEqual(len(tile["need"]), lines.LIMIT)
        self.assertEqual(tile["guessedCommands"], ["make test"])
        # What was cut away is gone, command and all.
        tile = self.by_hand(ask="x " * 100 + 'Run "make test" now?')
        self.assertEqual((len(tile["need"]) <= lines.LIMIT, tile["guessedCommands"]), (True, []))

    def test_whitespace_in_a_line_is_folded_before_it_is_guessed_on(self):
        tile = self.by_hand(ask='Run "$\t　make\ttest" now?\n')
        self.assertEqual(tile["need"], 'Run "$ make test" now?')
        self.assertEqual(tile["guessedCommands"], ["make test"])

    def test_a_line_that_is_not_text_offers_nothing(self):
        for ask in ([1, 2], 5, None, {"a": 1}, True):
            with self.subTest(ask=ask):
                self.assertEqual(self.by_hand(ask=ask)["guessedCommands"], [])

    def test_a_file_nested_deeper_than_json_can_read_is_no_line_and_no_error(self):
        depth = 70000
        tile = self.by_hand('{"ask": ' + "[" * depth + "]" * depth + ', "n": 1, "at": 1}')
        self.assertEqual((tile["need"], tile["guessedCommands"]), ("", []))


class GuessEdges(unittest.TestCase):
    """The rules that decide a quote is not a command, one line each, so that a rule
    taken out is noticed. Every line is invented."""

    def test_a_quote_after_a_runner_is_its_argument_within_six_words_and_not_after_(self):
        # The six words before the quote count, the runner among them: `ssh` and
        # five words of options still hold it, `ssh` and six let it go (a known
        # limit, named in the README).
        five = 'Run ssh -t -i ~/.ssh/k -p deploy@maple "sudo systemctl restart maple" when ready?'
        six = 'Run ssh -t -i ~/.ssh/k -p 22 deploy@maple "sudo systemctl restart maple" when ready?'
        self.assertEqual(ask_commands.guess(five), [])
        self.assertEqual(ask_commands.guess(six), ["sudo systemctl restart maple"])

    def test_a_runner_in_an_earlier_sentence_does_not_hold_a_quote_in_this_one(self):
        self.assertEqual(ask_commands.guess('The ssh key is fixed. Now run "make test" for me?'), ["make test"])

    def test_a_quote_never_closed_doubts_every_quote_on_the_line(self):
        self.assertEqual(ask_commands.guess("""Run 'make test now and "git push origin dev" after?"""), [])

    def test_a_quote_glued_to_a_word_or_an_equals_sign_is_an_argument_not_a_phrase(self):
        self.assertEqual(ask_commands.guess('Set MAPLE_CMD="git status --short" in the env file?'), [])
        self.assertEqual(ask_commands.guess('Use alias gs="git status" in the shell?'), [])

    def test_a_quote_closed_by_a_letter_or_a_hyphen_is_not_closed(self):
        self.assertEqual(ask_commands.guess('Is "make test"-style naming ok, and "git push origin dev"?'), [])

    def test_a_command_that_ends_in_a_semicolon_or_a_colon_is_not_offered(self):
        for end in (";", ":"):
            with self.subTest(end=end):
                self.assertEqual(ask_commands.guess(f'Then run "git push origin dev{end}" now?'), [])

    def test_half_a_command_is_never_offered(self):
        # A quote the shell would wait on to close, whether the apostrophe is the
        # session's or part of a word.
        for ask in ('Then run $ git commit -m "fix the notes', "Then run $ echo it's done > /tmp/x",
                    'Run "echo it\'s done > /tmp/maple-note" now?'):
            with self.subTest(ask=ask):
                self.assertEqual(ask_commands.guess(ask), [])

    def test_a_quote_that_holds_an_escaped_quote_or_a_quote_of_its_own_kind_is_not_offered(self):
        self.assertEqual(ask_commands.guess("""Then run 'echo "a\\" b" > /tmp/x' please?"""), [])
        self.assertEqual(ask_commands.guess('Then run "echo \u201chi\u201d > /tmp/maple-x" please?'), [])

    def test_twenty_dollars_is_an_amount(self):
        self.assertEqual(ask_commands.guess("Is the price 20 $ per-seat for 12 users?"), [])

    def test_a_comma_ends_the_clause_a_runner_was_named_in(self):
        self.assertEqual(ask_commands.guess('Once ssh works, run "make test" for me?'), ["make test"])

    def test_an_escaped_quote_in_the_sentence_outside_the_quotes_does_not_doubt_them(self):
        self.assertEqual(ask_commands.guess('Run "make test" and keep the \\" in the notes?'), ["make test"])

    def test_a_tool_with_a_subcommand_the_list_lacks_gets_no_button(self):
        # The safe direction: a missing button costs a selection with the mouse.
        self.assertEqual(ask_commands.guess('Try "npm login" or "git lfs pull"?'), [])


class RealShapes(unittest.TestCase):
    """Shapes the sessions really wrote in the days after ticket 14, each one
    a command the session marked that got no button (ticket 18). The lines are
    invented in the shape of the real ones."""

    def test_a_command_with_claude_codes_shell_prefix_after_a_dollar_keeps_the_prefix(self):
        # The `!` says the command goes into a Claude prompt, so it is copied too.
        self.assertEqual(ask_commands.guess("Run the id check: $ ! bash /home/maple/bin/ids.sh"),
                         ["! bash /home/maple/bin/ids.sh"])

    def test_a_quoted_command_with_the_shell_prefix_keeps_it(self):
        # Ticket 14 left these without a button; sessions wrote them often.
        self.assertEqual(ask_commands.guess('Run "! ssh-add ~/.ssh/id_maple" in this pane?'),
                         ["! ssh-add ~/.ssh/id_maple"])

    def test_a_dollar_the_session_escaped_still_marks_the_command(self):
        # Inside the hook's single quotes the backslash stays in the text.
        self.assertEqual(ask_commands.guess("Run it in a terminal. \\$ bash /home/maple/bin/set-pass.sh"),
                         ["bash /home/maple/bin/set-pass.sh"])

    def test_a_claude_slash_command_to_type_in_a_pane_is_offered(self):
        for ask, command in (("Type it in the boss pane: $ /maple-skills:wayfinder", "/maple-skills:wayfinder"),
                             ('Type "/maple-skills:wayfinder" in this pane', "/maple-skills:wayfinder"),
                             ('Type "/autocompact 450k" in the boss pane', "/autocompact 450k"),
                             ('Type "/compact --keep-tools" in that pane?', "/compact --keep-tools")):
            with self.subTest(ask=ask):
                self.assertEqual(ask_commands.guess(ask), [command])

    def test_a_bare_command_that_ends_the_ask_after_a_colon_is_offered(self):
        # The owner's choice for ticket 18: no marker, but strong evidence.
        for ask, command in (
                ("Run the wizard on the laptop: bash /home/maple/stage/wizard.sh "
                 "(browser sign-in, only your hand can do it)", "bash /home/maple/stage/wizard.sh"),
                ("Run the script that adds the rule: ! python3 -I /home/maple/add-rule.py",
                 "! python3 -I /home/maple/add-rule.py"),
                ("Save the password on the box: ssh maple-box 'umask 077; cat > /root/p.txt'.",
                 "ssh maple-box 'umask 077; cat > /root/p.txt'")):
            with self.subTest(ask=ask):
                self.assertEqual(ask_commands.guess(ask), [command])

    def test_a_bare_command_alone_in_brackets_is_offered(self):
        self.assertEqual(ask_commands.guess("Unlock the key (ssh-add ~/.ssh/id_maple) so I can push"),
                         ["ssh-add ~/.ssh/id_maple"])

    def test_a_bare_sentence_that_starts_with_a_program_is_not_a_command(self):
        for ask in ("Note: rm stale notes from ~/notes before Friday",
                    "Decide: git history or a new file?",
                    "Choice: make the page or the docs first",
                    "Run ssh-add ~/.ssh/id_maple in a terminal and type the passphrase",
                    "Read the plan (see ~/notes/plan.md) and decide",
                    "Pick one (cat or dog)",
                    "Next: find out who owns ~/maple/notes"):
            with self.subTest(ask=ask):
                self.assertEqual(ask_commands.guess(ask), [])

    def test_two_commands_joined_by_a_plus_are_prose_not_one_command(self):
        for ask in ("Start the deploy: $ git commit --allow-empty + git push in maple-site",
                    'Run "git commit --allow-empty + git push" in maple-site'):
            with self.subTest(ask=ask):
                self.assertEqual(ask_commands.guess(ask), [])

    def test_a_plus_that_is_an_argument_stays_in_the_command(self):
        self.assertEqual(ask_commands.guess("Check it: $ echo 1 + 2"), ["echo 1 + 2"])

    def test_a_folder_at_the_root_in_quotes_is_still_a_name(self):
        for ask in ('Is "/tmp" the right place?', 'Keep it under "/opt" or "/srv"?',
                    'Is the split "A/B" or "/ maple"?'):
            with self.subTest(ask=ask):
                self.assertEqual(ask_commands.guess(ask), [])


class GuessGrid(unittest.TestCase):
    """The property the buttons rest on, over a grid of realistic lines.

    Whatever `guess()` offers is a command the session wrote as one whole
    command: never a shortened one, one with words of the sentence glued on, or
    the inside of another. Offering nothing is always allowed; the lines where
    the end of a command is plain must offer it.
    """

    COMMANDS = (
        "make test", "git push origin main", "docker compose up -d", "go test ./...", "pip install -e .",
        "rm -rf ~/.cache/maple/*", "ls -la", 'git add . && git commit -m "wip"',
        "awk -F, '{print $2}' leads.csv", "find . -name '*.md'", 'psql -A -F, -c "select id, name from notes" notes',
        "./scripts/deploy.sh --dry-run", "systemctl --user restart maple-notes", "cd ..", "uv run pytest -q",
        "gh pr merge 12 --squash", "crontab -l", "git log --oneline -5", "sudo systemctl restart maple-notes",
        'ssh root@maple.example "journalctl -u maple-notes -n 50"', "git clean -fd --exclude=notes/",
        "echo ${HOME}", "cd ~", "cd -", """jq '.items[] | select(.name=="maple")' notes.json""",
        "git commit -m 'Ticket 14: copy buttons, tests'", "tar xzf notes.tar.gz", "kubectl get pods -n maple",
        "MAPLE_ENV=test make test", "python3 scripts/rebuild.py", "docker run -e MAPLE_ENV=prod maple-notes",
        "git push origin <branch>", "rm -f build/*.o", 'docker build -t maple . && docker run --rm maple',
        'git commit -m "say hi, there"', "npm run build", "ssh-add -l")
    # Commands whose end is plain: written whole, they are offered whole.
    PLAIN = ("make test", "git push origin main", "docker compose up -d", "ls -la", "uv run pytest -q",
             "gh pr merge 12 --squash", "crontab -l", "git log --oneline -5", "sudo systemctl restart maple-notes",
             "systemctl --user restart maple-notes", "kubectl get pods -n maple", "tar xzf notes.tar.gz",
             "python3 scripts/rebuild.py", "./scripts/deploy.sh --dry-run", "MAPLE_ENV=test make test",
             "npm run build", "ssh-add -l")
    LEADS = ("Run ", "Could you run ", "Puoi lanciare ", "Peux-tu lancer ", "Kun je ", "Then run ",
             "Clear the cache: ", "Tests are written. Could you run ")
    QUOTES = (('"', '"'), ("'", "'"), ("`", "`"), ("“", "”"), ("«", "»"),
              ("‘", "’"))
    # After a quoted command: more of the sentence, a second command, another
    # sentence. Nothing here is part of the command.
    QUOTED_ENDS = ("", ".", "?", " ?", "!", " for me?", ", then tell me how it went.", " and tell me what fails?",
                   ". Then restart the server.", ' and then "git status" to check?')
    # After a `$` command: where a sentence ends, or another sentence or
    # command starts after a break. A word that closes the sentence ("now") is
    # the accepted run-on and is not here.
    DOLLAR_ENDS = ("", ".", "?", " ?", "!", ", then tell me how it went.", ". Then restart the server.",
                   "? Thanks.", " and $ make build.", " puis $ make build.", ", then $ make build.")

    def lines(self, command):
        for lead in self.LEADS:
            for end in self.DOLLAR_ENDS:
                yield "dollar", f"{lead}$ {command}{end}", end
            for opening, closing in self.QUOTES:
                for end in self.QUOTED_ENDS:
                    yield "quoted", f"{lead}{opening}{command}{closing}{end}", end

    def test_nothing_but_the_intended_command_is_ever_offered(self):
        wrong, seen = [], 0
        for command in self.COMMANDS:
            allowed = {command, "make build", "git status"}
            for kind, line, _ in self.lines(command):
                seen += 1
                offered = ask_commands.guess(line)
                if not set(offered) <= allowed:
                    wrong.append((line, offered))
        self.assertGreater(seen, 10000)
        self.assertEqual(wrong[:12], [], f"{len(wrong)} of {seen} lines offer a wrong text")

    def test_a_line_cut_at_any_position_never_offers_a_piece_of_a_command(self):
        # The hook cuts a line at 160 characters wherever that falls: inside the
        # command, inside a quote, between two quotes. Whatever is left must
        # offer the command whole or nothing.
        inner = ('ssh maple "rm -rf /srv/maple/cache/*" && ssh maple sudo systemctl restart maple-notes',
                 "ssh root@maple.example 'sudo systemctl restart maple-notes' && ssh root@maple.example journalctl -u maple-notes",
                 'docker exec -it maple-notes sh -c "rm -rf /srv/maple/cache/*"',
                 'git commit -m "Ticket 14: copy buttons, tests" && git push origin feature/maple-notes',
                 "psql -A -F, -c 'select id, name from notes' notes | tee /tmp/notes.csv",
                 "MAPLE_ENV=test make test && make build", "find . -name '*.md' -mtime -1 -delete")
        leads = ("Please run ", "Puoi lanciare ")
        wrong, seen = [], 0
        for command in inner:
            for lead in leads:
                forms = [f"{lead}$ {command}"] + [f"{lead}{opening}{command}{closing}" for opening, closing in self.QUOTES]
                for form in forms:
                    for end in ("?", ".", ""):
                        line = form + end
                        for k in range(len(lead), len(line) + 1):
                            cut = line[:k].rstrip() + "\u2026" if k < len(line) else line
                            seen += 1
                            offered = ask_commands.guess(cut)
                            if not set(offered) <= {command}:
                                wrong.append((cut, offered))
        self.assertGreater(seen, 20000)
        self.assertEqual(wrong[:8], [], f"{len(wrong)} of {seen} cut lines offer a piece")

    def test_money_with_a_space_after_the_dollar_never_offers_a_button(self):
        leads = ("Is the price in ", "Should the table show the ", "Billed in ", "Le prix en ", "Prezzo in ", "Prijs in ")
        words = sorted(ask_commands.KNOWN) + ["per-seat", "pre-tax", "net-30", "n-1", "x_1", "tax-included",
                                              "year-over-year", "A/B", "N/A", "e.g.", "vs", "per", "user"]
        rests = ("?", " or the % diff?", " per month?", " column?", " and euros?", " vs EUR?", " (net)?",
                 ", right?", ".", " $?", " $ per year?")
        offered = [(line, ask_commands.guess(line)) for line in (f"{lead}$ {word}{rest}" for lead in leads
                                                                   for word in words for rest in rests)
                   if ask_commands.guess(line)]
        self.assertEqual(offered[:8], [])

    def test_a_command_with_a_plain_end_is_offered_whole(self):
        missing, seen = [], 0
        for command in self.PLAIN:
            for lead in self.LEADS:
                for end in ("", ".", "?", " ?", "!"):
                    line = f"{lead}$ {command}{end}"
                    seen += 1
                    if ask_commands.guess(line) != [command]:
                        missing.append((line, ask_commands.guess(line)))
                for opening, closing in self.QUOTES:
                    for end in ("", ".", "?", " for me?"):
                        line = f"{lead}{opening}{command}{closing}{end}"
                        seen += 1
                        if ask_commands.guess(line) != [command]:
                            missing.append((line, ask_commands.guess(line)))
        self.assertEqual(missing[:12], [], f"{len(missing)} of {seen} lines miss their command")


class GuessInvariants(unittest.TestCase):
    """What holds on any input, invented or real, with no exceptions.

    A wrong guess on a shape nobody writes is a known limit and is named in the
    README. These are the properties a button can never lose: the text it
    copies is a piece of the ask exactly as written, markup in it is only ever
    text (the page escapes it; see `test_a_guessed_command_with_markup...`), the
    guesser never raises, and its time does not grow faster than the line.
    """

    PIECES = ('"', "'", "`", "\u201c", "\u201d", "\u00ab", "\u00bb", "\u2018", "\u2019", "$", "$ ", "\\", "<<", "**",
              "__", "|", "&&", "||", ";", "(", ")", "[", "]", "{", "}", ".", "..", "...", "\u2026", "?", "!", ",", ":",
              "-", "--", "-F,", "=", "~/", "./", "/", "*", "\u2014", "\u00a0", "\u2028", "make test",
              "git push origin dev", "rm -rf /srv/maple/cache/*", "ssh maple", "echo", "sudo", "run", "then", "and",
              "Could you", "please", "-e", "go test ./...", "A=1", "12", "$5", "20 $", "it's", "users'", "!!", "# x",
              "<b>x</b>", "<script>alert(1)</script>", "&lt;", "$(rm -rf ~)", "${HOME}")

    def test_whatever_is_offered_is_a_piece_of_the_ask_as_written(self):
        rng = random.Random(14)
        bad, offers = [], 0
        for _ in range(20000):
            joiner = rng.choice(("", " ", " "))
            ask = lines._clip(joiner.join(rng.choice(self.PIECES) for _ in range(rng.randint(1, 45))))
            for command in ask_commands.guess(ask):
                offers += 1
                if not (command and command == command.strip() and command in ask):
                    bad.append((ask, command))
        self.assertGreater(offers, 100)
        self.assertEqual(bad[:5], [], f"{len(bad)} of {offers} offers are not a piece of their ask")

    def test_the_grid_and_the_cut_lines_offer_only_pieces_of_the_ask(self):
        bad = []
        for command in GuessGrid.COMMANDS:
            for kind, line, _ in GuessGrid(methodName="test_a_command_with_a_plain_end_is_offered_whole").lines(command):
                for k in (len(line), len(line) // 2, len(line) // 3):
                    ask = line if k == len(line) else line[:k].rstrip() + "\u2026"
                    bad.extend((ask, c) for c in ask_commands.guess(ask) if c not in ask)
        self.assertEqual(bad[:5], [])

    def test_markup_in_the_ask_reaches_the_page_only_as_text(self):
        # The guesser copies markup as it is; the page escapes every value it
        # paints (R7). Both halves are checked: this one keeps the markup in the
        # offered text intact, the page smoke checks the escaping.
        ask = 'Run "echo <b>x</b> | tee /tmp/maple-notes" for me?'
        self.assertEqual(ask_commands.guess(ask), ["echo <b>x</b> | tee /tmp/maple-notes"])

    def test_no_line_makes_the_guesser_raise_or_slow_down(self):
        rng = random.Random(15)
        worst = 0.0
        for _ in range(20000):
            ask = lines._clip(rng.choice(("", " "))
                              .join(rng.choice(self.PIECES) for _ in range(rng.randint(1, 60))))
            started = time.perf_counter()
            ask_commands.guess(ask)
            worst = max(worst, time.perf_counter() - started)
        self.assertLess(worst, 0.05)

    def test_a_long_run_of_one_mark_costs_a_bounded_time(self):
        # The line is clipped to 160 characters before it gets here, so this is
        # about the guesser alone: a text longer than any line offers nothing,
        # and one at the bound costs little, however it is made of marks.
        for unit in ("\u201c", "' \" ", '"', "$ make ", "\\ ", "\u00ab ", "`", "** ", "a. ", "-F, '", "( $ a "):
            with self.subTest(unit=unit):
                started = time.perf_counter()
                self.assertEqual(ask_commands.guess(unit * (30000 // len(unit))), [])
                ask_commands.guess((unit * ask_commands.LONGEST)[:ask_commands.LONGEST])
                self.assertLess(time.perf_counter() - started, 0.1)

    def test_a_line_as_long_as_the_hook_allows_is_still_guessed_on(self):
        ask = lines._clip("Please run `make test` " + "and then tell me how it went, " * 10)
        self.assertLessEqual(len(ask), lines.LIMIT)
        self.assertEqual(ask_commands.guess(ask), ["make test"])

    def test_the_bound_is_exact_and_a_longer_text_offers_nothing_rather_than_a_cut_command(self):
        self.assertEqual(ask_commands.LONGEST, 400, "the README names this number")
        self.assertGreaterEqual(ask_commands.LONGEST, lines.LIMIT)
        tail = 'Run "git push origin dev" now?'
        for length, want in ((ask_commands.LONGEST, ["git push origin dev"]), (ask_commands.LONGEST + 1, [])):
            with self.subTest(length=length):
                ask = "a" * (length - len(tail) - 1) + " " + tail
                self.assertEqual(len(ask), length)
                self.assertEqual(ask_commands.guess(ask), want)
        # A command that straddles the bound is not offered cut short.
        ask = "a" * 380 + " $ git push origin dev --force-with-lease now"
        self.assertGreater(len(ask), ask_commands.LONGEST)
        self.assertEqual(ask_commands.guess(ask), [])

    def test_what_is_offered_is_stripped_whatever_whitespace_stands_inside_the_quote(self):
        # The store folds whitespace, so a line never has these; the guesser holds
        # the property itself rather than lean on that.
        for space in ("\t", "\u3000", "\u00a0", "\u2028", "\x0b", "\x0c", "\x1f", "  "):
            for opening, closing in (('"', '"'), ("'", "'"), ("`", "`"), ("\u201c", "\u201d"), ("\u00ab", "\u00bb")):
                ask = f"Run {opening}$ {space}make test{closing} now"
                with self.subTest(ask=ask):
                    self.assertEqual(ask_commands.guess(ask), ["make test"])

    def test_whatever_is_offered_is_a_stripped_piece_of_the_ask_also_when_nothing_clipped_it(self):
        rng = random.Random(16)
        spaces = ("\t", "\u3000", "\u00a0", "\n", "\r", "\x0b", "\x0c", "\u2028", "  ")
        pairs = (('"', '"'), ("'", "'"), ("`", "`"), ("\u201c", "\u201d"), ("\u00ab", "\u00bb"))
        pieces = self.PIECES + spaces
        bad, offers = [], 0
        for i in range(20000):
            if i % 2:
                # Quoted commands with whitespace of every kind inside and around them.
                opening, closing = rng.choice(pairs)
                ask = (rng.choice(pieces) + " Run " + opening + rng.choice(("", "$ ", "$ ")) + rng.choice(spaces + ("",))
                       + rng.choice(GuessGrid.COMMANDS) + rng.choice(spaces + ("",)) + closing + rng.choice(("", " now", "?")))
            else:
                ask = "".join(rng.choice(pieces) + rng.choice(("", " ", " ")) for _ in range(rng.randint(1, 45)))
            for command in ask_commands.guess(ask):
                offers += 1
                if not (command and command == command.strip() and command in ask):
                    bad.append((ask, command))
        self.assertGreater(offers, 100)
        self.assertEqual(bad[:5], [], f"{len(bad)} of {offers} offers are not a stripped piece of their ask")


if __name__ == "__main__":
    unittest.main()
