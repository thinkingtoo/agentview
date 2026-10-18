# How should the overview look?

Type: prototype
Status: resolved
Blocked by: 04, 05, 06, 07

## Question

With projects, context, stuck kinds and the working-on line decided: how does the page lay out bosses first, projects separated, sessions under them, the movement sign, stuck reasons and the jump? Build rough variants on fixture data (no real titles) for the person to react to; the person chooses, the agent does not.

## Answer

Resolved 2026-10-18 by prototype, in four rounds with the person. The prototype is one HTML file on fixture data (17 invented sessions in 6 projects plus "No project") on the local branch `prototype/overview-layout`, never pushed. It holds variants A to H; H was chosen.

The overview is **one column per project**, read top to bottom:

- **Columns, not rows.** Heights change all the time as sessions get stuck and unstuck, and in a column that only pushes down its own project. Track projects come first, "No project" last. Columns keep a 230 px minimum width; more projects than fit scroll sideways.
- **Project card on top of each column**, in this order: the name (with the status tag for a track); directly under it the project's state word ("NEEDS YOU", "LIMIT", "MOVING", "ALL IDLE"); the context line (up to three lines); "N of M" for a track and the "notes" link; and a **combined movement strip**: one bar per minute for the last 30 minutes, summing the writes of every session in the project, with "2 moving · 2 stuck · 0 idle" under it.
- **The card is always coloured by its most urgent session**: Needs you amber, Error or Hung red, Limit purple, moving green, all idle grey. The colour shows as the card's top edge, a light tint, the state word on the card's second line, and the strip's colour. The person asked for the name first and the state right under it, never the state above the name.
- **Session tiles under the card**, boss first: dot, name, `boss`/`codex` tags, stuck kind, the jump ("open ↗", or "attach ↗" for a background session, or "no terminal" greyed), the working-on line, and the movement sign ("writing · 8s ago", "waiting on tests, 12 min", "idle 40 min"). A stuck tile has a border in its kind's colour, the reason, and the context box. Tiles carry **no strip of their own**; the project strip is the only graph (variant F, with a strip per tile, was rejected as too busy).
- **Copy button on commands only**: a Bash permission prompt, or a command among the things left for the person. Copying never answers the session; that stays in the pane.
- **Header counts are links**: "3 need you", "3 other stuck", "5 moving". A click lights up the matching sessions, fades the rest, and shrinks columns with none to their card; a second click clears it.
- Sessions idle for more than 2 hours shrink to a one-line pill (name and idle time) under their column. The threshold was a fixture choice, not a decision; see the new ticket on finished sessions.

**Cost of the strip**, asked by the person: no model or API call is involved. The server already reads every new transcript line on each 3-second poll (`Tailed` in `providers/base.py`); the strip is a 30-slot per-minute counter added to that reading.

Rejected along the way: A (project blocks in two columns), B (Needs-you inbox above the projects), C (one dense table; its strip was kept), D and E (one horizontal lane per project; their left-hand project label became the column card).
