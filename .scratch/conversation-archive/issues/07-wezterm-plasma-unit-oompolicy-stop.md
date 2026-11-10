# 07: A WezTerm window opened from the Plasma launcher puts its sessions under OOMPolicy=stop

**What to build:** not decided yet. Like 06, this is a problem write-up for the owner to triage. The fix touches how the owner opens their terminal, so the choice is theirs. Once it is decided, this ticket becomes the build.

**The problem:** the one WezTerm window running since the 2026-11-05 login was opened from the Plasma panel or menu, not by agentview. Plasma runs it in its own app unit, and that unit has `OOMPolicy=stop`. The window holds 4 `claude` processes. If the OOM killer kills any one process in that unit, systemd stops the whole unit and kills the window and all 4 sessions. This is how the restore failed on 2026-09-28 (ticket 06, Evidence: 151 processes killed after one OOM kill in the autostart unit). The login restore did not open a window of its own: it found this one running and reused it, as `snapshot.py` does when a window is already up. Sessions that the restore or a reopen adds as tabs in this window end up in the same unit.

**Blocked by:** None

**Status:** needs-triage

## Evidence

From ticket 06, "Cgroup check, 2026-11-10" (read-only, Sinead), and checked again read-only on 2026-11-11.

- **The window.** One `wezterm-gui`, pid 22119, started 2026-11-05 16:02:24. Its cgroup is `app-org.wezfurlong.wezterm@3004c8e51b5349fc8eb3766be6d8ac4a.service`, the unit Plasma creates for an app started from its launcher. On 2026-11-10: `KillMode=control-group`, `OOMPolicy=stop`, 733 tasks, 9.07 GB. On 2026-11-11: still active, `OOMPolicy=stop`, `KillMode=control-group`, 722 tasks.
- **Who opened it.** Its environment has `SYSTEMD_EXEC_PID=8124` and a `DESKTOP_STARTUP_ID` ending in `8124_…`, and pid 8124 is `plasmashell`. The journal has no `agentview: wezterm window` scope on 2026-11-05. It does have one on every other restore day since the scope change, except 2026-10-13. `~/.config/autostart` has no WezTerm entry, and `ksmserverrc` has `loginMode=emptySession`, so Plasma did not restore the window on its own. The window was opened by hand 16 seconds after the login restore started (`16:02:08 Started run-p8509-i25065.scope - agentview: tmux server`). The restore reused it and reported `resumed 22 session(s)` at 16:03:10.
- **What is exposed.** Of the 43 `claude` processes on 2026-11-10, 39 ran in `tmux-spawn-<uuid>.scope` units under the scoped tmux server (pid 8512, `agentview: tmux server`, `OOMPolicy=continue`). The other 4 ran in the Plasma WezTerm unit. On 2026-11-11 the WezTerm unit still held 4 `claude` processes.
- **Not the drop-in.** Ticket 06 concludes that `agentview.service`'s `switchover.conf` can go. That conclusion holds, because this window is outside the service either way.

## Ways out named so far

Ticket 06's conclusion names two. Neither has been tried.

- Restart the window once through the restore, so that it lands in an `agentview: wezterm window` scope with `OOMPolicy=continue`. This fixes today's window but not the next time one is opened from the launcher.
- Make a WezTerm window started from the launcher land in the same kind of scope, for example a launcher entry that goes through agentview, or a drop-in for the Plasma app unit that sets `OOMPolicy=continue`. Which of these, if any, is the owner's call.
