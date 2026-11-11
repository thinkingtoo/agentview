# 29: What the ssh rule of ticket 27 still gets wrong, both ways

**What to build:** decide, for each shape below, whether it is worth a rule. None occurs in the real `--n 1` asks (3263 asks, 2026-11-11).

**Found in:** Codex reviews 1 to 4 of PR #19 (Opus fallback, run by Milos, 2026-11-11), class c.

**Blocked by:** None.

**Claimed by:** Nia 2026-11-11

**Status:** done

## Commands that lost their button (the safe side, accepted by ticket 27)

A flag or a command counts only after a word of `HOST` shape, so these were offered on origin/dev and are not now (invented placeholders):

- `$ ssh maple -p 2222`, and `$ ssh maple -t 'top'` (while `$ ssh maple 'df -h'` is offered).
- `$ ssh maple ls -la`, `$ ssh MAPLE ls -la`, `$ ssh maple_box ls -la` (`HOST` has no `_`).
- `$ ssh -- maple 'df -h'`.
- A quote after the host is judged alone: one that holds no command drops the line, whatever follows (`$ ssh maple-box "x" -h`, `$ ssh maple '' -x`, `$ ssh maple-box '' ls -la`, `$ ssh 'maple' 'df -h'`); after a plain word a second quote does too (`$ ssh maple 'df -h' 'ls -la'`).
- Claude's `!` after a host: `$ ssh maple-box ! ls -la`.
- A shell mark after the quote counts only after a `HOST` word, so after a plain host the line is dropped (review 4, 2160 corpus cases): `$ ssh maple 'df -h' | grep sda`, `$ ssh maple "df -h"; echo done`. Allowing `;&|>` there too would let through only prose origin/dev already offers.
- A one-word program no list knows, in quotes (review 4, 175 cases): `$ ssh maple-box "uptime"`. origin/dev offered it because `"` is a sign, and by the same test `ssh maple-box "now"`.

## Prose still offered, as on origin/dev

- A sign right after `ssh` takes the whole sentence behind it: `Then $ ssh root@maple and look at the logs`, `$ ssh 10.0.0.5 and check`, `$ ssh ~ and ls`.
- A flag after a hyphenated word or a word with a digit: `$ ssh follow-up -ish`, `$ ssh v2 -based`.
- A shell mark followed by prose after the quote: `$ ssh maple-box 'git status' ; then tell me` (only the first character after the quote is checked).
- Prose with a sign inside the quote: `$ ssh maple 'maple at 10.0.0.5'`.

## Prose offered by the branch, not by origin/dev

- A plain word before a quoted command reads as a host, by design (`ssh maple 'git status'` is a real shape): `Then $ ssh again 'docker ps'`, `Run "ssh in 'git status'" now`, `$ ssh to 'git status'`. Review 4's corpus counts 1435 such cases (with wrappers and nesting); none of the 21 real `ssh` asks has a plain-word host, so requiring a `HOST` word before a quote would cost no real button.
- The `.`-as-`source` reading: `Then $ ssh in '. 5'` is offered; `$ ssh maple '.~/x; ls -la'` (no space after the dot) loses origin/dev's button.

## Decision, 2026-11-11

The plain-word-host shapes stay by design. Narrowing to a `HOST` word before the quote would break plain hosts like `maple` (`ssh maple 'df -h'` is a real shape) for zero gain on the real asks: none of them has a plain-word host, and none of the shapes above occurs in them. Every other shape in this ticket is wontfix (so `done` here means decided): each costs either a real-looking host or prose that origin/dev already offered, and none occurs in the 3284 real `--n 1` asks of 2026-11-11.

One line was cheap and is fixed (Nia): **a shell mark after the quote now counts after a plain host too** (the C1 shape, "after a plain host the line is dropped"). `ends` in `reads_as_ssh` no longer asks for a `HOST` word. `$ ssh maple 'df -h' | grep sda`, `$ ssh maple "df -h"; echo done`, `$ ssh maple 'git status' && echo done` and `$ ssh maple 'df -h' > disk.txt` are offered again, as before ticket 27. What this lets back in is only what dev offered before ticket 27 (17386f1): `$ ssh to 'git status'; then tell me`, `$ ssh in 'git status' | less`, `$ ssh again 'docker ps' && wait` are offered by 17386f1 and by this branch, not by 0f8f7e9. The sentence after a quote with no mark (`$ ssh maple 'git status' and then tell me`) still offers nothing.

### Evidence

- **Red** (`test_a_shell_mark_after_the_quote_counts_after_a_plain_host_too`, t-compute, 147 tests, 4 failures, one per subtest), e.g. `AssertionError: Lists differ: [] != ['ssh maple "df -h"; echo done']`.
- **Green:** `test_guessed_commands` + `test_ask` on t-compute, 155 OK, `ask_commands.py` resolved to the clone.
- **Real asks** (`measure-19-dump.py`, every distinct `team-line --n 1` ask in `~/.claude/projects`, dump in `/dev/shm`, deleted after): 3284 asks; origin/dev 0f8f7e9 169 asks with a button (169 buttons), this branch 169 (169), 0 asks differ, so no new prose. 21 buttons go through `ssh`, the same 21 as Milos's pass.
