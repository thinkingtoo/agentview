# agentview: what comes next

<!-- Format: NEXT_MD_FORMAT.md of tiroir-work. Read by /next. -->

## Poll round
id: poll-round
goal: One poll is one module (poll.round) that decides once what is forgotten; spec docs/specs/2026-10-25-poll-round.md
done_when: Tickets in .scratch/poll-round/issues are done

- [ ] review-candidates: The other seven candidates of the 2026-10-25 architecture review
  next: Pick the next from the review (what rings is derived in three places, fleet.py split, the dead suggest_project path, request admission, Paste card ownership, seen/finished as one keyed store, provider identity) with Thierry; the report is a scratchpad file and was not kept
  party: agent
  priority: Later
  summary: Candidate 7 (seen and finished as one keyed store) is now cheap: since ticket 02 both stores have the same forget(drop, path), and the round already reads the keys of both to decide what goes
  last_update: 2026-10-25
- [x] poll-module: Ticket 01, poll.round, the handler only serialises (merged 7ea4d81)
  party: agent
- [x] one-forget-decision: Ticket 02, the round decides once what is forgotten (merged 0346f81)
  party: agent

## Overview
id: overview
goal: The overview says, for every running session, whether it works, waits or needs you, and what to paste
done_when: Tickets in .scratch/overview-build/issues are done or closed, and the open items below are settled

- [ ] ci-wait-live: See "waiting on CI" on a real run (ticket 22's last box)
  next: When a session at rest has pushed and its branch has an Actions run going, check its tile says "waiting on CI" with an ETA, then tick the box in .scratch/overview-build/issues/22-waiting-on-ci.md
  party: agent
  priority: Next
  last_update: 2026-10-21
- [ ] ci-wait-workers: Boss workers waiting on CI, read from the boss's per-worker file
  next: When claude-boss writes ~/.claude/pm/.workers/<session-id>.json (its ticket ci-state/02), read worktree and branch from it in fleet.ci_of
  party: agent
  priority: Later
  summary: Workers started in a folder that holds worktrees carry no branch, so ticket 22 cannot match them today
  last_update: 2026-10-21
- [ ] clipboard-rule: Drop the clipboard rule once the copy buttons have proved themselves
  next: Count, on a week of real asks, how often a command got a copy button; if they cover what sessions ask, remove the "Clipboard (Proactive Copy)" section of ~/.claude/CLAUDE.md
  party: agent
  priority: Later
  summary: Owner, 2026-10-21; the rule makes sessions write "the command is in your clipboard" instead of the command (ticket 18)
  last_update: 2026-10-21
- [ ] bare-commands: Decide on ticket 19, a copy button for a command written bare
  next: Measure how many asks still name a command bare since the hook asked for quotes or "$ " (2026-10-20), then decide with Thierry whether ticket 19 is built
  party: agent
  priority: Later
  summary: Three hunts in ticket 18 found prose the bare rule took for a command
  last_update: 2026-10-21
- [x] copy-guesses: Copy buttons for the shapes sessions really write (ticket 18)
  party: agent
- [x] waiting-state: Waiting is not moving, and one word for the work (tickets 20, 21)
  party: agent
- [x] ci-wait: Waiting on CI with an ETA (ticket 22)
  party: agent
