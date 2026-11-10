# 26: What the ssh host rule of ticket 24 still lets through

**What to build:** decide, for each shape below, whether a button is worth losing. Found by review round 2 of PR 13 (Opus, 2026-11-11), class c: none is new in kind, each needs a known tool and its subcommand right after the host.

**Blocked by:** None

**Status:** wontfix

Noor, boss: none of these shapes occurs in the real asks; reopen if one appears

## The shapes (invented placeholders)

- Prose after a subcommand, through ssh: `Then $ ssh maple-box git push and then tell me` -> offered. Same on origin/dev without ssh (`$ git push and then tell me`): the subcommand rule in `reads_as_command` checks only the first word after the tool.
- Claude's `!` behind a wrapper: `Run "ssh maple-box sudo ! git status" now` -> offered; dev offers `$ sudo ! git status` too. The `!` guard looks at the first word only.
- `HOST` takes a word of prose with a digit (`ssh v2 git push`, `ssh 2fa git push`) and non-ASCII letters or digits (`ssh café-crème git push`), since `\d` and `\w` are Unicode there. `re.ASCII` would close the second; the README names only the hyphenated word as a known limit.

## Measured, 2026-11-11

By Milos, in the measuring pass of ticket 27: every distinct `team-line --n 1` ask in the transcripts (3255 asks, 163 buttons on origin/dev 6fb661c), dumped with `python3 /home/tiroir/Projects/agentview-wt/measure-19-dump.py <worktree> <scratchpad>/asks.jsonl`, each button sorted by a classifier that unwraps `!`, `VAR=` and the wrappers. Dumps deleted afterwards.

| Shape | Buttons that match it | Prose among them |
|---|---|---|
| Plain words after a subcommand, bare or through `ssh <host>` | 1 | 0 (a container id after `docker stop`, a command) |
| Claude's `!` behind a wrapper or a host | 0 | 0 |
| `HOST` word with no hyphen, dot or @ (a digit only) or non-ASCII | 0 | 0 |
