# 20: A worker whose current work is a review shows a scanning 🔍

**What to build:** the sign 🔍 replaces 🔨 or 🧪 for a worker while a review is the thing in flight: running Matt's code-review, running `/codex-review`, or waiting on a background Opus or Codex review agent.

**Why (Thierry, 2026-11-13, "Review: magnifier emoji"):** a fifth sign on the track card. Live example: Vera (codex-down, 01:13) had activity "delegating" and the line "Ticket 40 gebouwd, PR 135 open; wacht op Opus-review en CI".

**Blocked by:** 18 (merged)

**Status:** in-progress

Signs after this ticket:
- swinging 🔨: a turn in flight (busy).
- still 🔨: a question open.
- rocking 🧪: turn over, own background jobs running (ticket 18).
- 🔍: a review agent is running. Moves gently on a small ring (0.12em across, 2.8 s), different from the swing and from the rock. Still under `prefers-reduced-motion`.
- ⏸: a row waiting on someone else, unchanged.

Precedence on a row with several workers: a turn in flight (swinging 🔨 or 🔍) beats still 🔨, which beats 🧪. An `elsewhere` entry carries its own sign.

Which sessions get it: any crew session with a review agent running that would otherwise show 🔨 or 🧪, and also one whose turn is over with only that agent behind it (Vera's state at 01:13, "wacht op Opus-review en CI"): `workers` admits `reviewing` like `watching`. A review agent beside another open job (a CI watch, a shell) still gives 🔍. A session with a question open stays a still 🔨.

## Signal: measured 2026-11-13, picked

Measured on the transcripts of the last four days (2,256 files) and on the live fleet:
- A keyword on the **Agent/Task description** of a running subagent. 1,012 subagent calls. `review` alone catches 739 (73%); a wider word list (`review`, `revue`, `bug hunt`, `delta`, `re-check/re-run/re-gate/re-read`, `opus`, `verdict`, `standards/spec axis`, `codex`) catches 951 (94%). Of 50 sampled newly-caught descriptions, all 50 are reviews ("Opus bug hunt on PR 39", "Delta check PR 136", "Narrow Opus re-run"). Of the 61 left over, a sample of 25 held 4 reviews ("Narrow re-review of PR 132 fix", "Re-review PRs 843 and 335") and none of the rest are. So: precision about 100% on the sample, recall about 99% of reviews.
- Where the description is known while the agent runs: `<session>/subagents/agent-*.meta.json` has `description`, `requestShape` and `finished`. 877 files in four days, all with a description; 870 say `finished: true`. A running one says no `finished` and its `.jsonl` is fresh (the live example, "Codex review 2 (Opus) of ticket 24", was one minute old; the four stale ones were two to three days old, so freshness has to be checked). This covers a background agent, which `delegating` could not name.
- A **Skill** call (`code-review`, `codex-review`): 313 of 440 skill calls. It is in flight for a moment only: the skill loads and the real review is the agents it then runs. Not a signal for "a review is in flight".
- A **`codex exec` shell**: 3,007 Bash calls mention codex, 178 look like exec/review, and a text match on the command also hits `sed`/`cat` commands that merely name it. Usable only on the command's own program (it starts the segment), and only for the job in flight.
- A keyword on the **team-line `did`**: a snapshot of the 9 live lines: 5 name review, Opus or Codex, and only 1 of those 5 had a review agent running (the other 4 are reviews already done, a report to send, or someone else's review). Wrong 4 times in 5, and it is the worker's last words, stale for hours.

The shipped classifier, run on the 881 subagent descriptions of the last four days (`claude.is_review`): 832 are reviews (94%), 49 are not. A review word alone counts (`review`, `revue`, `bug hunt`, `delta check`, `verdict`, `standards/spec axis`, `final read`). `opus` and `codex` count unless a word of work to do stands beside them (`implement*`, `parity`, `build`, `port`, `migrate`, `write`, `draft`, `fix the`, `fix round`). A bare `re-run`, `re-read`, `re-check` or `delta` counts for nothing ("Rerun failing tests", "Delta sync of shelves"). Sampled: 40 of the 49 misses held two review-shaped ones ("Recheck five wording fixes", "Check follow-ups against code"), so recall is about 95%; 40 of the 54 hits that carry only `opus` or `codex` were all reviews ("Opus read of PR 151", "Opus narrow re-run PR 117", "Opus round 2 of PR 101", "Opus check of merge resolution", "Opus fourth pass on 7e373a0", one French: "Repli Opus : chasse aux bogues PR 1-3"). Two are borderline, still reviews of finished work ("Opus round 3, merge conflict edits"). The feared false hits ("Opus fallback implementation", "codex parity", "Opus: fix the flaky test", "Codex fix round 2") were not observed in the data and are pinned as false in `tests/test_review_agent.py`, together with the generic ones the first review tried ("Rerun failing tests", "Reviewer onboarding notes"). Known gaps, left on purpose: the veto blocks `fix the` and `fix round` only, so "Opus: fix flaky test" or "Codex: fixes round 2" would read as reviews, while a wider `fix` veto would drop real reviews measured above ("Opus check of clean() fix", "Narrow Opus read of PR 257 fix"); and "Recheck five wording fixes" is missed. If the live card shows either, widen it then. The first word list missed `re-review` (a lookbehind) and let `delta`, `re-run` and `re-read` through alone; both are fixed.

Picked: **a live subagent whose meta says not finished, whose transcript wrote in the last 10 minutes and whose description is a review's (`claude.is_review`).** Why: it is tied to the running agent itself, needs no cooperation from the worker, catches background agents, and was right on every sample. Not built from it: the `did` line (wrong 4 in 5), the Skill call (momentary), the Bash text (many false hits). A `codex exec` shell is not built in this ticket; say it in a follow-up if the live card shows a miss.

Row precedence: 🔍 is shown when every worker with a turn in flight on the row is in a review; if another worker on it has real work in flight, the row keeps the swinging 🔨.

## Acceptance

- [x] The ticket names the chosen signal with its measured hit and miss rates -- evidence: this file
- [x] A live review subagent (meta not finished, transcript fresh, description a review's) makes the session `reviewing`; a finished, stale, non-review, broken or missing-meta one does not -- evidence: `tests/test_review_agent.py`
- [x] A worker in flight, one whose turn is over with only a review agent behind it, and one with a review agent beside another job each show 🔍; a boss, a concierge and a session with a question open do not -- evidence: `tests/test_objectives.py` (class `Reviewing`)
- [x] A row is reviewing only when every worker in flight on it is; real work in flight beside it keeps the swinging 🔨 -- evidence: same
- [x] The page draws 🔍 with `scan` over 🔨 and 🧪, never on a waiting row; `scan` lives only under `no-preference`, moves on a 0.12em ring inside the room the line leaves it -- evidence: `tests/test_hammers_on_top.py`
- [ ] No clipping on the live card, checked in the personal Chrome after the restart -- evidence: PR comment
