# Boss brief: one marks store (seen, read and pinned)

Written 2026-10-25 by Tarek with `/hand-to-boss`. You are the boss for
track `marks`. Read this file, then every source it names, before you dispatch
anything. This brief points; the sources hold the content.

## Sources

| What | Path |
|---|---|
| Plan (read first, in full) | `/home/tiroir/Projects/agentview/docs/specs/2026-10-25-marks.md` |
| Tickets, one file each, in dependency order | `/home/tiroir/Projects/agentview/.scratch/marks/issues/` |
| Handoffs | `/home/tiroir/Projects/agentview/handoff-Tarek-2026-10-25.md` (what the two stores are today, the race between a click and a round) |
| Research | none |
| Previous spec this builds on | `/home/tiroir/Projects/agentview/docs/specs/2026-10-25-poll-round.md`, ADR `/home/tiroir/Projects/agentview/docs/adr/0001-lines-forget-only-on-a-full-round.md` |
| Glossary ("Handover read", "Pin (a session)") | `/home/tiroir/Projects/agentview/GLOSSARY.md` |
| Project memories (read all) | `/home/tiroir/.claude/projects/-home-tiroir-Projects-agentview/memory/MEMORY.md` and the files it lists |
| Code | `/home/tiroir/Projects/agentview` (branch `dev`) |

## Frontier

The frontier on 2026-10-25, from `frontier.py /home/tiroir/Projects/agentview/.scratch/marks/issues`:

```
Ready now: 01
  01  One `marks` store for seen, read and pinned
Done: none
```

Re-run `python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.11.5/skills/hand-to-boss/frontier.py /home/tiroir/Projects/agentview/.scratch/marks/issues`
after every ticket that closes; the output above is a snapshot.

External blockers: who holds each one, and what unblocks it:

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| none | | | |

An external blocker is a person, not a task: nobody on the team works around it.
A blocker the owner holds goes into your tracker's Open blockers and up the
escalation ladder.

## Objective

Write it with `boss-goal` from this brief. **Done when**: every ticket not waiting
on an external blocker has Status `done` and its boxes ticked; the ones still
waiting are listed with who holds them. Give it a `## Tickets` section holding
`/home/tiroir/Projects/agentview/.scratch/marks/issues`, one line: the pulse then reads the frontier itself and hands you
every ready ticket each time a worker goes idle.

## Staffing

- You run on `opus`.
- Every worker runs on `sonnet`: `boss-lifecycle.sh spawn <dir> --model sonnet`.
  `BOSS_WORKER_MODEL` is set to the same in your environment, so a spawn without
  `--model` lands there too.
- One git worktree per worker, on its own branch, under `/home/tiroir/Projects/agentview-wt/<worker>`.
  Two workers never share a branch or a worktree.
- At most 1 worker at once (12 is the span of control): as many as the
  frontier has ready tickets. The graph is a single ticket.

## Claiming a ticket

The boss claims a ticket at dispatch, before the dispatch message goes out:

```bash
python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.11.5/skills/hand-to-boss/frontier.py claim /home/tiroir/Projects/agentview/.scratch/marks/issues <NN> <worker>
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

- Shared tree: "Another session may share this checkout. Before a commit, `git status` and stage only your own paths by name; for more than a small edit, use a worktree." (`/home/tiroir/.claude/CLAUDE.md`)
- Public repo: the repo is public. Commit as `tiroir <202564+tiroir@users.noreply.github.com>` (check `git config user.email` in every worktree), and write evidence in tickets as dates and counts, never conversation text. (memory `agentview-is-public.md`)
- History check before every push: `/home/tiroir/Projects/agentview-wt/history-check.py <repo> origin/dev`, output to a file, push only when its last line is `clean`; a hit on a generic title is judged, a client or person name blocks the push. (memory `history-check-gate-on-clean.md`)
- Tests: "Locally, run only the test files your change touches. Never the full suite ... A repo with no t-compute CI ... run the suite on t-compute over ssh, not here." This repo has no CI: the full suite runs on t-compute from a `git archive` of the head, with a private `TMPDIR`, `python3 -m unittest discover -s tests`. (`/home/tiroir/.claude/CLAUDE.md`, memory `tmp-inode-exhaustion-unit-suite.md`)
- Real state: the person's live marks are in `~/.local/state/agentview/` (`seen.json`, `finished.json`). Tests and checks never touch it: point `XDG_STATE_HOME` or `marks_path` at a temp dir. "Sandboxed checks must not reach real things." (memory `sandboxed-checks-must-not-reach-real-things.md`)
- Service restart (the ticket's last box): "Do not remove that drop-in ... without it a restart kills every session in the cgroup again." Before restarting `agentview.service`, check `~/.config/systemd/user/agentview.service.d/switchover.conf` exists (it did on 2026-10-25) and `systemctl --user status agentview`; without the drop-in, the restart is the owner's call. (memory `restarting-agentview-kills-sessions.md`)
- Review: "review through `/codex-review`; if Codex is out, Opus fallback immediately"; `codex exec` needs `< /dev/null`. (memories `codex-out-of-tokens-opus-now.md`, `codex-exec-needs-stdin-closed.md`)
- Git: `dev` deploys nothing (`branch_deploys.py /home/tiroir/Projects/agentview dev` exits 1), so merge into `dev` and push without asking; "Where nothing deploys, push." After merging, delete the feature branch local and remote. Remove the Claude Code footer from commits. (`/home/tiroir/.claude/CLAUDE.md`)

## Time windows

None stated on 2026-10-25.

## Language

Report to the owner in English. Files, commits, tickets and PRs in English.

## Suggested skills

- `/claude-boss:boss`: you are running it.
- `mattpocock-skills:tdd`: the worker builds the ticket test first (the race and the import tests fail on the tree before).
- `mattpocock-skills:code-review`, then `/codex-review`: before the merge into `dev`.
- `mattpocock-skills:diagnosing-bugs`: if the live check after the restart shows tiles that differ from before.
