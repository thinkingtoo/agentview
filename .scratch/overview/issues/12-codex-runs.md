# How do Codex runs appear on the overview?

Type: grilling
Status: open
Blocked by: none

## Question

Using "Which movement and stuck signals can Codex sessions give?": Codex on this machine is almost all `codex exec` runs (1,563 of 1,808 rollouts) and review subagents (237), with 7 interactive sessions, the last in August. Today's provider already lists exec runs with the kind "exec". Does an exec run get its own tile, sit inside the tile of the Claude session that started it, or stay off the page? For interactive Codex sessions: is the inferred Needs you (an unanswered `require_escalated` call) good enough, or does agentview set up Codex's `permissionRequest` and `stop` hooks, which the person has to approve in `/hooks`, for a clean Needs you and a session line?
