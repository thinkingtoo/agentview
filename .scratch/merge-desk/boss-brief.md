# Boss brief: Merge desk

Written 2026-11-13 by Kenji with `/hand-to-boss`. You are the boss for
track `merge-desk`. Read this file, then every source it names, before you dispatch
anything. This brief points; the sources hold the content.

The track spans two repositories: AgentView (the desk) and sheaf (the buttons it is
pressed with). Each has its own tickets folder and its own frontier.

## Sources

| What | Path |
|---|---|
| Plan (read first, in full) | `/home/tiroir/Projects/agentview/docs/specs/2026-11-13-merge-desk.md` |
| Tickets, AgentView, one file each, in dependency order | `/home/tiroir/Projects/agentview/.scratch/merge-desk/issues/` |
| Tickets, sheaf, one file each, in dependency order | `/home/tiroir/Projects/sheaf/.scratch/action-buttons/issues/` (and its `README.md` one level up) |
| Handoffs | none |
| Research | `/home/tiroir/.claude/plans/merge-desk.md` (first draft, superseded by the plan; read for the why). The proven reference for a safe merge (pinned commit, waiting out GitHub's UNKNOWN, one merge at a time): `/tmp/claude-1000/-home-tiroir-Projects-sheaf/9b25dd13-7719-4864-9de4-8419cde7f15f/scratchpad/merge_server.py`, a session scratchpad file: copy it into the ticket 03 worktree early |
| Repo conventions | AgentView: `/home/tiroir/Projects/agentview/docs/agents/`, `/home/tiroir/Projects/agentview/GLOSSARY.md`. sheaf: `/home/tiroir/Projects/sheaf/SPEC.md` (9.10, 10.11 for actions), `/home/tiroir/Projects/sheaf/GLOSSARY.md` |
| Code | `/home/tiroir/Projects/agentview` (branch `dev`) |
| Code | `/home/tiroir/Projects/sheaf` (branch `main`) |

Out of scope: `/home/tiroir/Projects/sheaf/.scratch/sheaf-looks/` (its own track, later).

## Frontier

The frontier on 2026-11-13 22:44 CET, from `frontier.py /home/tiroir/Projects/agentview/.scratch/merge-desk/issues`:

```
Ready now: 01, 02
  01  "Fold into" replaces the project merge
  02  A handed-over PR appears on the merge desk page
Waiting on other tickets:
  03  after 02
  04  after 02
  05  after 03
  06  after 02
  07  after 02
  08  after 03
  09  after 02
Done: none
```

and from `frontier.py /home/tiroir/Projects/sheaf/.scratch/action-buttons/issues`:

```
Ready now: 01, 02, 04
  01  A one-off action is a button on its own line
  02  A tick box's label ticks it
  04  Merge, Deploy and Install are action words
Waiting on other tickets:
  03  after 02
Done: none
```

Re-run `python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.23.0/skills/hand-to-boss/frontier.py <issues dir>`
for each of the two folders after every ticket that closes; the output above is a snapshot.

**Across the two folders.** AgentView 02 to 05 work with a plain sheaf tick today (a tick
writes `[x]` into the file), so they do not wait on sheaf. They look right only once sheaf 01
(a button on its own line) and 04 (the three words) are merged and installed on the laptop:
`uv tool install --reinstall --from git+https://github.com/sweatshop-ai/sheaf@<main sha> sheafmd`,
then `sheaf stop` and `sheaf start`. Give sheaf 01 and 04 the first wave. AgentView 01 (a
rename in the page code) goes after AgentView 02 merges, so the two do not edit the same page
code at once.

External blockers — who holds each one, and what unblocks it:

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| AgentView 07, last box | a press on his phone that merged a PR | Thierry | not yet: ask once the rest of 07 is done |
| sheaf 03 | a change on tiroir-tt if its routines read `- [ ] Share` (check `thinkingtoo/tt-tiroir` first; box changes go through his stages) | Thierry | not yet |

An external blocker is a person, not a task: nobody on the team works around it.
A blocker the owner holds goes into your tracker's Open blockers and up the
escalation ladder.

## Objective

Write it with `boss-goal` from this brief. **Done when**: every ticket not waiting
on an external blocker has Status `done` and its boxes ticked; the ones still
waiting are listed with who holds them. Also: the sheaf merges are installed on the
laptop, and the desk page shows a real waiting PR that Thierry merged with its button.
Give it a `## Tickets` section holding
`/home/tiroir/Projects/agentview/.scratch/merge-desk/issues` and
`/home/tiroir/Projects/sheaf/.scratch/action-buttons/issues`, one line each: the pulse then
reads the frontier itself and hands you every ready ticket each time a worker goes idle.
If the pulse reads only the first line, run `frontier.py` on the sheaf folder yourself at
each idle worker.

## Staffing

- You run on `opus`.
- Every worker runs on `sonnet`: `boss-lifecycle.sh spawn <dir> --model sonnet`.
  `BOSS_WORKER_MODEL` is set to the same in your environment, so a spawn without
  `--model` lands there too.
- One git worktree per worker, on its own branch, under `/home/tiroir/Projects/agentview-wt/`
  for AgentView and `/home/tiroir/Projects/sheaf-wt/` for sheaf.
  Two workers never share a branch or a worktree.
- At most 3 workers at once (12 is the span of control): as many as the
  frontier has ready tickets, held to 3 by the laptop's load (tests run locally only for
  the files a change touches, and the laptop is shared).

## Claiming a ticket

The boss claims a ticket at dispatch, before the dispatch message goes out:

