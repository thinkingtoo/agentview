# Boss brief: Paste

Written 2026-10-21 by Isolde with `/hand-to-boss`. You are the boss for
track `paste`. Read this file, then every source it names, before you dispatch
anything. This brief points; the sources hold the content.

## Sources

| What | Path |
|---|---|
| Plan (read first, in full) | `/home/tiroir/Projects/agentview/docs/specs/2026-10-21-paste.md` |
| Tickets, one file each, in dependency order | `/home/tiroir/Projects/agentview/.scratch/paste/issues/` |
| Handoffs | none |
| Research | none |
| Repo conventions (tracker, labels, domain) | `/home/tiroir/Projects/agentview/docs/agents/` and `/home/tiroir/Projects/agentview/GLOSSARY.md` |
| Code | `/home/tiroir/Projects/agentview` (branch `dev`) |
| Owner's global rules (ticket 04 edits its clipboard section) | `/home/tiroir/.claude/CLAUDE.md` |

## Frontier

The frontier on 2026-10-21 21:40 CEST, from `frontier.py /home/tiroir/Projects/agentview/.scratch/paste/issues`:

```
Ready now: 01
  01  One Paste end to end
Waiting on other tickets:
  02  after 01
  03  after 01
  04  after 01, 03
Done: none
```

Re-run `python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.10.2/skills/hand-to-boss/frontier.py /home/tiroir/Projects/agentview/.scratch/paste/issues`
after every ticket that closes; the output above is a snapshot.

External blockers — who holds each one, and what unblocks it:

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| none | — | — | — |

Ticket 04 ends with one check by hand (a fresh session hands over a message as a
Paste). The team can run that check itself in a throwaway session; it needs no
one's hand.

An external blocker is a person, not a task: nobody on the team works around it.
A blocker the owner holds goes into your tracker's Open blockers and up the
escalation ladder.

## Objective

Write it with `boss-goal` from this brief. **Done when**: every ticket not waiting
on an external blocker has Status `done` and its boxes ticked; the ones still
waiting are listed with who holds them.

## Staffing

- You run on `opus`.
- Every worker runs on `sonnet`: `boss-lifecycle.sh spawn <dir> --model sonnet`.
  `BOSS_WORKER_MODEL` is set to the same in your environment, so a spawn without
  `--model` lands there too.
- One git worktree per worker, on its own branch, under `/home/tiroir/Projects/agentview-wt/`.
  Two workers never share a branch or a worktree.
- At most 2 workers at once: after 01 only 02 and 03 can run in parallel.

## Claiming a ticket

The boss claims a ticket at dispatch, before the dispatch message goes out:

```bash
python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.10.2/skills/hand-to-boss/frontier.py claim /home/tiroir/Projects/agentview/.scratch/paste/issues <NN> <worker>
git -C /home/tiroir/Projects/agentview commit -m "Claim <NN> for <worker>" -- <ticket file>
```

`claim` writes `**Claimed by:** <worker> <date time>` above the Status line and
sets `**Status:** in-progress`, under a lock, in the shared ticket file. It
refuses (exit 3, naming the claimant) a ticket that is already claimed, done or
still blocked; then nothing is dispatched. The commit names that one file by
path, so it carries nothing else in a tree other sessions share, and no edit is
left uncommitted. Both are coordination, not implementation: if the guard
remarks on them, say so in one line and carry on.

The worker never edits the claim. It reads the ticket at its path under
**Sources**, the shared file, never the copy inside its own worktree, and when
it finishes it ticks the boxes and sets Status there, committing that file by
path in the same way. To release a claim, the boss removes the line, sets
Status back to `ready-for-agent`, commits the file by path and notes it in the
tracker.

## Done means verified

A worker ticks an acceptance box only when it has the evidence: the command it ran
and what came back, the URL it read, the test that passed. It puts that evidence
in its report. Status becomes `done` only when every box is ticked. A box that
cannot be verified yet stays unticked with one line saying why.

## Guardrails

Quoted from the rules that bind this work. The source is named on each line; the
source wins where this summary is short.

- **The main checkout is live.** AgentView runs from it: `agentview.service` has
  `WorkingDirectory=%h/Projects/agentview` and runs `server.py` from there, and every
  session on the machine runs `hooks/team-line` from that checkout
  (`systemctl --user cat agentview.service`; the hook text each session receives).
  Never build in the main checkout; merge into `dev` only finished, tested tickets, and
  restart the service only after a merge, checking that the page still loads.
- Shared tree: "Another session may share this checkout. Before a commit, `git status`
  and stage only your own paths by name; for more than a small edit, use a worktree."
  (`/home/tiroir/.claude/CLAUDE.md`, Three tool habits)
- Parallel work: "Parallel workers MUST use separate branches — never two workers on the
  same branch. Use worktrees." (`/home/tiroir/.claude/CLAUDE.md`, Git Safety)
- Tests on the laptop: "Locally, run only the test files your change touches. Never the
  full suite, never `pytest -n auto`/xdist, unless `uptime` shows load under 8." and "A
  repo with no t-compute CI … run the suite on t-compute over ssh, not here."
  AgentView has no CI (`.github/workflows` does not exist). Kill your own test runs,
  including headless Chrome from `ui_smoke`. (`/home/tiroir/.claude/CLAUDE.md`, Full test suites)
- Git: `dev` deploys nothing (`branch_deploys.py /home/tiroir/Projects/agentview dev`
  exits 1), so push after each merge; "Where nothing deploys, push."
  (`/home/tiroir/.claude/CLAUDE.md`, Production)
- Commits: "run `git commit --amend` to remove the Claude Code footer"
  (`/home/tiroir/.claude/CLAUDE.md`, Git Commits)
- Secrets (ticket 03): "No test ever touches the real keyring" (spec, Testing Decisions).
  Never write a real token into a test fixture.
- Owner's CLAUDE.md (ticket 04): edit surgically, only the "Clipboard (Proactive Copy)"
  section; the file is committed nightly by `config-commit.timer`. Keep it in English
  ("This file must always be in English", `/home/tiroir/.claude/CLAUDE.md`, Meta).
- What needs the owner's own hand: a password, a browser sign-in, Cloudflare, a GitHub
  token, a purchase (`/home/tiroir/.claude/CLAUDE.md`). Nothing in these tickets needs one.

## Time windows

None stated on 2026-10-21.

## Language

Report to the owner in Dutch. Files, commits, tickets and PRs in English.

## Suggested skills

- `/claude-boss:boss` — you are running it.
- `mattpocock-skills:tdd` — every worker, every ticket: the tickets are built test-first.
- `mattpocock-skills:code-review` — before each merge into `dev`, then `/codex-review` for a bug hunt on the diff.
- `mattpocock-skills:domain-modeling` — ticket 01, for the GLOSSARY.md entry **Paste**.
- `mattpocock-skills:diagnosing-bugs` — when a test fails for a reason nobody understands.
