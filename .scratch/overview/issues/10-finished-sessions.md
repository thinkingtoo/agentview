# When is a session finished and forgotten, and how does it show?

Type: grilling
Status: resolved
Blocked by: none

## Question

Using "How should the overview look?": 13 of 24 sessions on 2026-10-17 had been idle for hours. The chosen layout shrinks a session to a one-line pill under its project column, but the 2-hour threshold was a fixture choice. When does a session count as finished and forgotten (time idle, an unseen handover, a session line with `n` = 0, its project's state)? Is it a pill, folded behind a count, or hidden? Does a pill still count toward its project card's colour and the header counts? Does anything bring it back to a full tile?

## Answer

Resolved 2026-10-18 by grilling. Over the last 30 days (765 Claude sessions), idle spells were often followed by more work: 520 spells of 2 hours or more, 234 of 8 hours or more, 44 of 24 hours or more, 8 of 48 hours or more. A session idle for hours still comes back about 17 times a day, so it is never hidden. The live roster could not be used that day: all 18 idle sessions had been reset to 0 to 0.3 hours.

- **Finished**: idle for 2 hours or more, its handover seen, and nothing left for the person (`n` = 0). An unread handover or a thing left for the person keeps it a full tile however old it is. The 2 hours sit in `config.json` beside the other thresholds.
- **A pill at the foot of its project column**: name and idle time on one line, the working-on line on hover, and a click jumps like a tile.
- **Not counted**: pills are left out of the project card's state and summary, and out of the header counts. A project with only pills shows its card grey, ALL IDLE, with the pills under it.
- **Back to a tile automatically** on any sign of life: a new prompt, a write, or a stuck kind. It shrinks again after the next 2 hours idle.
- **Pinned by hand**: a pill can be pinned open so it stays a full tile. Defaults the agent set, not asked: a pin belongs to that one session, lasts until it is unpinned or the session closes, and is kept in agentview's own state beside the seen marks, not in `config.json`. A pinned idle session counts as an ordinary idle tile.
