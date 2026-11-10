# 27: A sign anywhere after `ssh` offers prose

**What to build:** no button when the sign that makes `ssh` a command stands in prose after it. `ssh` is in `PROGRAMS`, so any word that matches `ARGUMENT_SIGN` anywhere after it counts, including one at the end of a sentence about ssh.

**Blocked by:** None

**Status:** needs-triage

## The shape (invented placeholders)

- `Then $ ssh in and run ls -la` -> `["ssh in and run ls -la"]` on origin/dev.
- `Then $ ssh 42 git status` -> `["ssh 42 git status"]` on origin/dev (a bare number is a sign).
- `Then $ ssh -maple git status` -> offered (a word that starts with `-` is a flag).

Found by the spec review and the bug hunt of PR 13 (ticket 24), 2026-11-11. Not counted on the real asks yet.

## Where the rule lives

`ask_commands.py`, `reads_as_command`: `if first in KNOWN and any(ARGUMENT_SIGN.search(w) for w in rest)`. The same holds for every program of `PROGRAMS`; ticket 24's `HOST` shape could judge the word after `ssh`.
