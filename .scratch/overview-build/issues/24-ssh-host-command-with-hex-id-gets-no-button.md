# 24: A command marked with `$` that runs over ssh with a hex id gets no button

**What to build:** a copy button for `$ ssh <host> docker stop <id>` when `<id>` is a container or commit id such as `8617f9d7515d`. The session marked the command with `$`, so it is not a guess about a bare command; the guesser refuses it on the evidence rule alone.

**Blocked by:** None

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
