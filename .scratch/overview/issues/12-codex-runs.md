# How do Codex runs appear on the overview?

Type: grilling
Status: resolved
Blocked by: none

## Question

Using "Which movement and stuck signals can Codex sessions give?": Codex on this machine is almost all `codex exec` runs (1,563 of 1,808 rollouts) and review subagents (237), with 7 interactive sessions, the last in August. Today's provider already lists exec runs with the kind "exec". Does an exec run get its own tile, sit inside the tile of the Claude session that started it, or stay off the page? For interactive Codex sessions: is the inferred Needs you (an unanswered `require_escalated` call) good enough, or does agentview set up Codex's `permissionRequest` and `stop` hooks, which the person has to approve in `/hooks`, for a clean Needs you and a session line?

## Answer

Resolved 2026-10-18 by grilling. Exec rollouts here: 1,563, a median of 1.0 minute, 3.8 minutes at p90, at most 6 running at once, 295 in the 7 days to 2026-10-18 (busiest day 143). Review subagents (237) last 2.3 minutes at the median.

- **A running exec run shows inside the tile of the Claude session that started it**, as movement: "waiting on: codex review, 2 min". It is found by walking up from the `codex` process to a Claude session's pid. It has no tile of its own, the same rule as waiting on a subagent or a background job.
- **An exec run with no starter found** (run by hand, or its Claude session gone) gets an ordinary tile marked `exec`, placed in a project by its launch folder like any session.
- **No Codex hooks for now.** Interactive Codex sessions get what the rollout gives: movement, busy and idle, Limit, Error, and Needs you inferred from a `require_escalated` call with no output yet, which Hung rules out first. Revisit if interactive Codex use returns; there have been 7 interactive sessions in total, the last in August.
- **A Codex usage limit is one banner across the page**, like a full disk: "Codex usage limit reached, resets at 14:20", until the reset time. It is not a per-session kind, because the run that hit it has already ended. The reset time comes from the error's message text, the only place it appears.
