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

**Status:** needs-triage
