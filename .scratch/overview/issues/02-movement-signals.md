# What signals show that a session is moving?

Type: research
Status: resolved
Blocked by: none

## Question

What evidence on this machine shows that a session is still making progress, including when the model itself is idle? Candidates: transcript writes and their timestamps, outstanding tool calls, background shell tasks, Monitor and run_in_background waits, child processes (test runners, `gh run watch`), subagents, Claude Code's `status` and `waitingFor`. For each: where it is read, how fresh it is, what it costs to read every few seconds, and whether Codex sessions give the same thing.

## Answer

Resolved 2026-10-17. Full findings: `docs/research/movement-signals.md` on the local branch `research/movement-signals` (commit `15309ae`, never pushed). Measured on 24 live Claude sessions over 60 polls at 3 s; no Codex session was live, so Codex rests on 40 recent rollout files.

- The peer `status` is written only when it changes and has no heartbeat, so a stale `busy` looks like a long one. Codex has busy/idle only.
- Transcript writes: gaps are 0.5 s at the median and 421 s at p99, and the long gaps are exactly the waits. 25 ms per poll.
- Open background tasks (started ids minus task-notification and `TaskStop` ids) matched `shell` exactly: 5 of 5 `shell` sessions had one, 0 of 9 idle ones did.
- Shells under the session pid, with their CPU, cost 191 ms per poll (a full `/proc` scan is 1,021 ms). Subagent transcript writes cost 42 ms. A task's output file can be found in 1 ms when its path is taken from the tool result.
- An outstanding tool's age alone cannot tell a test run from a hung command.

Best rule: a session is **moving** if its transcript or a subagent wrote recently, a shell under it is using CPU, or it has an open background task with a live shell behind it. Otherwise it is **not moving**. The main process's own CPU only backs up a stale `busy`.

Today's `stuck` flag fired on 2 sessions: one was a false alarm (waiting on two live background shells, resumed minutes later), the other had nothing open for 477 minutes. Still open: why that second session's `busy` never cleared, and Codex child processes, which need a live Codex session to measure.
