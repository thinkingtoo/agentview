# 24: A command marked with `$` that runs over ssh with a hex id gets no button

**What to build:** a copy button for `$ ssh <host> docker stop <id>` when `<id>` is a container or commit id such as `8617f9d7515d`. The session marked the command with `$`, so it is not a guess about a bare command; the guesser refuses it on the evidence rule alone.

**Blocked by:** None

**Claimed by:** Rosa 2026-11-11

**Status:** needs-triage

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

Chosen: the second way, `remote_command` in `ask_commands.py`, called from `reads_as_command` (so it holds in quotes too, as `sudo` does). Only the plain shape: `ssh`, one host word that is not a flag or `!`, then a command judged by itself that is neither Claude's `!` nor a slash command. Flags before the host already carry a sign.

Why not the hex word: it is wider and offers prose. With it, `$ ssh maple-box and check abc1`, `$ echo 2fa` and `$ cat 8617f9d7515d` all get a button; with `remote_command` none does (`SshHost` tests).

Measured with `measure-19-dump.py` on the distinct `--n 1` asks of every transcript (3252), dump kept in the session scratchpad and deleted after:

| | asks with a button |
|---|---|
| origin/dev | 160 |
| hex word after `$` | 161 (1 changed) |
| `remote_command` (this branch) | 161 (1 changed) |

The one ask that changed is the shape above, in both. Command:

    python3 /home/tiroir/Projects/agentview-wt/measure-19-dump.py <worktree> <scratchpad>/after.jsonl

Tests: `SshHost` in `tests/test_guessed_commands.py` (3 tests, red before the change); `test_guessed_commands` and `test_ask` run locally, results below.
