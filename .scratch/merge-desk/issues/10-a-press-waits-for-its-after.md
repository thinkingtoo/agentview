# 10: A press of an item with `after: N` waits until N is merged

**What to build:** an item handed over with `--after N` (plan, "What the merge desk holds": "the order it must go in") is pressed only once PR N of the same repo is merged. Pressed earlier, the watcher refuses with "not merged: #N must go in first" and unticks the box, as for any refusal. Found while building 03 (Vera, 2026-11-13): 03 stores `after` but does not enforce it.

**Blocked by:** 03, 04 (both change deskwatch.py; boss, 2026-11-14)

**Claimed by:** Katya 2026-11-14 00:36

**Status:** done, on branch katya/10-after (not merged into dev)

- [x] A press of an item whose `after` PR is open is refused with that line, and the box unticks (test_a_press_whose_after_pr_is_open_is_refused_and_unticks_the_box passes)
- [x] Once N is merged, the same press merges (test_once_the_after_pr_is_merged_the_same_press_merges passes)
- [x] Tests use a fake `gh` on PATH, never the real GitHub (tests/test_deskwatch.py FAKE_GH; 126 passed across test_deskwatch, test_desk, test_deskinstall)
