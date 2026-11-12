# 02: The self-reload drops view state kept in memory, and follows the served checkout

**What to fix:** (1) The reload loses `OPEN_ROWS`, `WHOLE`, `NOTES`, `LIGHT`, `REVIVING`/`REOPENING` and the scroll position; none is persisted and none blocks the reload. Persist them in sessionStorage or add them to `staleAndFree`. (2) `agentview.service` serves the live checkout and reads `index.html` per request, so any write there (a checkout, a pull, an editor save) reloads every open tab; a half-written or broken file leaves a tab with no `setInterval`, dead until reloaded by hand, and a pull puts new page script on an old server process. Options: hash the file once at server start and serve those bytes (edits then need a restart, like `server.py`), or keep the tab polling when the new page fails to start.



(3) After any navigation the new page's audio context starts suspended until a click (not tested in a browser), so the chime after a self-reload may stay muzzled. (4) An opened Paste (`PASTE_OPEN`) and `RESTORING` are lost on reload but cannot block it: `PASTE_OPEN` is never pruned against the roster and `RESTORING` stays true up to an hour, so each would stall the reload for the life of the tab. They need a true in-flight flag or pruning first.

**Found in:** Opus bug-hunt of PR 42 (run by Dalia, 2026-11-12), finding 3 and the rest of 4; Spec review, `LIGHT`/`SAVING` note.

**Class:** c.

**Blocked by:** None.

**Status:** needs-triage

**Also (test, Opus review of 5d870c0):** `tests/test_self_reload_js.py` copies `load()`'s last lines instead of running `load()`, so moving the reload back above `announce()` would not fail it; it leaves the free-hold conditions (`SAVING`, `#q`/`#find`) and `CHIME = false` unpinned.
