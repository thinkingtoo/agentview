# Handoff: 🧪 and 🔍 on the track card (boss-track/18, 23, 20)

All merged into `dev` and live (service restarted 2026-11-13 02:14, build 4dabf0f39431). Nothing of mine is unmerged.

- **18 (PR 48, merge 9c7beed):** a crew worker whose turn is over with a job of its own open (`waits`) is listed like a working one; sign 🧪, never a swinging hammer. `objectives.workers` admits `working or watching`.
- **23 (PR 51, merge 6ea51d6):** the 🧪 rocks over 2.4 s through ±30° with a hold at each end. `.ov-obj-line`/`.ov-obj-note` clip boxes grow 0.3em to the left (padding and negative margin) so nothing moves. Checked live over the whole cycle on real 🧪 workers: no clipping.
- **20 (PR 53, merge b4ec03f):** 🔍 for a worker with a review agent running. Signal: a live subagent (`subagents/agent-*.meta.json` not `finished`, transcript written in the last 10 min, description is a review's, `claude.is_review`). Beats 🔨 and 🧪; a row is reviewing when every worker in flight on it is. Numbers and the rejected signals (`did` line, Skill call, Bash text) are in the ticket.
- **Open, only one:** the live no-clip check of 🔍 on a real card. No subagent was running at 02:14, so none could be swept and I did not fake one. When a review agent runs, load the page in the personal Chrome, step the `scan` animation over its 2800 ms and compare the sign's box to the line's clip (the ring is 0.12em, the room 0.3em); then set ticket 20 to `done` (it says `in-progress`).
- **Known gaps, in ticket 20:** the veto blocks `fix the` and `fix round` only; "Recheck five wording fixes" is missed. Widen if the live card shows either.
- **Suite:** t-compute has no node, so `tests/test_hammers_on_top.py` (22 tests) skips there; run it on the laptop, one file. One unexplained suite failure in 6 known runs (ticket 23 notes), never reproduced.
- **Restart trap:** `[ cgroup-has-one-process ] && systemctl restart` can skip silently when the transient `ci_state` refresh is in the cgroup; check that MainPID changed. Count tmux with `TMUX` and `TMUX_TMPDIR` unset.
