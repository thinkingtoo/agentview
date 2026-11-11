# 27: A sign anywhere after `ssh` offers prose

**What to build:** no button when the sign that makes `ssh` a command stands in prose after it. `ssh` is in `PROGRAMS`, so any word that matches `ARGUMENT_SIGN` anywhere after it counts, including one at the end of a sentence about ssh.

**Claimed by:** Milos 2026-11-11

**Blocked by:** None

**Status:** done

## The shape (invented placeholders)

- `Then $ ssh in and run ls -la` -> `["ssh in and run ls -la"]` on origin/dev.
- `Then $ ssh 42 git status` -> `["ssh 42 git status"]` on origin/dev (a bare number is a sign).
- `Then $ ssh -maple git status` -> offered (a word that starts with `-` is a flag).

Found by the spec review and the bug hunt of PR 13 (ticket 24), 2026-11-11. Not counted on the real asks yet.

## Where the rule lives

`ask_commands.py`, `reads_as_command`: `if first in KNOWN and any(ARGUMENT_SIGN.search(w) for w in rest)`. The same holds for every program of `PROGRAMS`; ticket 24's `HOST` shape could judge the word after `ssh`.

## Measured, 2026-11-11 (Milos)

On every distinct `team-line --n 1` ask in the transcripts (3255 asks, 163 buttons on origin/dev 6fb661c), with `/home/tiroir/Projects/agentview-wt/measure-19-dump.py` and a classifier that unwraps `!`, `VAR=` and the wrappers and sorts each button by the rule that fired. Each one read by hand; the dumps were deleted afterwards.

| Rule that fired | Buttons | Commands | Prose |
|---|---|---|---|
| `ssh <host> <command>` (ticket 24) | 7 | 7 | 0 |
| `ssh`, sign in the word right after it (`-t`, `root@...`) | 6 | 6 | 0 |
| `ssh`, sign further on (a host, then a quoted command) | 8 | 8 | 0 |
| Another program of `PROGRAMS`, sign not right after it | 1 | 1 | 0 |

Commands, invented placeholders: `ssh maple-box 'bash /root/stage-maple/rollback.sh --yes'`, `tmux kill-session -t maple`. Prose: none in the real asks; the shapes above (`ssh in and run ls -la`, `ssh 42 git status`) are invented ones, and so are `ssh maple-box and run ls -la` and `ssh maple then cd ~/notes`. The other programs stay as they are.

## Done

`reads_as_ssh` in `ask_commands.py`: the word right after `ssh` decides. With a sign of its own other than a bare number it counts as before (`ssh -maple git status`, `ssh root@maple`, `ssh 10.0.0.5 uptime`). Otherwise that word is the host, and what follows has to say so: a quote with a sign in it (`ssh maple 'df -h'`, not `ssh to 'maple-box'`), which after a word of no host shape has to end the command, or, after a word of ticket 24's `HOST` shape, a flag or a command of its own. Tests in `SshHost`: the seven prose asks and the nine quoted ones of the bug hunt offer nothing; the eight shapes sessions write still offer their command.

**The trade, against the dispatch's literal rule** ("only a host-like word followed by a command counts"): that rule would lose 14 of the 21 real `ssh` buttons, the 6 with a flag right after `ssh` (`ssh -t maple-box ...`) and the 8 with a host and then a quoted command (`ssh maple-box 'bash ...'`). So a sign right after `ssh` still counts, and so does a quote after the host; neither costs a real button or offers real prose. Bug hunt 1 (Opus) found the first version took any quote after the host, so `$ ssh to 'maple-box'` was offered where origin/dev offered nothing (class a); fixed test-first, and `ssh once "it works"`, offered on origin/dev, no longer is. A flag after a plain word no longer counts (`ssh in -t`, `ssh in --help`, found by the spec review).

After: 3263 asks (eight new since the first pass), 166 buttons on origin/dev bb82f03 and 166 on the branch, no ask whose buttons differ. Zero prose offered, no command button lost. `test_ask` + `test_guessed_commands` on t-compute: 150 OK, import resolved to the clone. The hunt's class c findings are ticket 29.
