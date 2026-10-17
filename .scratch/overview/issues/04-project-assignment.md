# How does a session get its project?

Type: grilling
Status: resolved
Blocked by: 01

## Question

Given the signals found in "What signals exist to group sessions into projects?", which rule decides a session's project, in what order, and what happens when signals disagree or are missing? Can the person name or merge a project by hand, and where would that live? Does a worktree, a client subfolder or a scratch directory fold into its parent project?

## Answer

Resolved 2026-10-17 by grilling; the person accepted all eight recommendations.

1. **Order, first match wins:** (1) the person's own setting; (2) the boss track: a boss's marker, for a worker its `boss-<track>` tmux session, then its `reportsTo` boss's marker, then the single tracker naming it; (3) the repository, worktrees folded onto their parent and keyed by remote; (4) today's folder rule; (5) a guess from the paths the session touched.
2. **A track is one project across repositories.** A worker in another repository than its boss sits under the boss's project; one repository holding several tracks becomes several projects.
3. **Folding:** worktrees fold into their parent repository; each `clients/<client>/` subfolder is its own project; plain folders holding several repos, and `~/Projects` itself, are never a project and fall to the guess.
4. **Boss signals disagreeing:** for a worker, tmux track, then `reportsTo`, then tracker; for a boss, its marker beats its tmux name.
5. **Stable placement:** for rules 3 and 4 the launch folder decides; a session never changes project because it `cd`s elsewhere.
6. **No project:** sessions placed only by the guess, or by nothing, sit in one last group, "No project", each showing the guessed project as a one-click suggestion.
7. **By hand:** rename, merge, and move a session or a whole track or repository into a project. Stored in agentview's `config.json` (`assign`, renames), keyed by track or repository so it holds for future sessions; a single-session move ends with that session.
8. **A boss shows once,** at the top of its track's project. This clears the "boss whose workers span projects" fog.

Codex sessions reach only rules 3 to 5. The project's default display name moves to "Where does a project's "what is this about" line come from?".
