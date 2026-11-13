# Boss brief: Merge desk

Written 2026-11-13 by Kenji after a grilling with Thierry. You are the boss for track `merge-desk`. It spans two repositories: AgentView (the desk) and sheaf (the buttons it is pressed with). Read this file, then every source it names, before you dispatch anything. This brief points; the sources hold the content.

## Sources

| What | Path |
|---|---|
| Spec (read first, in full) | `/home/tiroir/Projects/agentview/docs/specs/2026-11-13-merge-desk.md` |
| AgentView tickets, in dependency order | `/home/tiroir/Projects/agentview/.scratch/merge-desk/issues/` |
| sheaf tickets, in dependency order | `/home/tiroir/Projects/sheaf/.scratch/action-buttons/issues/` (on sheaf `main` once [PR #273](https://github.com/sweatshop-ai/sheaf/pull/273) is merged; until then on branch `kenji/action-buttons-tickets`) |
| The proven reference for a safe merge (pinned commit, UNKNOWN wait, one at a time) | `/tmp/claude-1000/-home-tiroir-Projects-sheaf/9b25dd13-7719-4864-9de4-8419cde7f15f/scratchpad/merge_server.py` (copy it into the ticket 03 worktree early: it lives in a session scratchpad) |
| First draft and its decisions | `/home/tiroir/.claude/plans/merge-desk.md` |
| Repo conventions | AgentView: `docs/agents/`, `GLOSSARY.md`. sheaf: `SPEC.md` (9.10, 10.11 for actions), `GLOSSARY.md` |
| Code | `/home/tiroir/Projects/agentview` (branch `dev`), `/home/tiroir/Projects/sheaf` (branch `main`) |
| Owner's global rules | `/home/tiroir/.claude/CLAUDE.md` |

Out of scope: `/home/tiroir/Projects/sheaf/.scratch/sheaf-looks/` (its own track, later).

## Frontier

Snapshot on 2026-11-13 22:30 CET. Re-run after every ticket that closes:
`python3 $(ls -d /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/*/skills/hand-to-boss/frontier.py | sort -V | tail -1) <issues dir>`

```
AgentView (.scratch/merge-desk/issues)
Ready now: 01, 02
Waiting: 03 after 02 · 04 after 02 · 06 after 02 · 07 after 02 · 09 after 02 · 05 after 03 · 08 after 03

sheaf (.scratch/action-buttons/issues)
Ready now: 01, 02, 04
Waiting: 03 after 02
```

**Across the two repos.** AgentView 02 to 05 work with a plain sheaf tick today (a tick writes `[x]`), so they do not wait on sheaf. They look right only when sheaf 01 (a button on its own line) and 04 (the Merge, Deploy, Install words) are merged *and installed* on the laptop: install with `uv tool install --reinstall --from git+https://github.com/sweatshop-ai/sheaf@<main sha> sheafmd`, then `sheaf stop` and `sheaf start`. Run sheaf 01 and 04 early, in parallel with AgentView 02.

External blockers:

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| AgentView 07, last box | a press on the phone that merged a PR | Thierry | not yet: ask once 07 is otherwise done |
| sheaf 03 | the tiroir-tt routines that read `- [ ] Share` (check `thinkingtoo/tt-tiroir` before merging; changes on the box go through Thierry's stages) | Thierry, if a box change is needed | not yet |

## Objective

Write it with `boss-goal` from this brief. **Done when**: every ticket in the two issue folders not waiting on an external blocker has Status `done` and its boxes ticked, the sheaf merges are installed on the laptop, and the desk page shows a real waiting PR that Thierry merged with its button. Ones still waiting are listed with who holds them.

## Staffing

- You run on `opus`; workers on `sonnet` (`boss-lifecycle.sh spawn <dir> --model sonnet`).
- One git worktree per worker, own branch: AgentView under `/home/tiroir/Projects/agentview-wt/`, sheaf under `/home/tiroir/Projects/sheaf-wt/`. Never two workers on a branch or a worktree.
- At most 3 workers at once. A good first wave: AgentView 02, sheaf 04, sheaf 01. AgentView 01 (a rename) after 02 merges, so the two do not touch the same page code at once.

## Claiming a ticket

As in `/hand-to-boss`: `frontier.py claim <issues dir> <NN> <worker>`, then commit that one ticket file by path in the shared checkout (AgentView on `dev`; sheaf: the ticket file lands on `main` only through a PR, so claim on the PR branch of that ticket and say so in the tracker). The worker ticks boxes and sets Status in the shared file, committing it by path.

## Done means verified

A box is ticked only with evidence: the command and its output, the test that passed, the CI run id. Status `done` only when every box is ticked.

## Merging, and the desk itself

- **sheaf**: PRs to `main`; CI runs on the t-compute runners (tests only, nothing deploys: `branch_deploys.py /home/tiroir/Projects/sheaf main` reads "tests only"). Merge them yourself once CI is green with `total_count > 0` and the reviews are GO; no ask to Thierry. Browser tests never run on the laptop.
- **AgentView**: no CI. `dev` deploys nothing (`branch_deploys.py` exit 1). The main checkout is live (`agentview.service` runs from it): build in worktrees, merge finished tickets into `dev`, push, restart the service and check the page loads.
- Reviews per PR: `mattpocock-skills:code-review`, then `/codex-review` (Opus fallback when Codex is out).
- **Once ticket 03 is merged, the desk is live: hand your own sheaf PRs to it with `desk ready`** instead of merging them yourself, as the first real use.

## Guardrails

- The main checkouts are shared with other sessions: `git status`, stage only your own paths by name. (`/home/tiroir/.claude/CLAUDE.md`, Three tool habits)
- "Locally, run only the test files your change touches. Never the full suite" and "Browser tests (Playwright, headless Chrome e2e) never run on the laptop". (`/home/tiroir/.claude/CLAUDE.md`, Full test suites)
- Never write to the gateway VPS (137.74.12.211); nothing on tiroir-tt changes outside Thierry's stages. (`/home/tiroir/.claude/CLAUDE.md`, Production; tt-tiroir)
- The desk merges with the laptop's `gh` login: tests use a fake `gh` on PATH, never the real GitHub.
