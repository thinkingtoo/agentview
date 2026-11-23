# 37: Install items: read a short-hash receipt, say when the install left main, pin only a green commit

**What to fix:** three gaps in `deskinstall.py` that made the sheaf Install item useless on 2026-11-22/23 (Tarek, session 7306b89d).

1. **A receipt with a short rev makes the tool vanish.** On 2026-11-20 10:56 sheaf was installed by hand as `uv tool install --from git+https://github.com/sweatshop-ai/sheaf@a30694be sheafmd`. uv wrote `rev=a30694be` (8 hex) into `~/.local/share/uv/tools/sheafmd/uv-receipt.toml`. `GIT` in `deskinstall.py` requires `rev=[0-9a-f]{40}`, so `read_receipt` returned None: the scan stopped seeing sheaf, and the ticked item was refused with "no uv receipt of a known shape for sheafmd" (desk log 2026-11-22 23:23 and 23:50). The message is wrong: the shape is known, only the hash is short. Fix: accept a 7–39 hex rev and resolve it to the full sha through GitHub (`repos/<owner>/<repo>/commits/<short>`); an ambiguous or unknown short rev gives a refusal that says so, naming the short rev. Keep every other rule of `read_receipt` (one requirement, owners, no other keys).
2. **An install that is no longer on main gets no item and no word.** a30694be predates sheaf's history rewrite of 2026-11-20 (every commit after 1.0.0 got a new sha), so `compare` says `diverged` and `scan_tool` does nothing (`status != "ahead"`). The tool then sits behind main forever with no item. Fix: a diverged install gets an item too, pinned like any other, whose block says the installed commit is not on main (e.g. "installed commit a30694b is not on main (history rewritten?)"); the press must accept installing a pinned main commit over a diverged install (today `install()` refuses unless `compare(installed, pinned)` is `ahead`). A tool *ahead* of main stays without an item.
3. **The pin is main's head, tested or not.** On 2026-11-23 16:16 the item was pinned at ef55dfb, which had no check runs at all, while main's last green CI was b96f36bb, 26 commits earlier with code changes in between. Ticking would install an untested commit. Fix: pin the newest main commit whose checks all finished well (same "green" rule as `deskscan`: at least one check, every conclusion success/neutral/skipped). Look back a bounded number of commits (first-parent of main); if none is green, no item, logged. The block says which commit is pinned and that it is the newest green one, and how far main is ahead of it. Mind paths-ignore: a push touching only `.scratch/**` or `.boss/**` runs no CI on sheaf, so a green commit followed by notes-only commits is the right pin.

**Blocked by:**

**Claimed by:** Emeka (session a30ee7a4), 2026-11-23

**Status:** resolved

## Acceptance criteria
- [x] red then green: a receipt with `rev=a30694be` is read as the tool at the full sha GitHub returns (gh stubbed), and an unknown short rev gives a refusal naming it
- [x] red then green: a diverged install gets an item that says so, and a press of it installs the pinned commit
- [x] red then green: with main's head ungreen and an older green commit, the item pins the green one; with no green commit in the window, no item and a log line
- [x] the module docstring of `deskinstall.py` says the three rules
- [x] only the touched test files run locally, at load < 8; agentview restarted afterwards per memory `restarting-agentview-kills-sessions`, and the live desk shows the sheaf item pinned at a green commit

## Context
- Desk page: http://127.0.0.1:27419/tiroir/.local/state/agentview/merge-desk.md; log `/home/tiroir/.local/state/agentview/merge-desk.log` (`install:sheafmd` records).
- sheaf was reinstalled by hand on 2026-11-22 23:51 at 822a9f67 (full sha, last green main then), and the hub restarted at 1.3.0; the stale item was discarded via `desktable.discard`.
- agentview is public: noreply identity, history check before pushing (memories `agentview-is-public`, `history-check-gate-on-clean`).

## Comments

- 2026-11-23, Emeka: done on branch install-37. Short revs resolve through `repos/<repo>/commits/<short>` (cached per process; an outage is said as such, not as an unknown commit). The pin is the newest green commit on main's first-parent line within 50 (one GraphQL call, 100 history nodes; more than 100 checks on a commit is not green). A diverged item is pressed only over the rev its `ready` record names. With no green commit, an item already on the page stays. Review: code-review (standards + spec) and an Opus fallback (Codex out of tokens), GO; fixes in the same push. Also fixed two dev tests left stale by 3ee417b (bottom-up presses, newest on top). Live check: see below.
- 2026-11-23 17:57, Emeka: agentview restarted (cgroup held server.py only on three reads; 17 claude processes, tmux 11748 and wezterm 15695 before and after). The first scan logged `ready install:sheafmd pinned=ad47060 installed=822a9f6`, and merge-desk.md now reads "Pinned commit: ad47060…, the newest green commit of main of sweatshop-ai/sheaf, main is 12 commits ahead of it" (main head 7df6e63 had no checks). Before the fix the scan had re-pinned main's head every 15 minutes all day. The rendered page was not read: curl gets 401 from the hub and the Chrome extension refused the tab.
