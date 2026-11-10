# 25: Page tests for the goal link's branches on a track card

**What to build:** `tests/ui_smoke.py` checks for the track card from ticket 23: "goal ↗" with its href and `target=_blank` on a page at 127.0.0.1; "goal on the laptop" on any other host (`localhost`, a tailscale name); "no goal page" with the server's reason in the hover when `track.goal.url` is null; "N of M" unfolding and folding the Done when boxes, the unfold surviving a repaint; and box text and the goal's reason given as markup (`<svg onload=...>`) shown as text. Use a fake roster body, as the smoke does for other cards.

**Why:** found by the spec review and by the final review run on PR #6. The server side is tested (`tests/test_goal_page.py`, `tests/test_context.py`), but no test covers `goalLinkOf`, `boxesOf` or `ON_THE_LAPTOP` in index.html. They were checked by hand on a sandboxed server only.

**Where:** `tests/ui_smoke.py`; `index.html` `goalLinkOf`, `boxesOf`, `progressOf`.

**Blocked by:** None.

**Claimed by:** Tarek 2026-11-11

**Status:** done

- [x] Each branch above has a check in ui_smoke, and each check fails when its branch is removed from index.html -- evidence: the smoke output, and one mutation per branch. `goal_pass`, 19 checks, green alone and in the full smoke (452 OK; the one failure is paste/15, which fails the same on dev). 16 mutations of index.html, each fails the pass; table below

## Comments

**Tarek 2026-11-11, evidence.** Full smoke on a throwaway server from the worktree (port 59617 picked by binding 0, listener pid 1868139 proven with `ss`, cwd the worktree, own XDG_STATE_HOME), laptop load 11-13 on 16 cores (t-compute was at 26 on 8). Mutations ran `goal_pass` alone with PYTHONDONTWRITEBYTECODE=1 and `tests/__pycache__` cleared, index.html restored and its hash checked after.

| Mutation of index.html | Check that fails |
|---|---|
| `target="_blank"` dropped | at 127.0.0.1 the goal is a link |
| `ON_THE_LAPTOP` always true | at localhost / at a tailscale name the goal says it opens on the laptop |
| "goal on the laptop" branch removed | same two |
| url-null branch removed | no goal page with the server's reason; a url the hub does not serve; a missing page still says why (other hosts) |
| `startsWith("http://127.0.0.1:")` test dropped | a goal url the laptop's hub does not serve is no link either |
| server's reason dropped from the hover | no goal page with the server's reason; still says why (other hosts) |
| `if (!g) return ""` removed | the page throws on the goal-less track, draws no column, the pass stops at `wait_for_selector` (a crash, not a named check) |
| "N of M" never a button | N of M is a button that lists the boxes on hover |
| box list dropped from the hover | same |
| box-less count drawn as a button | a track with no boxes has its count, and nothing to unfold |
| bar of a track with 0 boxes not full | a track of no boxes at all has a full bar |
| `boxesOf` never unfolds | a click unfolds the boxes; the unfold survives a repaint |
| second click does not fold | a second click folds them; they stay folded through the poll |
| a poll forgets the unfold (`BOXES.clear()` in `load`) | the unfold survives a repaint |
| box text not escaped | markup in a box is text; no dialog, no page error |
| goal reason not escaped | the server's reason in the hover; markup is text; no dialog |

**Tarek 2026-11-11, code review.** Matt's code-review (Standards + Spec), report in `agentview-wt/Tarek-reviews/code-review-25.md`: no defect. Taken: the column found by project, not position; no needless free port; `GOAL_URL` and the spec's `<svg onload>` (`SVG`) with the other constants; the markup check reads the reason too; a `total: 0` bar check and a box-less span mutation. `if (!p)` and the eta span are pinned by `card_pass`. Left: the `if (!g)` mutation fails by crash, not a named check.
