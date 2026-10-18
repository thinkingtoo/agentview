# Which movement and stuck signals can Codex sessions give?

Type: research
Status: resolved
Blocked by: none

## Question

Using "What signals show that a session is moving?" and "Which kinds of stuck does the overview name, and how is each detected?": for a Codex session on this machine, which of these can agentview read, and from where: transcript or rollout writes per minute (for the project strip), a shell under it using CPU, background work, an open question or approval prompt (Needs you), a rate limit or API error as the last record (Limit, Error), and the busy/idle state that Hung needs? Codex has no session-line hook, so it never has `did`, `ask` or `n`. Facts only: file paths, record types and field names from the Codex version installed here, never conversation text.

## Answer

Resolved 2026-10-18 by research. Findings: `.scratch/overview/research/codex-parity.md` on the local branch `research/codex-parity` (commit `a71b950`, never pushed). All 1,808 rollouts under `~/.codex/sessions/` were read (2026-04 to 2026-10-17): 1,563 `codex exec` runs, 237 review subagents, 7 interactive `cli` sessions (the last in August), 1 `vscode`. 1,622 of 1,643 turn contexts run with `approval_policy: "never"`.

- **Available from the rollout**: per-minute writes (every record has a `timestamp`), busy and idle (`task_started` against `task_complete` or `turn_aborted`), Limit (`task_complete` with `error.codex_error_info == "usage_limit_exceeded"`, 294 records on 17 days; the reset time only in the message text) and Error (the other `codex_error_info` values; retried errors leave no record).
- **Partial**: background work, read from text in the tool output ("Process running with session ID"), not from a field. A shell's CPU through `/proc` is possible but was not measured live; no Codex process ran during the research.
- **Needs you is never written to the rollout.** It can only be inferred: an `exec_command` with `sandbox_permissions: "require_escalated"` and no output yet (39 such calls; 8 waited over 10 minutes). Hung has to rule that out first, or a pending approval reads as Hung.
- **Correction**: the question said Codex has no session-line hook. Codex 0.147.0 ships lifecycle hooks (`stop` with `last_assistant_message`, `permissionRequest` with `tool_name` and `tool_input`), set in `~/.codex/hooks.json` or `config.toml` and approved in `/hooks`. None is configured here. Whether to use them moved to "How do Codex runs appear on the overview?".
