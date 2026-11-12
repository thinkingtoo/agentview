# 27: Engine pass leftovers from the PR 39 review (all class c)

**What to fix:** small things the review of paste/25 + paste/26 (PR 39) found in `paste_engine_pass`, none of them a wrong result today.

- The path check reads "went by the selection" whenever `__ways` is empty, also when no copy call happened at all. Word it for the empty list.
- The check's name carries run-time values (`ways`, `in_tap`), so the `FAILED: [...]` line differs between runs; the values already sit in the detail.
- `waits()` catches only `TimeoutError`; `copy.click()`, `wait_for_selector`, `goto`, and `copy.inner_text()` (called twice) can still raise on a missing button or a crashed page.
- Both waits are 5 s instead of Playwright's 30 s: a slow first WebKit fetch on a loaded runner could fail by name. Not observed; raise it if it is.
- `WAYS_EXPECTED[name]` raises `KeyError` for an engine other than webkit or firefox; `Control+V` is the Linux key.
- The init script duplicates the one in `paste_pass`; a "keep in step" comment would help. No negative case for a `write` called outside the tap.
- t-compute has no WebKit or Firefox for Playwright out of the box (the tickets of paste/18 said so for the laptop): a private venv with Playwright 1.65.1 and the three libraries is in `~/ferran-pw` there; making that a documented, shared setup is a separate job.

**Class:** c.

**Found in:** PR 39 review (Ferran, Opus agent, Matt code-review), 2026-11-12.

**Blocked by:** None.

**Status:** needs-triage
