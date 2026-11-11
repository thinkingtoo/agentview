# 17: The smoke check of the copy's timing misses an await that is not the fetch

**What to build:** `paste_pass` checks that `clipboard.write` was called before the `/api/paste_text` fetch came back (`window.__ways == ["write"]`, tests/ui_smoke.py:1703 at 5337170). Ticket 11 needs more than that: no await at all between the tap and the `write`, since mobile Safari's gesture window may close at the first one. Suppose a later change adds an `await Promise.resolve()` before the `write`. That passes in Chromium, because the microtask settles long before the routed fetch is fulfilled. Record a synchronous marker as well: set it in a capture-phase click listener and clear it with `queueMicrotask`. Then log whether `write` ran while it was set.

**Found in:** Codex review 2 of PR #23 (Opus fallback, run by Runa, 2026-11-11), class c.

**Blocked by:** None.

**Status:** needs-triage

- [ ] An `await Promise.resolve();` inserted before the `write` in `copyFetched` fails a named check -- evidence: the mutation and its output
