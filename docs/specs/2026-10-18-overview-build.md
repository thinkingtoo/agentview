# Overview: build spec

Status: ready-for-agent

**2026-10-18 · from the design in `2026-10-18-overview.md` (the decisions, numbers and data
sources live there) and the overview map, `.scratch/overview/map.md`.**

## Problem Statement

The person runs many coding-agent sessions on this laptop at once: bosses leading workers,
sessions across several repositories, some Codex runs. Today's main page groups them by
folder, so one piece of work is split across many blocks and a boss's workers land under
other labels than their boss. Each session gets one flag, and the flags mislead: `stuck` is a
false alarm most of the time because it cannot see a subagent or a background job working,
`ready` reads as "your turn" when another session or a job is about to pick the work up, and a
rate limit or a server error shows up as `ready`. Nothing shows that a session waiting on
tests is still alive. The person cannot tell at a glance which projects are moving, which
session needs them and why, or what a project they have not looked at for a day was about.

## Solution

The overview replaces the main page. Every running project is one column, with a project
card on top that names the project, says in one coloured word whether it needs the person
(NEEDS YOU, ERROR, HUNG, LIMIT, MOVING, ALL IDLE), reminds them what it is about, and shows a
graph of how much its sessions wrote in the last 30 minutes. Under the card, one tile per
session says what job it is on, shows a sign that it is moving (or how long it has been idle),
and when it is stuck names the kind, the reason and what the person needs to act. One click
on a tile puts that session's terminal in front of the person. Sessions idle for hours shrink
to one-line pills, never hidden. The header counts what needs the person and lights those
sessions up on a click. Search, closed and reopen stay as they are, and the chime keeps
working as today.

## User Stories

### Projects

1. As the person, I want every running session grouped under the project I think of it as, so that one piece of work is in one place.
2. As the person, I want a boss and all its workers under one project even when the workers work in other repositories, so that a track reads as one line of work.
3. As the person, I want the boss to show once, at the top of its project, so that I see who leads before who works.
4. As the person, I want worktrees of a repository folded into that repository's project, so that a branch in a worktree does not look like a separate project.
5. As the person, I want each client folder to be its own project, so that two clients never share a column.
6. As the person, I want a session to stay in the project it started in even when it moves into another folder, so that columns do not reshuffle under me.
7. As the person, I want sessions that fit no project gathered in a last "No project" column with a one-click suggestion of where they belong, so that nothing is lost and fixing it is quick.
8. As the person, I want to move a session, a whole track or a whole repository into a project by hand, so that I can correct the grouping.
9. As the person, I want a move I make for a track or a repository to hold for future sessions, so that I make each correction once.
10. As the person, I want to rename a project and merge two projects, so that names match how I talk about the work.
11. As the person, I want project names that read well by default (spaces, a capital, the brand in lowercase) with the raw name on hover, so that I recognise them without renaming everything.
12. As the person, I want the projects I pinned first in my own order, then the other tracks, then repositories, then No project, so that my priorities lead the page.

### Remembering what a project is about

13. As the person, I want a short context line under each project's name, so that I remember what it is about after a day away.
14. As the person, I want a track's context line taken from its goal's outcome, so that it says what the track is for without my writing anything.
15. As the person, I want a repository's context line taken from its README or its agent instructions, so that it is filled for free.
16. As the person, I want to write my own context line in place on the page and have it win over any source, so that I can fix a poor one.
17. As the person, I want recent session titles shown greyed as a guess, with "add a line", when no source exists, so that an empty project still says something and invites a line.
18. As the person, I want a track's status (OPEN, PAUSED, MET) and its "N of M" progress on the card, so that I see how far a track has come.
19. As the person, I want a met track to show "done" even if boxes are left unticked, so that the status I set is what counts.
20. As the person, I want a "notes" link that searches my brain for the project on click, so that I can reach my notes without the page guessing at them.

### The project card

21. As the person, I want the project's name first and its state right under it, so that I read what it is before how it is.
22. As the person, I want each card always coloured by its most urgent session (amber for Needs you, red for Error or Hung, purple for Limit, green for moving, grey when all idle), so that I can scan the page by colour.
23. As the person, I want a 30-minute graph of how much the project's sessions wrote, per minute, so that I see at a glance whether a project is alive and whether it just went quiet.
24. As the person, I want "2 moving · 1 stuck · 1 idle" under the graph, so that I know the mix without counting tiles.

### Sessions

