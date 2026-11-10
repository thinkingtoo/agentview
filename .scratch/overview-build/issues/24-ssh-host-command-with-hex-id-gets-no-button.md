# 24: A command marked with `$` that runs over ssh with a hex id gets no button

**What to build:** a copy button for `$ ssh <host> docker stop <id>` when `<id>` is a container or commit id such as `8617f9d7515d`. The session marked the command with `$`, so it is not a guess about a bare command; the guesser refuses it on the evidence rule alone.

**Blocked by:** None

**Claimed by:** Rosa 2026-11-11

**Status:** done

## The shape (invented placeholders, never a real host)

- `Stop the stuck container: $ ssh maple-box docker stop 8617f9d7515d` -> no button today.
- `Stop the stuck container: $ ssh maple-box docker stop 8617` -> `["ssh maple-box docker stop 8617"]`, because an all-digit word counts as an argument.

Seen once in the real asks of 2026-10-22..11-11 (found while measuring ticket 19).

## Where the rule lives

`ask_commands.py`: `guess` -> `reads_as_prompted` -> `reads_as_command`. `ssh` is in `PROGRAMS`, so it needs a word after it that matches `ARGUMENT_SIGN`. A hyphenated host (`maple-box`) is prose by design, the subcommand words (`docker`, `stop`) carry no sign, and `^\d+$` does not match a hex id that holds letters.

## Open

- After a `$` the prompt is already a mark. A word of hex digits with at least one digit (an id or a short sha) could count as a sign there. Weigh that against prose after a `$` (`$ 5`, "the $ diff"), which `reads_as_prompted` keeps strict on purpose.
- Or judge what follows `ssh <host>` as a command of its own, as `WRAPPERS` does for `sudo`.

## Done on the branch (Rosa, 2026-11-11)

Chosen: the second way, `reads_as_remote_command` in `ask_commands.py`, called from `reads_as_command` (so it holds in quotes too, as `sudo` does). Only the plain shape: `ssh`, one word that looks like a host (`HOST`: letters with a hyphen, a digit, a dot or an `@`, no mark stuck to it), then a command judged by itself that does not start with Claude's `!`. Flags before the host already carry a sign.

Why not the hex word: it is wider and offers prose. With it, `$ ssh maple-box and check abc1`, `$ echo 2fa` and `$ cat 8617f9d7515d` all get a button; with this rule none does (`SshHost` tests).

Measured with `measure-19-dump.py` on the distinct `--n 1` asks of every transcript, dumps kept in the session scratchpad and deleted after:

| | asks with a button (same 3252 asks) |
|---|---|
| origin/dev | 160 |
| hex word after `$` | 161 (1 changed) |
| ssh host rule, first cut (`6310de5`) | 161 (1 changed) |
| ssh host rule with `HOST` (after review) | 161 (1 changed; on the 3255 asks of the second run, dev and the branch differ on that one only) |

The one ask that changed is the shape above, in every row. Command:

    python3 /home/tiroir/Projects/agentview-wt/measure-19-dump.py <worktree> <scratchpad>/after.jsonl

Tests: `SshHost` in `tests/test_guessed_commands.py`, red before each change. `test_ask` + `test_guessed_commands` on t-compute (laptop load 15+) at `6310de5`: 143 tests OK, import resolved to the clone; after the review fix, results in the PR.

## Review (PR 13)

- Matt's code-review: standards (ticket status and missing results, a long README line, `remote_command` named like a string) fixed; spec: nothing wrong, the quote path is wider than `$` but is the way the ticket names.
- Codex review 1 (run by Rosa, Opus; Codex out of tokens), NO-GO, class b: any word took the host's place (`"ssh and git push"`, `$ ssh then git pull`) and a mark stuck to the host was kept (`"ssh maple-box, git status"`). Fixed test-first with `HOST`; the cost is no button for a one-word host (`ssh maple git status`), the safe side. The slash-command check was dead (`/` is already a sign) and is gone.
- Found on origin/dev, not from this branch: ticket 27.
