# 02: The self-reload drops view state kept in memory, and follows the served checkout

**What to fix:** (1) The reload loses `OPEN_ROWS`, `WHOLE`, `NOTES`, `LIGHT`, `REVIVING`/`REOPENING` and the scroll position; none is persisted and none blocks the reload. Persist them in sessionStorage or add them to `staleAndFree`. (2) `agentview.service` serves the live checkout and reads `index.html` per request, so any write there (a checkout, a pull, an editor save) reloads every open tab; a half-written or broken file leaves a tab with no `setInterval`, dead until reloaded by hand, and a pull puts new page script on an old server process. Options: hash the file once at server start and serve those bytes (edits then need a restart, like `server.py`), or keep the tab polling when the new page fails to start.

**Found in:** Opus bug-hunt of PR 42 (run by Dalia, 2026-11-12), finding 3 and the rest of 4; Spec review, `LIGHT`/`SAVING` note.

**Class:** c.

**Blocked by:** None.

**Status:** needs-triage