```bash
python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.23.0/skills/hand-to-boss/frontier.py claim <issues dir> <NN> <worker>
git -C <repo holding the tickets> commit -m "Claim <NN> for <worker>" -- <ticket file>
```

`claim` writes `**Claimed by:** <worker> <date time>` (replacing an existing
`Claimed by` line) and
sets `**Status:** in-progress`, under a lock, in the shared ticket file. It
refuses (exit 3, naming the claimant) a ticket that is already claimed, done or
still blocked; then nothing is dispatched. A ticket may carry `**Claimed by:**`
empty or with `none`, `nobody` or `-` (any case): all mean unclaimed. The commit names that one file by
path, so it carries nothing else in a tree other sessions share, and no edit is
left uncommitted. Both are coordination, not implementation: if the guard
remarks on them, say so in one line and carry on.

The worker never edits the claim. It reads the ticket at its path under
**Sources**, the shared file, never the copy inside its own worktree, and when
it finishes it ticks the boxes and sets Status there, committing that file by
path in the same way. To release a claim, the boss removes the line, sets
Status back to `ready-for-agent`, commits the file by path and notes it in the
tracker.

On sheaf, `main` takes changes only through pull requests: commit the claim in the shared
checkout `/home/tiroir/Projects/sheaf` and push it to `main` only together with a merged PR,
or carry the ticket file's final state in the ticket's own PR. Say in the tracker which you did.

## Done means verified

A worker ticks an acceptance box only when it has the evidence: the command it ran
and what came back, the URL it read, the test that passed. It puts that evidence
in its report. Status becomes `done` only when every box is ticked. A box that
cannot be verified yet stays unticked with one line saying why.

## Guardrails

Quoted from the rules that bind this work. The source is named on each line; the
source wins where this summary is short.

- Shared tree: "Another session may share this checkout. Before a commit, `git status` and stage only your own paths by name; for more than a small edit, use a worktree." (`/home/tiroir/.claude/CLAUDE.md`, Three tool habits)
- Shared tree: "Parallel workers MUST use separate branches — never two workers on the same branch. Use worktrees" (`/home/tiroir/.claude/CLAUDE.md`, Git Safety)
- Production: "Never write to the gateway VPS (`137.74.12.211`, tiroir.me). It serves real logins." (`/home/tiroir/.claude/CLAUDE.md`, Production)
- Devices and hosts the team may and may not touch: tiroir-tt changes go only through stages Thierry approves (`/home/tiroir/.claude/pm/sheaf-v2.goal.md`); the desk merges with the laptop's `gh` login, so tests use a fake `gh` on PATH, never the real GitHub (plan, "A press and what follows").
- Tests: "Locally, run only the test files your change touches. Never the full suite, never `pytest -n auto`/xdist" and "Browser tests (Playwright, headless Chrome e2e) never run on the laptop, not even one file: run them on t-compute over ssh or in CI" (`/home/tiroir/.claude/CLAUDE.md`, Full test suites)
- Git, AgentView: `dev` deploys nothing (`~/.claude/routines/branch_deploys.py /home/tiroir/Projects/agentview dev` exits 1), so merge finished tickets into `dev` and push: "Where nothing deploys, push." AgentView has no CI. The main checkout is live: `agentview.service` runs `server.py` from `/home/tiroir/Projects/agentview`, so never build there; after a merge, restart the service and check the page loads. (`/home/tiroir/.claude/CLAUDE.md`, Production; `systemctl --user cat agentview.service`)
- Git, sheaf: `main` runs tests only ("reads as tests only" from `branch_deploys.py /home/tiroir/Projects/sheaf main`): "A branch whose workflows only run tests … is not a deploy: merge or push there yourself, no question" once CI is green with `total_count > 0`. (`/home/tiroir/.claude/CLAUDE.md`, Production)

## Shared runtime

What a running worker shares beyond its files, one line per repo in Sources, and
how it gets its own copy.

| Repo | Shared when it runs | Own copy per worker |
|---|---|---|
| AgentView | the live server on 127.0.0.1:8765, `config.json`, the state under `~/.local/state/agentview/`, the laptop's sheaf hub on 27419 | run `server.py` from the worktree with its own `config.json` (`"port"`, a port bound with port 0; 8765 refused), its own `XDG_STATE_HOME`, as `tests/ui_smoke.py` lines 8-26 describe; the desk's sheaf page on its own hub with `SHEAF_HOME` and `SHEAF_PORT` set |
| sheaf | the installed `sheaf` (uv tool) and the live hub on 27419 | `uv sync` in the worktree: proven 2026-11-13 22:42 in a throwaway `git worktree add --detach`, `uv run python -I -c "import sheafmd"` resolved to that worktree's `src/sheafmd`; `tests/conftest.py` refuses to run against another checkout's sheafmd and gives each test its own `SHEAF_HOME`/`SHEAF_PORT` |

A resource with no own copy goes one at a time: writing code stays parallel, and
you give one worker the turn to run on it, then the next. Installing sheaf on the
laptop and restarting its hub is one of those: only the boss does it, after a sheaf
merge, and every open sheaf page reloads.

## Time windows

None stated on 2026-11-13.

## Language

Report to the owner in English. Files, commits, tickets and PRs in English.

## Suggested skills

- `/claude-boss:boss` — you are running it.
- `mattpocock-skills:tdd` — every ticket: red test first, through the seams the tickets name.
- `mattpocock-skills:code-review` — before each merge, standards and spec.
- `codex-review` — the bug hunt after code-review (Opus fallback when Codex is out).
- `mattpocock-skills:diagnosing-bugs` — a red CI run on sheaf that is not the change's.
