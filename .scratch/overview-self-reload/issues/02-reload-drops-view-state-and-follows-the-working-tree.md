# 02: The self-reload drops view state kept in memory, and follows the served checkout

**What to fix:** (1) The reload loses `OPEN_ROWS`, `WHOLE`, `NOTES`, `LIGHT`, `REVIVING`/`REOPENING` and the scroll position; none is persisted and none blocks the reload. Persist them in sessionStorage or add them to `staleAndFree`. (2) `agentview.service` serves the live checkout and reads `index.html` per request, so any write there (a checkout, a pull, an editor save) reloads every open tab; a half-written or broken file leaves a tab with no `setInterval`, dead until reloaded by hand, and a pull puts new page script on an old server process. Options: hash the file once at server start and serve those bytes (edits then need a restart, like `server.py`), or keep the tab polling when the new page fails to start.

(3) A session that turns waiting in the poll that triggers the reload is never announced: the reloaded page takes its first roster as the baseline (`WAITING`/`READY` null). Persist both in sessionStorage. Announcing before the reload does not work (`play()` awaits the audio context and the page is gone). After any navigation the new page's audio context also starts suspended until a click (not tested in a browser). (4) An opened Paste (`PASTE_OPEN`) and `RESTORING` are lost on reload but cannot block it: `PASTE_OPEN` is never pruned against the roster and `RESTORING` stays true up to an hour, so each would stall the reload for the life of the tab. They need a true in-flight flag or pruning first.

**Found in:** Opus bug-hunt of PR 42 (run by Dalia, 2026-11-12), finding 3 and the rest of 4; Spec review, `LIGHT`/`SAVING` note.

**Class:** c.

**Blocked by:** None.

**Status:** needs-triage
