# What signals show that a session is moving?

Type: research
Status: open
Blocked by: none

## Question

What evidence on this machine shows that a session is still making progress, including when the model itself is idle? Candidates: transcript writes and their timestamps, outstanding tool calls, background shell tasks, Monitor and run_in_background waits, child processes (test runners, `gh run watch`), subagents, Claude Code's `status` and `waitingFor`. For each: where it is read, how fresh it is, what it costs to read every few seconds, and whether Codex sessions give the same thing.
