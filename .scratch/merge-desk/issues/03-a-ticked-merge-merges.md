# 03: A ticked Merge merges, at the reviewed commit only

**What to build:** AgentView watches the desk file. A newly ticked Merge item is merged, one at a time in page order: pinned head still current, wait out GitHub's UNKNOWN (60 s, every 2 s), MERGEABLE, then `gh pr merge --merge --match-head-commit`. The result goes under the item; a refusal unticks the box. Every press and result go to `merge-desk.log`. Tonight's temporary server (Kenji's session scratchpad, `merge_server.py`) is the proven reference for these checks.

**Blocked by:** 02


**Claimed by:** Freya 2026-11-13 23:49

**Status:** done

- [x] A branch pushed after the hand-over is refused with "the branch changed after the review", and the box unticks
- [x] Two presses in a row merge one after the other, never at once
- [x] UNKNOWN that clears within 60 s merges; one that does not is refused and says so
- [x] Tests use a fake `gh` on PATH, never the real GitHub

**Evidence** (branch vera/03-ticked-merge; `python3 -m unittest tests.test_deskwatch tests.test_desk`: 73 tests OK, load < 8):
- Branch changed: `Refused.test_a_branch_pushed_after_the_hand_over_is_refused_and_unticks_the_box`
- One at a time: `OneAtATime` (2 tests)
- UNKNOWN: `Unknown` (3 tests: clears within 60 s merges; does not clear is refused and says so)
- Fake gh: whole `tests/test_deskwatch.py` runs a fake `gh` script, `deskwatch.GH` pinned to it; never the real GitHub
- Reviews: code-review, Codex 1-2, Opus 3 and 4 (fix check GO); files vera-03-codex-1/2.md, vera-03-opus-4.md in agentview-wt/
