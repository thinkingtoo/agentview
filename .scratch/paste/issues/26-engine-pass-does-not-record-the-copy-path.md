# 26: paste_engine_pass does not record which copy path ran in WebKit and Firefox

**What to fix:** in WebKit or Firefox, a ClipboardItem that is refused falls back to `copyText` after the await, and the pass still goes green: it checks only the text read back. Chromium's pass records the path (`window.__ways`, `window.__inTapWrites`) and checks that it was `write` inside the tap; the engine pass does not. Record the path there too, and either check it or name in the check which path ran, so a phone-like engine that silently takes the fallback is visible.

**Input:** an engine that refuses `navigator.clipboard.write([new ClipboardItem(...)])`: `copyFetched` catches, awaits the text, calls `copyText`, and the read-back still matches.

**Failing lines:** at 7dc96ed, `tests/ui_smoke.py:1801-1810` checks the button and the read-back only:

```python
    check(f"{name}: copy puts the whole text on the clipboard, byte-order mark included", got == PASTE_FULL, repr(got))
```

against the fallback in `index.html:1169-1175` (`catch (e) { /* no promised items here, or refused: the old way */ }` … `return text !== null && copyText(text);`) and Chromium's path checks at `tests/ui_smoke.py:1719-1721`.

**Class:** c. A documented limit of paste/18 (PR 29); its evidence says so.

**Found in:** PR 29 hunt (Samir, Opus), 2026-11-11.

**Blocked by:** None.

## Evidence

**Ferran, 2026-11-12.** The engine pass now records `navigator.clipboard.write`/`writeText` and the click-listener depth (as the Chromium pass does) and names the path in the check: `webkit: and the copy went by ['write'], written inside the tap: [True]`.

**Reading: `write` is required in both engines.** On t-compute, Firefox 159 and WPE WebKit (Playwright 1.65.1's build) both copy through exactly one `write`, called inside the tap, with no permissions granted (`WAYS_EXPECTED` in `ui_smoke.py`). Neither takes the fallback today, so requiring `write` loses nothing and a silent fall back is a named failure. Limit: WPE WebKit is not Safari; the phone itself is still paste/16.

Mutation, `write` refused (`throw` in place of `navigator.clipboard.write(...)`): the text still reads back, the old checks stay green, the new one fails in both engines:

```
webkit: and the copy went by ['writeText'], written inside the tap: [False] FAILED (['writeText'], [False])
firefox: and the copy went by ['writeText'], written inside the tap: [False] FAILED (['writeText'], [False])
```

**Status:** done
