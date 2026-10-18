# Boss brief: the overview (agentview main page redesign)

Written 2026-10-18 23:58 CEST by Tarek with `/hand-to-boss`. You are the boss for
track `overview-build`. Read this file, then every source it names, before you dispatch
anything. This brief points; the sources hold the content.

## Sources

| What | Path |
|---|---|
| Plan (read first, in full) | `/home/tiroir/Projects/agentview/docs/specs/2026-10-18-overview-build.md` |
| Tickets, one file each, in dependency order | `/home/tiroir/Projects/agentview/.scratch/overview-build/issues/` |
| Design spec (decisions, numbers, data sources the plan points to) | `/home/tiroir/Projects/agentview/docs/specs/2026-10-18-overview.md` |
| The map and its 12 decision tickets (the why behind each rule) | `/home/tiroir/Projects/agentview/.scratch/overview/map.md`, `/home/tiroir/Projects/agentview/.scratch/overview/issues/` |
| Domain words | `/home/tiroir/Projects/agentview/GLOSSARY.md` |
| Prior design the flags come from | `/home/tiroir/Projects/agentview/docs/specs/2026-08-27-session-states-design.md` |
| Handoffs | none |
| Research (local branches only, never pushed; read with `git -C /home/tiroir/Projects/agentview show <branch>:<path>`) | `research/project-signals`, `research/movement-signals`, `research/stuck-history`, `research/codex-parity` |
| Layout prototype (visual reference, variant H; local branch, never pushed) | branch `prototype/overview-layout`, file `prototype-overview.html` |
| Code | `/home/tiroir/Projects/agentview` (branch `dev`) |

## Frontier

The frontier on 2026-10-18 23:58 CEST, from `frontier.py .scratch/overview-build/issues`:

```
Ready now: 01
  01  Overview skeleton
Waiting on other tickets:
  02  after 01
  03  after 02
  04  after 02
  05  after 01, 04
  06  after 01
  07  after 06
  08  after 07
  09  after 08
  10  after 09
  11  after 01
  12  after 09
  13  after 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12
Done: none
```

Re-run `python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.9.1/skills/hand-to-boss/frontier.py /home/tiroir/Projects/agentview/.scratch/overview-build/issues`
after every ticket that closes; the output above is a snapshot.

External blockers — who holds each one, and what unblocks it:

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| none | No ticket waits on a person. Restarting the **live** agentview service to put the new page in front of the owner is the owner's call (see Guardrails); every ticket is verified on a second test server instead. | Thierry | not yet asked |

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
- One git worktree per worker, on its own branch off `dev`, under `/home/tiroir/Projects/agentview-wt/<worker>`.
  Two workers never share a branch or a worktree.
- At most 3 workers at once: after 01 the graph is at most three wide (02→03/04, 06, 11).

## Claiming a ticket

The boss claims a ticket at dispatch, before the dispatch message goes out:

```bash
python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.9.1/skills/hand-to-boss/frontier.py claim /home/tiroir/Projects/agentview/.scratch/overview-build/issues <NN> <worker>
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

- **Public repo, no personal data:** "`thinkingtoo/agentview` is public … commits must use the noreply identity"; "in tickets write evidence as dates and counts, never titles, prompts or search words." Before a push, "check `git log -p origin/dev..HEAD` (not just the final diff) against the archive index for real names, titles and prompt openings." Fixture names and texts are invented. (`/home/tiroir/.claude/projects/-home-tiroir-Projects-agentview/memory/agentview-is-public.md`, `…/memory/codex-exec-needs-stdin-closed.md`). Each new worktree checks `git config user.email` is `202564+tiroir@users.noreply.github.com` before its first commit.
- **Shared tree:** "Another session may share this checkout. Before a commit, `git status` and stage only your own paths by name; for more than a small edit, use a worktree." "Never `git checkout` in a shared working directory when other workers are in the same project." (`/home/tiroir/.claude/CLAUDE.md`)
- **The live service (production for this repo):** "Before any restart of the live one, run `systemctl --user status agentview` and look at the CGroup list; if it holds tmux or claude processes, the restart is the owner's call, not a test step." "Do not remove that drop-in" (`~/.config/systemd/user/agentview.service.d/switchover.conf`, present on 2026-10-18). "Test server changes on a second server from the worktree on another port … `XDG_STATE_HOME` pointed elsewhere so the log is separate." (`/home/tiroir/.claude/projects/-home-tiroir-Projects-agentview/memory/restarting-agentview-kills-sessions.md`)
- **Test servers and launch code must not reach real sessions:** "Pick ports by binding port 0, and send a request only after proving the listener's pid is the unit you started"; "Sandbox tmux with a short directory … that exists, then preflight read-only"; "Never issue the safety check and the launch in one parallel tool batch." This binds ticket 11 (jump, `claude attach`) above all: a test never opens a tab or attaches to a real session. (`/home/tiroir/.claude/projects/-home-tiroir-Projects-agentview/memory/sandboxed-checks-must-not-reach-real-things.md`)
- **Git:** `dev` deploys nothing (`branch_deploys.py /home/tiroir/Projects/agentview dev` exited 1 on 2026-10-18), so merged work on `dev` is pushed without asking: "Where nothing deploys, push." Workers merge to `dev` through the boss; after merging a branch, delete it. "After creating a commit, run `git commit --amend` to remove the Claude Code footer." (`/home/tiroir/.claude/CLAUDE.md`). Never push the local `research/*` or `prototype/*` branches.
- **Codex as second opinion:** run `codex exec -s read-only "$(cat prompt.txt)" < /dev/null > review.md 2>&1` with `timeout 570`; "The `< /dev/null` is not optional." Re-run until a GO on the final diff. The binary is under `~/.nvm/versions/node/*/bin/codex` when not on PATH. (`…/memory/codex-exec-needs-stdin-closed.md`)
- **Blockers go to the owner through `AskUserQuestion`, never as prose at the end of a turn** (the chime only rings on `waiting`). (`/home/tiroir/.claude/CLAUDE.md`)

## Time windows

None stated on 2026-10-18.

## Language

Report to the owner in English. Files, commits, tickets and PRs in English.

## Suggested skills

- `/claude-boss:boss` — you are running it.
- `mattpocock-skills:tdd` — every ticket: test-first through the seams the plan names (`roster()` with fake providers first).
- `mattpocock-skills:code-review` — on each branch before it merges to `dev`.
- `codex-review` — the bug hunt after the code review, with the invocation above.
- `mattpocock-skills:diagnosing-bugs` — when a test or the smoke run fails for an unclear reason.
- `render-doc` — only if a report for the owner is long enough to need a page.
