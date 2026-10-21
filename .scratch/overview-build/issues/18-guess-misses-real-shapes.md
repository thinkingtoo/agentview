# 18: The guesser misses the shapes sessions really write

**What to build:** ticket 14's guesser offers a copy button for a command in quotes or after `$ `. On the real asks of the last days it offers one for 7 of 283 distinct `--n 1` asks, and misses at least 11 more that hold a command the session marked. Teach it the shapes sessions actually write, below, each test-first on an invented line of that shape. A guess still never runs anything and never answers the session.

**Blocked by:** 14

**Claimed by:** Tarek 2026-10-21

**Status:** done

## Findings (Tarek, 2026-10-21, counts only: the repo is public, no real ask text here)

Corpus: every `team-line` Bash call in `~/.claude/projects/*/*.jsonl` changed in the last 4 days: 3,897 calls, 534 with `--n 1` and an ask, 283 distinct asks. Run through `ask_commands.guess` on `996ae0f`.

- **Timeline.** The hook sentence that tells a session where to put a command reached the shared checkout on 2026-10-20 (`d77de80`, 09:30); `agentview.service` has run the code since 2026-10-20 16:06. Before that no button could appear, whatever the session wrote.
- **Guessed: 7 distinct asks.** After the restart, 5 of them were on a tile (from 20 s to 12 min before the next line replaced them). One of the 7 is a false positive: `$ git commit --allow-empty + git push in <folder>`, prose after a `$` that passes because of a flag.
- **Missed, the session did mark the command (invented examples of each shape):**
  1. The `!` of Claude Code's shell prefix, which the owner's global instructions tell sessions to suggest: `$ ! bash ./x.sh`, `"! printf ..."`, and `... : ! python3 -I /path/x.py` at the end of the ask. 5 distinct asks. `reads_as_prompted` and `reads_as_command` see `!` as the first word and refuse.
  2. A dollar escaped by the session: `\$ bash /path/x.sh`. Inside the hook's single quotes the backslash stays, and `DOLLAR_COMMAND` needs a space, colon or bracket before the `$`. 3 distinct asks.
  3. A Claude slash command to type in a pane: `$ /some-skill:name`, `"/autocompact 450k"`. A path with one slash is not a program. 3 distinct asks.
- **Missed by design, no marker:** a command written bare (`Run the wizard: bash /path/wizard.sh (...)`, `(ssh-add ~/.ssh/id_ed25519)`), at least 5 distinct asks, and one bare word in quotes (`"claude"`). Ticket 14 chose to offer nothing here; changing that is the owner's call.
- **No text to guess:** several asks say "run the command from your clipboard" and do not repeat it. The owner's clipboard rule makes the session copy it, and the ask then only points at it.
- **Prototype** (a wrapper around `guess`, not in the repo): rules 1 to 3 take the 283 asks from 7 to 18 guessed, with no new false positive among them. In the prototype the `!` was dropped from the copied text; what the button should copy is open below.

## Open

- Decided (Tarek): a command written with `!` is copied with the `!`, as the session wrote it. The session chose the prefix because the command goes into a Claude prompt; one meant for a terminal is written without it (seen in the corpus: "in a normal terminal, not with !").
- Decided by the owner, 2026-10-21: a command with no marker gets a button when the evidence is strong (a known program with a sign after it, at the end of the ask after a colon or alone inside brackets).
- The false positive: a lone `+` before a program's name is the sentence's "and"; nothing is offered.
- Owner, 2026-10-21: the "Clipboard (Proactive Copy)" section of `~/.claude/CLAUDE.md` is what makes sessions write "the command is in your clipboard" instead of the command. Remove it once the buttons have proved themselves on real asks.

## Done on the branch (Tarek, 2026-10-21)

- Rules 1 to 3, the bare rule and the `+` rule, each test-first in `tests/test_guessed_commands.py` (`RealShapes`, 11 tests). Ticket 14's test that pinned "no button for `!` and for `/compact --keep-tools`" is changed to the new rule; "npm login" and "git lfs pull" still get none.
- Real data, the same 289 distinct asks (any `--n`) on the branch: 7 guessed before, 20 after; the one false positive is gone and no new one appears. Still missed: a bare command in the middle of a sentence, or followed by more words after a comma.
- Tests run locally (load 5): `test_guessed_commands` 116 OK, `test_turn_hook` 23 OK, `test_needs_you` 49 OK, `test_needs_you_reader` 40 OK; private TMPDIR left with 0 entries. The full suite runs elsewhere.

## Hunt 18-1 (Opus fallback, Codex unavailable: 429 usage limit, 2026-10-21)

NO-GO on `7d3b13a`, five P1, all reproduced and fixed test-first: a bare command ending in `?`/`!` or followed by a comma clause (the `?` pasted as a glob); one plain word of prose taken as the last argument (`rm -rf ~/maple adesso`); a colon that reports (`Done: rm -rf ...`); a web route in quotes taken for a slash command (`"/login"`, `"/review the PR"`); the inside of `$(...)` offered as a bracket command. P2 `! !` fixed too; P2 a bracket command offered as a choice is accepted and listed in the README. After the fix: 122 guesser tests OK, the hunter's 61 inputs all right, worst time 2.5 ms, real asks still 7 -> 20 with no false positive.

## Hunt 18-2 (Opus fallback, Codex unavailable, 2026-10-21)

NO-GO on `4386b3b`: round 1 all fixed; new P1 on the bare path: a word of prose inside the command (`git pull in ~/maple`, `rm -rf ~/build or ~/dist`), `cd ..` cut to `cd .` by the sentence's full stop, and report words the `Done:` list missed (`Errore:`, `Executed:`, `Don't run:` ...). Fixed by changing the rule, not by growing lists: a colon offers a bare command only after a verb that asks for it to be run (no negation, no "already"); no letters-only word that is not the tool's subcommand among the arguments; the full stop is the sentence's only after a non-dot; a bracket remark that names more to run blocks the offer. P2 fixed: fullwidth `？`/`！`, `¿ ¡ ‼`, a hyphen-only slash name after `$`. Accepted: `$ /status --json` (a route after a prompt), history expansion inside quotes (unchanged from origin/dev). Real asks: 7 -> 19 (the one lost has no run verb before its colon). 130 guesser tests OK.

## Hunt 18-3 (Opus fallback, Codex unavailable, 2026-10-21) and the cut

NO-GO on `81d0893`: rounds 1 and 2 fixed, three new P1 all on the bare path (a run verb as a noun or in a report: `Run failed: npm run build --prod`, `Start date: rm -rf ~/x`; a run verb in an earlier comma clause; `Don’t run:` with U+2019), P2s on prose stuck to punctuation, the bracket path ignoring negation, a dropped `(as root)` remark, placeholders, and 67 ms on 400 characters of colons. The marked shapes (`!`, `\$`, slash commands, the `+` rule) were clean in all three hunts.

Third hunt, so the cap: the bare path is taken out of this ticket (Tarek's call, the owner's "yes if the evidence is strong" did not hold up: three hunts in a row found prose it took for a command) and moved to ticket 19 with every finding. Its negative tests stay as guards. The code at `81d0893` is the starting point there.

After the cut: 128 guesser tests OK, `test_turn_hook` 23, `test_needs_you` 49, `test_needs_you_reader` 40, TMPDIR left empty. All ~440 hunt inputs: 3 differ from origin/dev, all marked and right (`$ ! bash ~/x.sh`, `$ ! rm -rf ~/x`, `$ /status --json`, the last accepted in the README). Real asks: 7 -> 15. Worst time 0.5 ms.
