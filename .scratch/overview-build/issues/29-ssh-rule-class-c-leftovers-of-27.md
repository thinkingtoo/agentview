# 29: What the ssh rule of ticket 27 still gets wrong, both ways

**What to build:** decide, for each shape below, whether it is worth a rule. None occurs in the real `--n 1` asks (3263 asks, 2026-11-11).

**Found in:** Codex reviews 1 and 2 of PR #19 (Opus fallback, run by Milos, 2026-11-11), class c.

**Blocked by:** None.

**Status:** needs-triage

## Commands that lost their button (the safe side, accepted by ticket 27)

A flag or a command counts only after a word of `HOST` shape, so these were offered on origin/dev and are not now (invented placeholders):

- `$ ssh maple -p 2222`, and `$ ssh maple -t 'top'` (while `$ ssh maple 'df -h'` is offered).
- `$ ssh maple ls -la`, `$ ssh MAPLE ls -la`, `$ ssh maple_box ls -la` (`HOST` has no `_`).
- `$ ssh -- maple 'df -h'`.
- A quote after the host is judged alone: one that holds no command drops the line, whatever follows (`$ ssh maple-box "x" -h`, `$ ssh maple '' -x`, `$ ssh maple-box '' ls -la`, `$ ssh 'maple' 'df -h'`); after a plain word a second quote does too (`$ ssh maple 'df -h' 'ls -la'`).
- Claude's `!` after a host: `$ ssh maple-box ! ls -la`.

## Prose still offered, as on origin/dev

- A sign right after `ssh` takes the whole sentence behind it: `Then $ ssh root@maple and look at the logs`, `$ ssh 10.0.0.5 and check`, `$ ssh ~ and ls`.
- A flag after a hyphenated word or a word with a digit: `$ ssh follow-up -ish`, `$ ssh v2 -based`.
