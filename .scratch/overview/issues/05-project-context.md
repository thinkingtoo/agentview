# Where does a project's "what is this about" line come from?

Type: grilling
Status: resolved
Blocked by: 04

## Question

Each project needs enough context for the person to remember what it is about. Where does that text come from: the repository's CLAUDE.md or README, the boss's brief, a brain note, the sessions' titles, written by hand once? Who keeps it current, how long is it, and what shows when there is none? And what is the project's display name by default (track slug, repository name, client folder) before the person renames it?

## Answer

Resolved 2026-10-17 by grilling, in two rounds.

1. **Track projects:** the context line is the first sentence of the goal file's `## Outcome` (`~/.claude/pm/<track>.goal.md`), cut at about 140 characters, full paragraph on hover. Beside it, the status word from `_Status:` as a small tag (OPEN, PAUSED, MET), never the whole status line.
2. **Track progress:** "N of M" from the ticked boxes under `## Done when`, as a small bar, no percentage. A `MET` status shows "done" whatever the boxes say: on 2026-10-17, 4 of 9 `MET` goals still had unticked boxes. All 32 goal files carry a checklist. Repository projects show no progress.
3. **Repository projects:** the README's first prose paragraph, then the opening of CLAUDE.md or AGENTS.md; headings, badges and `@` includes are skipped. Same cut. Nobody keeps it for the overview; it changes when those files do.
4. **By hand wins:** a line the person writes, edited in place on the page and stored in `config.json` beside the project's rename, keyed by track or repository, overrides both sources.
5. **No source:** up to two recent session titles of the project, greyed and marked as a guess, plus a quiet "add a line". "No project" has no context line.
6. **Default display name:** track slug, repository name (from the remote, so worktrees share it), or client folder name, prettified: hyphens and underscores become spaces, first letter capital, the brand stays lowercase. The raw slug shows in grey on hover. Renames live in `config.json` `names`.
7. **Brain:** never the source of the context line. Each project has a "notes" link that searches the brain on click, with the project name plus its context line, and shows the top 3 hits. A test search for a current track on 2026-10-17 returned only unrelated May notes (best score 0.51), so a search result is a guess. Fixtures and tests never carry brain text; the repo is public.
8. **Boss dispatch briefs** are left out: they are per worker, not per project.
