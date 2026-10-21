# 22: A session waiting on CI, with an ETA

**What to build:** a session at rest whose branch's latest GitHub Actions run, for the commit its own checkout is at, is queued or running shows "waiting on CI" with how long and an ETA; its card waits (ticket 20's state). The owner decided yes on 2026-10-21 (through the claude-boss session that wrote the shared module).

**Blocked by:** 20

**Claimed by:** Tarek 2026-10-21

**Status:** in review (branch `overview/22-ci-wait`)

## How

- `ci_state.py` vendored from claude-boss@430098a (`scripts/vendor-ci-state`, the `registry.py` pattern). Its contract: the caller only reads a cache; a refresh runs detached, one at a time; any failure is `unknown`; `head_sha` is the run's commit.
- `projects.head_of(cwd)`: the remote and the commit the checkout is at, from its `.git` files (worktrees, loose and packed refs), regular files only and bounded reads, never git.
- `fleet.ci_of`: asked only for a session that is not working and not stuck, has a branch, a GitHub remote, and has rested under `CI_LOOK_MINUTES` (180) or waits on a job; shown only when the run's `head_sha` is the checkout's commit.
- Tests replace `fleet.CI_STATE` in the shared `Base`, so no test reaches GitHub or the real cache.

## Boxes

- [x] Tile, card, counts and pills through `roster()` with a fake `ci_state` (`tests/test_ci_wait.py`, 9 tests)
- [x] `head_of` on real temporary repositories: a checkout, a worktree, a packed ref, no repository or no remote (4 tests)
- [ ] Seen on the live page on a real run

## Hunt 22-1 (Opus, 2026-10-21) on 435bbf2: NO-GO on one P1, fixed

P1: a NUL in a checkout's HEAD ref (`ref: refs/heads/a\0b`) raised `ValueError` out of `regular()` and would fail `/api/roster` for every tile. Fixed: the ref is refused, `_small` catches `ValueError`, and `ci_of` turns anything it raises into no CI (test with a `CI_HEAD` that raises). Clean: FIFOs, symlink loops, unreadable files, non-UTF-8 refs, `..`, host spellings (`GITHUB.COM` normalised, `github.com.evil.example` refused), no test reaching GitHub (traced: 0 calls). P2 taken: only a commit origin's branch also has is asked about (a local or unpushed branch costs no refresh); a run past its median says "longer than usual" instead of "about <1 min left"; an ETA that is a bool, negative, non-finite or over a week is left out. P2 accepted and in the README: two sessions in one checkout both show the wait; an ssh alias remote (`github-alias:o/n`) never shows CI.
