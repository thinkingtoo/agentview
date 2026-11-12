# 01: The server gives a track's card one row per Done when line, with its state

**What to build:** for a track whose boss runs, the server turns each `## Done when` line of `~/.claude/pm/<track>.goal.md` into a row with one of four states, and the tickets the line names:

- **done**: the box is ticked. The box wins: a ticket at Status done does not make its row done, so the rows agree with "N of M".
- **worked**: a worker listed in a `Roster` table of the tracker `~/.claude/pm/<track>.md`, whose session is in the track's column now, has one of the row's tickets in its task cell. A row whose tickets are all done while its box is not ticked is also worked, with `awaiting_tick`.
- **waiting**: no ticket of the row is worked on, and an open ticket of the row has a `Blocked by` that names a ticket that exists and is open.
- **planned**: everything else. A line that names no ticket is only done or planned.

A ticket reference is `<feature>/<NN>` (`paste/12`, `overview-build/23`), or a range (`paste/23 to 26`, `paste/23-26`), looked up as `.scratch/<feature>/issues/<NN>-*.md` in the main checkout of every repository a session of the track works in. A reference that resolves to no file is no ticket. A ticket is done at Status done, resolved or wontfix.

Rows are sorted worked, waiting, planned, done; inside a state, the goal file's order. Each row carries its full text and, per ticket: the reference, the title (the first `# ` heading), the Status, the `Blocked by` text, and the live workers on it.

**Why (Thierry, 2026-11-12, grilling):** "the programmer looks at the agent view and immediately understands what that boss track is about ... There are objectives and for every objective it's either planned, maybe dependent on another issue, maybe done, maybe being worked on ... You don't need to click on it to see the status." Q5: rows are the Done when lines; Q6: the four states; Q9: active first; Q10: ticket references by pattern, ranges included; Q11: roster plus a live session; Q12: the box wins.

**Where:** a new `objectives.py`; `fleet.py` `_column` where the track is built; `context.read` for reading a ticket inside its checkout; `projects.checkouts` for the main checkout.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] A test per state, per sort rule, per reference form (single, range, unresolved), on invented goal files, trackers and tickets in a temp dir
- [ ] A ticket file that is a link out of its checkout (to a file outside `.scratch`) is not read
- [ ] The tracker's struck-through roster rows and workers whose session is gone make nothing worked
- [ ] Reading stays bounded: tickets per card and bytes per ticket have a limit
