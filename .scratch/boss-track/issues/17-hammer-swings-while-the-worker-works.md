# 17: A hammer swings while its worker works and stays still while it waits

**What to build:** every `🔨` on a track card (worked rows, elsewhere lines) swings when a worker behind it has a turn in flight, and is still when none has.

**Why (Thierry, 2026-11-12, in Italian):** "you remember I asked you to make it move while it works and keep it still while it's waiting."

**Blocked by:** 13

**Status:** done

- Busy = the session's status is `busy` and its turn is not over with a job open (`waits` false). A question open (`waiting`), or the turn over with a shell or Monitor behind it (`waits`), is still.
- The server sends it: `rows[].busy` (any worker on any of the row's tickets is busy) and `elsewhere[].busy`.
- The page: `.swing` on the `🔨` sign, a small CSS keyframe, only under `prefers-reduced-motion: no-preference`. The `⏸` sign of a waiting row is untouched.

- [x] A busy worker makes its row and its elsewhere entry busy; a waiting one and one with a job behind a finished turn do not; with several workers on a row, one busy is enough -- evidence: `tests/test_objectives.py` (class `Busy`)
- [x] The sign of a busy row or entry carries `swing`, the others do not; the `⏸` row never does -- evidence: `tests/test_hammers_on_top.py`
- [x] The stylesheet animates `.swing` only under `prefers-reduced-motion: no-preference` -- evidence: `tests/test_hammers_on_top.py`
