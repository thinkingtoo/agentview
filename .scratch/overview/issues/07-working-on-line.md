# What does the "working on" line of a session say?

Type: grilling
Status: resolved
Blocked by: none

## Question

Each session shows what it is working on. Today the roster carries `title`, `prompt`, `did`, `doing`, `ask` and `said`, and 8 of 24 sessions had no title on 2026-10-17. Which source wins, what shows when it is empty, and how does a session's line relate to its project's context line?

## Answer

Resolved 2026-10-18 by grilling, in two rounds. Live roster that day: 21 sessions, `did` on 15, `title` on 13, neither on 4.

The working-on line says what the session's job is, and nothing about this minute.

- **Source order**: the person's own line, then `did` (the session line from its last stop), then Claude Code's `title`. This is today's order: `did` is rewritten at every stop, while a title is written once and goes stale.
- **Busy sessions keep their last `did`.** The words stay until the session writes new ones, so the row does not flip at every prompt. Only `ask` and `n` stay turn-scoped as today, so Needs you stays accurate.
- **Empty**: the last prompt, clipped and greyed so it reads as a stand-in. With no prompt either, the branch or folder, greyed.
- **No repeats**: a line equal to its project's name or context line is skipped for the next source. With nothing left, the session shows no line, because the project heading already says it.
- **One line**, clipped with an ellipsis, full text on hover (`did` ran up to 142 characters).

The "now" words leave the line. `doing` goes into the movement sign ("running tests, 4 min"). `ask` goes into the Needs you context. `said` shows only on a finished session the person has not seen yet, as the handover. Today's second line under a session goes away.

Codex sessions have no hook, so they have no `did` and start at `title`. That belongs to "Codex parity".
