# Handoff: hammers swing (boss-track/17), stale-tab finding (boss-track/16)

Branch `feat/hammer-top-and-swing`, PR #47 to `dev`. Not merged.

- **17 done:** `rows[].busy` and `elsewhere[].busy` from `objectives.busy_names(rows, crew, is_concierge)` (crew only, boss and concierges excluded); the page's `signOf()` adds `swing` plus a clock-phased `animation-delay`; keyframe only under `prefers-reduced-motion: no-preference`.
- **16 done, no page change:** the current page draws the hammer first; the bottom hammer was a tab older than ticket 13 (19:36) and the self-reload (19:27). Not provable on his own tab.
- **Review:** Matt's code-review (Standards, Spec) fixed: Busy tests moved above the `__main__` guard, `signOf` replaces the string-splicing `swingTag`, `in_flight` builds on `working`. Opus bug hunt (Codex out) found one real bug, a same-named boss making a worker swing; fixed with a test that fails without the fix.
- **Left to know:** an awaiting-tick row (state worked) swings while its worker is busy. A busy session whose turn is over with a job open is no worker at all (ticket 08), so it has no hammer.
- **Open for the boss:** merge, and ask Thierry to reload old tabs.

## After the merge (2026-11-12)

- PR #47 merged into `dev` as 47a7608 (merge commit); branch and worktree removed; main checkout at origin/dev.
- Restart of `agentview.service`: cgroup held `server.py` alone in 6 of 6 samples; MainPID 2235680 -> 263617; claude processes 32 -> 32, tmux sessions 8 -> 8; `/api/roster` build 6384ceecde4b = sha1(index.html)[:12].
- Live, personal Chrome after a reload: three busy hammers carry `swing` (Ludo, Otilia, Alonso), the transform changes between samples; on the codex-down card the elsewhere hammer is the first `<li>`. No card had a still hammer at the time, so "still" rests on the unit tests.
- Clip check at ±14°: the rotated box passes the `overflow:hidden` note box by 3 to 5 px, but zoomed screenshots at three moments of the swing show the whole glyph, nothing cut. No follow-up PR.