25. As the person, I want each session's tile to say what job it is on, in one line, so that I know what each one is for.
26. As the person, I want my own line for a session to win over anything the session wrote, so that I can label a session my way.
27. As the person, I want the line to keep the session's last summary while it works on the next prompt, so that tiles do not flicker at every prompt.
28. As the person, I want a greyed stand-in (my last prompt, or the branch or folder) when a session has no line, so that no tile is blank.
29. As the person, I want a session's line skipped when it only repeats the project's name or context line, so that the page does not say the same thing twice.
30. As the person, I want a sign of life on every tile ("writing · 8s ago", "waiting on: tests, 12 min", "idle 14 min"), so that I can judge for myself whether it is fine.
31. As the person, I want a session waiting on tests, a subagent, a background job or a Codex run to count as moving, so that it never reads as stuck.
32. As the person, I want an idle session shown as idle, never as "your turn", so that I am not pulled to sessions another session or a job is about to resume.
33. As the person, I want to see the last thing a finished session told me until I have seen it, so that I do not miss a handover.

### Stuck

34. As the person, I want a session that needs me (an open question, an open permission prompt, or things left for me on its line) marked Needs you, so that I know it waits on me and nothing else.
35. As the person, I want the question with its options, or the tool and its command, or the list of things left, shown on the tile, so that I can decide before I jump.
36. As the person, I want "3 things left for you" when a session left several, so that I see the size of the job.
37. As the person, I want a session held by a rate limit marked Limit with the reset time and how long it has been held, so that I know whether to wait or switch.
38. As the person, I want a session stopped by an API or auth error marked Error with the error type, so that I know it will not recover alone.
39. As the person, I want a busy session that has not moved for 10 minutes marked Hung with its last tool and how long ago, so that I find the truly stuck ones.
40. As the person, I want the Hung threshold in the config, so that I can tune it.
41. As the person, I want the chime to keep working exactly as today, so that the redesign does not change what I hear.

### The jump

42. As the person, I want one click on a tile to put that session's own terminal pane in front of me, whatever kind of stuck it is, so that the question or prompt is right there.
43. As the person, I want the click to land on the stuck worker itself, not its boss, so that I answer where the question is.
44. As the person, I want a background session to open in a new tab attached to it, so that sessions without a terminal are reachable too.
45. As the person, I want a session with no terminal shown greyed as "no terminal" before I click, so that I do not click again and again for nothing.
46. As the person, I want a failed jump to keep its reason on the tile for a moment, so that I know why nothing happened.
47. As the person, I want the page never to open a second copy of a running session, so that two windows never write one conversation.

### Header, copy and banners

48. As the person, I want the header to count what needs me, what else is stuck, and what is moving, so that I know the size of things before I scroll.
49. As the person, I want a click on a count to light up those sessions and shrink the columns without any, and a second click to clear it, so that I can focus without losing my bearings.
50. As the person, I want a copy button on a command waiting for my permission, or a command left for me to run, so that I can paste it without selecting text.
51. As the person, I want copying never to answer the session, so that approving still happens in the pane where I can see it.
52. As the person, I want a full disk and a Codex usage limit shown once across the top, so that a machine-wide problem is not repeated on every tile.
53. As the person, I want columns to keep their width and scroll sideways when there are many projects, so that one project never pushes another around.

### Finished sessions

54. As the person, I want a session idle for 2 hours, with its handover read and nothing left for me, shown as a one-line pill at the foot of its column, so that old work stays out of the way but in reach.
55. As the person, I want a pill's line on hover and a click on it to jump, so that picking old work up is one click.
56. As the person, I want pills left out of the card's colour, its summary and the header counts, so that old sessions do not make a project look busy.
57. As the person, I want a pill to become a full tile again on any sign of life, so that resumed work shows without my doing anything.
58. As the person, I want to pin a pill open as a full tile until I unpin it or the session closes, so that I can keep one in view on purpose.
59. As the person, I want the 2-hour threshold in the config, so that I can tune it.

### Codex

60. As the person, I want a Codex review run started by a Claude session shown as that session waiting on it ("waiting on: codex review, 2 min"), so that short runs do not flood the page with tiles.
61. As the person, I want a Codex run nobody started from a Claude session shown as its own tile marked exec, so that a stray run is still seen.
62. As the person, I want an interactive Codex session to show movement, busy and idle, Limit and Error like a Claude session, so that both read the same way.
63. As the person, I want an interactive Codex session waiting on my approval marked Needs you rather than Hung, so that I am not told it is broken when it is waiting on me.

## Implementation Decisions

**Modules**

- **Provider readers (Claude and Codex)** gain new facts per session; they keep reading
  incrementally from the tail, as today:
  - writes per minute over the last 30 minutes, the session's own and its subagents';
  - whether a shell under the session is using CPU;
  - open background tasks with a live shell behind them;
  - the open question or permission prompt and its content;
  - the last record when it is an API error, with its type and any reset time;
  - for Codex: busy and idle from task start and complete records; Limit and Error from the
    error info on task completion; Needs you inferred from an escalated command with no output
    yet; the exec run's starting session, found by walking up the process tree from the Codex
    process to a Claude session's pid; the Codex usage-limit reset time.
