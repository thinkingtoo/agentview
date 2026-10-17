# What signals exist to group sessions into projects?

Type: research
Status: resolved
Blocked by: none

## Question

For each running session, what facts are already on this machine that say which project it belongs to? Candidates: the working directory, the git remote and repository root, the parent repository of a worktree, a boss's team list, cc-agent-names records, the claude-boss plugin's state, the session's own title. For each signal: where it is read from, how often it is present across today's sessions (as counts), and where two signals disagree (as counts and kinds, never names).

## Answer

Resolved 2026-10-17. Full findings: `docs/research/project-signals.md` on the local branch `research/project-signals` (commit `34c6555`, never pushed).

Snapshot of 24 live sessions (4 bosses, 13 workers, 7 neither; no Codex running). Today's folder labels give 14 groups for 7 repositories: worktrees split one repository across several labels (11 cases), one label covers 4 boss tracks, and 10 of 13 workers land under a different label from their boss. `team` means "who the boss messaged", so 2 sessions sit in two teams. The boss-side signals agree with each other: the tmux `boss-<track>` name matches the boss marker 9 of 10 times, and every worker is named in its boss's tracker (13 of 13).

Recommended precedence, first match wins:

1. An explicit assignment by the person (covers nothing today; an override).
2. Boss track: the boss's marker `~/.claude/pm/.boss-sessions/<sid>`; for a worker its tmux `boss-<track>` name, then `reportsTo`, then a single tracker naming it. Covers 18 of 24 and follows work across repositories.
3. Repository identity: a worktree's parent repository keyed by remote, plus the client subfolder. Covers the 6 sessions with no boss signal.
4. Today's folder rule, for the 5 sessions outside any repository.
5. Paths the session touched, as a guess only.

Codex sessions can reach only steps 3 to 5 (0 of 1,808 Codex threads carry a `project_id`).
