# 17: The smoke check of the copy's timing misses an await that is not the fetch

**What to build:** `paste_pass` checks that `clipboard.write` was called before the `/api/paste_text` fetch came back (`window.__ways == ["write"]`, tests/ui_smoke.py:1703 at 5337170). Ticket 11 needs more than that: no await at all between the tap and the `write`, since mobile Safari's gesture window may close at the first one. Suppose a later change adds an `await Promise.resolve()` before the `write`. That passes in Chromium, because the microtask settles long before the routed fetch is fulfilled. Record a synchronous marker as well: set it in a capture-phase click listener and clear it with `queueMicrotask`. Then log whether `write` ran while it was set.

**Found in:** Codex review 2 of PR #23 (Opus fallback, run by Runa, 2026-11-11), class c.

**Blocked by:** None.

**Status:** done

**Claimed by:** Samir 2026-11-11

- [x] An `await Promise.resolve();` inserted before the `write` in `copyFetched` fails a named check -- evidence: the mutation and its output

## Evidence

**Samir, 2026-11-11.** Worth fixing: ticket 11's whole point is the tap, and nothing pinned it.

The ticket's marker (set in a capture-phase listener, cleared with `queueMicrotask`) cannot work for a real click: the browser runs a microtask checkpoint after each listener returns, so the marker is cleared before the page's own listener on `#main` runs. `window.event` does not work either: it stays set through the microtask checkpoint, so it is still set after one `await`. Instead an init script wraps every `click` listener in a counter, raised for the listener's synchronous part only (an async listener returns at its first await). The `write` wrapper records whether the counter was above 0. New check in `paste_pass`: "and the write was called inside the tap, before any await".

Red, before the check, with `await Promise.resolve();` inserted before the `write` in `copyFetched` (`paste_pass` alone, `PYTHONDONTWRITEBYTECODE=1`, index.html restored and its hash checked after each mutation):

```
and it went through the ClipboardItem, started before the text came back, not a fallback OK
all green
```

The same mutation with the check:

```
and it went through the ClipboardItem, started before the text came back, not a fallback OK
and the write was called inside the tap, before any await  FAILED [False]
FAILED: ['and the write was called inside the tap, before any await']
```

Green on the real page, `paste_pass` and `paste_stay_pass` together: `and the write was called inside the tap, before any await  OK`, all green, no page or console error. The page is unchanged: it was right; only the check was missing.