- **The roster** (fleet) is the deep module the page reads. It turns provider facts plus config
  into the overview. It owns:
  - project assignment (person's setting, then boss track, then repository with worktrees
    folded and client folders split, then folder, then a guess into No project);
  - name and context line;
  - each session's working-on line, movement sign, stuck kind, finished state and jump target;
  - each project's state, summary and strip;
  - the header counts and the banners.
  Today's flag classification stays alongside it, untouched, for the chime.
- **Jump** gains a route for background sessions (a new tab attached to the session) and
  reports "no terminal" ahead of a click.
- **The page** renders the roster's columns. It decides nothing the roster already decided:
  no classification, no ordering, no counting in the browser.

**Roster contract (the page reads only this)**

- Top level:
  - `columns`, in display order;
  - `counts`: needs you, other stuck, moving;
  - `banners`;
  - what search, closed and the chime read today, unchanged.
- **Column**:
  - project identity and display name, with the raw name;
  - kind (track, repository, folder, none);
  - for a track, the status tag and done/total;
  - context line with its source (own, goal, readme, guess);
  - state (needs, error, hung, limit, moving, idle);
  - strip: 30 per-minute write counts, oldest first;
  - summary counts;
  - `sessions` (full tiles, boss first);
  - `pills` (finished sessions).
- **Session**:
  - key, name, provider, tags (boss, codex, exec);
  - working-on line with its source (own, did, title, prompt, place);
  - movement (writing, waiting on what and since when, idle since, or none);
  - stuck kind with reason and context (question and options, tool and command, things left,
    reset time, error type, last tool and age), or none;
  - unread handover text;
  - jump (pane, attach, none) with a reason when none;
  - suggestion (No project only);
  - pinned.
- Pill: key, name, idle since, working-on line, jump.

**Rules fixed by the design**

- Most urgent state wins, in this order: Needs you, Error, Hung, Limit, moving, idle.
- Pills are counted in nothing.
- Hung means busy, with no write, no CPU-using shell and no live background task for
  `hung_after_minutes` (default 10).
- Finished means idle for `finished_after_minutes` (default 120), handover seen, and nothing
  left for the person.
- The working-on line falls back in this order: own line, did, title, then a stand-in. A line
  equal to the project's name or context line is skipped. A busy session keeps its last `did`.

**Config**

- `assign` becomes keyable by track or repository as well as by session.
- `names` holds project display names.
- New `project_lines`: the person's context line per project.
- New `hung_after_minutes` and `finished_after_minutes`.
- `pinned` keeps meaning "first, in this order".
- Session pins are agentview state, beside the seen marks, not config.
- Existing flag thresholds stay for the chime.

**Unchanged:** the four flags and the chime, search, closed, reopen, the session-line hook and
its file.

## Testing Decisions

- A good test drives a public seam with realistic input and asserts on what the person would
  see in its output, never on a helper's internals. Fixture names and texts are invented; no
  real session titles, prompts or client names, because the repo is public.
- **Main seam: `roster()` with fake providers**, as `test_round` and `test_providers` already
  do. It covers:
  - projects, order and pins;
  - context line sources;
  - card state and colour precedence;
  - every stuck kind, and what is not stuck;
  - movement signs and the strip;
  - finished pills and their return to a tile;
  - header counts, banners, Codex exec runs folded into their starter, and orphan exec tiles.
  Most new tests live here.
- **Provider readers on fixture files**, only for the facts `roster()` cannot reach: Claude
  per-minute writes, subagent writes, background tasks, open prompts, API error records; and
  the Codex rollout records (task start and complete, error info, escalated commands). Prior
  art: `test_codex`, `test_activity`, `test_scan`, with fixtures under the tests' data folder.
  The process-tree walk for an exec run's starter is tested against a fake `/proc`, as
  `test_present` does.
- **Jump: `choose_route`**, pure, for the attach route and "no terminal". Prior art:
  `test_jump`.
- **The page**: a Playwright smoke run by hand, extending `ui_smoke.py`, outside the regular
  test run. It checks columns, the card's second line, the colours, the count filters and the
  copy button.

## Out of Scope

- Acting from the page: answering a question or approving a prompt without jumping.
- Other machines, cloud sessions, systemd routines, and a view for phones.
- Any change to the chime or to the flags it reads.
- Replacing dialogs with one list of things left for the person.
- Codex hooks (`stop`, `permissionRequest`): not until interactive Codex use returns.

## Further Notes

- The layout comes from a prototype the person chose (variant H, local branch
  `prototype/overview-layout`, never pushed). Its fixture page is the visual reference.
- Research findings are on local branches `research/project-signals`,
  `research/movement-signals`, `research/stuck-history` and `research/codex-parity`, never
  pushed because the repo is public.
- The project strip costs no model or API calls. It is a per-minute counter added to the
  transcript reading the server already does on every poll.
