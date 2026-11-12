# 02: The track card shows the rows with a sign, open by default

**What to build:** on the overview, a track's card shows its rows (ticket 01) under the progress line, one line each, without a click: ✅ done (dimmed), 🔨 worked, ⏸ waiting, ○ planned, the sign also in colour. A click on a row unfolds it: its full text and, for each ticket it names, the reference, title, Status, `Blocked by` and the worker on it; "awaiting tick" when its tickets are done and its box is not. A second click folds it. "N of M" still folds all rows away and back; the rows are open by default and a fold is remembered per track in that browser (localStorage) across reloads.

**Why (Thierry, 2026-11-12, grilling):** Q8: all rows, sorted usefully; Q13: a click shows the line and its tickets; Q15: keep the fold; Q17: open by default, remembered.

**Where:** `index.html` `progressOf`, `boxesOf`, the "N of M" click handler; README "What a project is about".

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Every text from a goal, tracker or ticket is printed through `esc()`
- [ ] A row folds and unfolds on click and on tap (no hover needed)
- [ ] A fold survives a reload; a track never folded shows its rows
- [ ] A screenshot of a sandboxed server with invented trackers, kept off the public repo if it shows real text
