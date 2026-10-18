# Map: the overview

Label: wayfinder:map

## Destination

A spec at `docs/specs/<date>-overview.md` for a redesign of agentview's main page. At a glance it shows every running project, clearly separated with bosses first, and enough context to remember what each project is about. For each session it shows what the session is working on, a visible sign that it is moving (even while it waits on CI or tests), and whether it is stuck: the kind of stuck, the reason and the context to act on it, plus a one-click jump to that session. The spec then goes to `/to-spec` and `/to-tickets`. No product code is written while the map is open.

## Notes

- Domain language lives in `GLOSSARY.md` (Session, Project, Boss, Worker, Overview, Stuck, Movement). Grilling tickets load `grilling` and `domain-modeling`.
- Scope settled when the map was charted (2026-10-17):
  - The overview *replaces* today's main page. Search, closed and reopen stay as they are.
  - A project is the person's own unit of work, not a folder.
  - Sessions covered: this laptop, interactive Claude and Codex sessions plus their workers.
  - Stuck kinds are named where they can be detected, and a movement sign is always shown so the person can judge the rest.
- Prior art: `docs/specs/2026-08-27-session-states-design.md` defines today's flags (stuck, waiting, ready, tool). Build on it, do not restart.
- **The repo is public.** Tickets, answers and research notes carry dates, counts and field names, never session titles, prompts, client names or conversation text. Research branches stay local and are never pushed.
- The person's own words: auto-memory `overview-need-2026-10-17.md`.

## Decisions so far

- [What signals exist to group sessions into projects?](issues/01-project-signals.md): the boss track is the only project-shaped signal (18 of 24); repository identity with worktrees merged covers the rest; folder labels split 7 repos into 14 groups.
- [What signals show that a session is moving?](issues/02-movement-signals.md): moving = recent transcript or subagent write, a shell under it using CPU, or an open background task with a live shell; the status field alone has no heartbeat.
- [What has stuck looked like on this machine so far?](issues/03-stuck-history.md): unanswered dialogs and waiting on another session dominate; rate limits and server errors show as `ready`; today's `stuck` is false 86% of the time.
- [How does a session get its project?](issues/04-project-assignment.md): person's setting, then boss track (spans repos), then repository with worktrees folded and each client its own project, then folder; launch folder fixes it; leftovers in "No project"; overrides in `config.json` by track or repo.
- [Where does a project's "what is this about" line come from?](issues/05-project-context.md): a track uses its goal's Outcome, status tag and "N of M"; a repository its README then CLAUDE.md; the person's own line wins; otherwise greyed session titles; names are prettified slugs; the brain only behind an on-click "notes" link.
- [Which kinds of stuck does the overview name, and how is each detected?](issues/06-stuck-kinds.md): four kinds, Needs you (question, permission prompt or things left on the session line, all one level), Limit, Error, Hung (busy, not moving for 10 min); waiting on jobs is movement, idle is neutral; flags stay for the chime.
- [What does the "working on" line of a session say?](issues/07-working-on-line.md): the job, not the minute: own line, then `did` (kept while busy), then `title`, else the last prompt greyed; skips repeats of the project line; `doing`, `ask` and `said` move into the movement sign, Needs you and the unseen handover.

## Not yet specified

- **Finished and forgotten sessions.** Sessions idle for hours (13 of 24 on 2026-10-17): shown, folded or dimmed. Decide after the stuck kinds and the layout.
- **Codex parity.** Which movement and stuck signals Codex sessions can give at all.

## Out of scope

- Acting from the page (answering a question, approving a dialog without jumping): a later effort.
- Other machines, cloud sessions, systemd routines.
- Viewing from a phone.
- Changes to the chime.
- Replacing dialogs with one list of things left for the person, answered some other way: changes how every session asks, the chime and the person's own rules; a separate effort (ruled in "Which kinds of stuck does the overview name, and how is each detected?").
