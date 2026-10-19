# 13: Retire the old view

**What to build:** Contract: the overview is the only main view. The roster stops returning `blocks`; the chime, search and closed read from the new contract; the old block rendering and second-line code leave the page. Nothing the person sees changes except that the old view can no longer come back. The tab title counts from the header's counts (09), not from the old flags, so the two can no longer differ (found by 09). The smoke's block-view checks leave with the view, among them `blocks_pass`'s drag check, which failed once and passed on rerun several times on 2026-10-19.

**Blocked by:** 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 14, 15

**Status:** ready-for-agent

- [ ] No caller reads `blocks` any more and it is gone from the roster
- [ ] The chime rings as before (flags still computed), search, closed and reopen work
- [ ] The tab title's count equals the header's "need you" count, tested
- [ ] The full test suite passes and the smoke run by hand passes
