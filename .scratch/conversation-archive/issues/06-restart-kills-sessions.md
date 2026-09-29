# 06: Restarting agentview.service kills the sessions in its cgroup

**What to build:** nothing yet. This is a problem write-up for the owner to triage, and it changes how the owner's session launcher works, so the fix is their call. When it is decided, this ticket becomes the build.

**The problem:** `systemctl --user restart agentview` ended a batch of running Claude sessions, this one's included, two seconds after the new server started. The service's cgroup holds a tmux server and, afterwards, WezTerm windows and `claude --resume` processes, and systemd kills a cgroup as a whole on a restart. Both facts were observed (see Evidence); that the sessions that died were the ones in the cgroup was not checked directly, and only one session, started 15 hours earlier, was seen to survive.

**Blocked by:** None

**Status:** needs-triage

## Evidence (2026-09-29)

What was observed, and what was not.

- **Before.** At 12:34 `systemctl --user status agentview` listed two things in the service's cgroup: `server.py`, and a tmux server whose command line is `tmux new-session -d -s _agentview_boot`, the command restore runs (`snapshot.py`, `_wait_tmux_settled`). 5 tasks. What else was in the cgroup at 13:02 was not looked at.
- **The restart.** At 13:02:10 `systemctl --user restart agentview` was run to load new code. The command that ran it was itself killed (exit 137), and its session with it. The event log has 7 `session.gone` at 13:02:13, two seconds after the new server's first scan, and 1 more at 13:04:15 that this ticket does not explain. One session that had started 15 hours earlier was seen at 13:02:11 and never went.
- **After.** Between 13:02:45 and 13:03:09, 14 sessions were seen starting again one after the other (14 `session.seen` events, some under placeholder names of the form `<project>-<n>` until their real names were given back). The log does not say what ran restore. At 13:05 `systemctl --user status agentview` listed a new tmux server, `wezterm-gui`, about 14 `claude --resume` processes and their MCP servers: 2,008 tasks, 5.9 GB. At 13:06, `systemctl --user show agentview.service` said `TasksCurrent=2000`, `MemoryCurrent=6.5 GB`, `KillMode=control-group`, `Delegate=no`. This is what the next restart would kill.
- **The login autostart is exposed too (read-only check, 2026-09-29).** On this KDE session the desktop starts `agentview-restore.desktop` as a systemd unit, `app-agentview\x2drestore@autostart.service` (`Type=exec`, `KillMode=control-group`, `OOMPolicy=stop`, in `app.slice`; the unit file is generated from `~/.config/autostart/agentview-restore.desktop`). It ran at 21:06:04 on 2026-09-27, one minute after boot. On 2026-09-28 at 21:52:26 the journal says "A process of this unit has been killed by the OOM killer." Under `OOMPolicy=stop` systemd then stopped the unit and, two seconds later, sent SIGKILL to 151 processes in its cgroup: a tmux server, tmux clients, `claude`, `node`, `sudo`, `bash`, `python`. So the restore's tmux server and the sessions under it had been living in the autostart unit's cgroup for about 24 hours, and an OOM event in any one process took all of them down. A restore was then run by hand in a transient unit named `agentview-rescue-215554.service` (21:55:54 to 21:56:25, `KillMode=process`), which is fix A in miniature.
- **What the restart cost.** At least one command in flight (the one above). The other sessions' in-flight turns were most likely lost too, but that was not checked. The boss session called the episode "workers asleep".

## Why it happens

- `agentview.service` is a plain service with the default `KillMode=control-group`. A restart or a stop sends SIGTERM to every process in its cgroup, then SIGKILL to what is left.
- The server launches what ends up in that cgroup itself. **↺ reopen** POSTs to `/api/restore`, and `server.py` starts `snapshot.py restore` with `subprocess.Popen(..., start_new_session=True)` (`server.py`, `_restore`). `snapshot.py restore` opens windows with `_start_gui` (`wezterm start` under `start_new_session=True`) and starts the tmux server with `tmux new-session`. A click in the closed list runs `snapshot.revive`, which calls `jump.open_tab`, and that has two paths: with no `wezterm-gui` running it starts one from the server with `wezterm start` under `start_new_session=True` (`jump.py`), and with one running it runs `wezterm cli spawn`, which asks that window to open the tab, so the new session belongs to the window's cgroup and not to the service's. `start_new_session` only calls `setsid`. It gives the child its own session and process group. It does not leave the cgroup.
- The login autostart is not outside this: systemd runs it as its own unit (see Evidence), so whatever `snapshot.py restore --login` starts stays in that unit's cgroup, and the unit's `OOMPolicy=stop` turns one OOM-killed process into the loss of the whole cgroup. The trigger is different (an OOM event, not a restart), the mechanism is the same.
- A scope is created with `OOMPolicy=stop` by default (checked on this machine with `systemctl --user show` on a live scope: `OOMPolicy=stop`, and `DefaultOOMPolicy=stop` for the user manager). Fix B without more would move the problem: one OOM-killed process in a scope that holds the tmux server, or a WezTerm window and its tabs, stops the scope and kills the rest. `systemd-run -p OOMPolicy=continue` is accepted on a scope (checked: it shows `OOMPolicy=continue`) and keeps the other processes alive.

## Two ways to fix it

**A. `KillMode=process` in `agentview.service`.** A restart then kills only the main process (`server.py`) and leaves the rest of the cgroup alone.
- Tradeoffs (reasoning about systemd's documented behaviour; none of A or B was tried on this machine): one line, in one file, and it covers every launch path at once. But the leftovers stay in the service's cgroup, so `systemctl --user stop agentview` would report the unit as stopped while a tmux server, WezTerm and a dozen sessions still count as it. systemd then logs "left-over process" warnings at every restart. Memory and task accounting for the unit stays wrong (6.5 GB at 13:06, attributed to a dashboard). Anything that reads the unit's cgroup to decide what is running gets the wrong answer. The tmux and WezTerm processes also keep the old environment of the service.

**B. Launch what the service starts outside the service's cgroup: `systemd-run --user --scope` (or `--slice=`) in front of the `tmux` and `wezterm` commands** in `snapshot.py` (`_start_gui`, and the `tmux new-session` calls of `restore`) and in `jump.py` (the `wezterm start` in `open_tab`, which the closed list reaches). The `wezterm cli spawn` path needs no change once the window it asks is itself outside the service.
- Tradeoffs: they get a cgroup of their own, so a restart of agentview cannot touch them, and the accounting of the unit is right. It changes how the owner's session launcher starts every terminal, in two files (`snapshot.py` is 960 lines) tested mostly against fakes: a wrong flag means restore starts nothing at all, or starts it with the wrong environment (`DISPLAY`, `WAYLAND_DISPLAY`, `SSH_AUTH_SOCK`, `CLAUDE_CODE_CHILD_SESSION`). `systemd-run --scope` blocks until the command exits, so it has to be started in the background too. Every scope is one more unit to name and to clean up.

**B needs one more flag.** Put `-p OOMPolicy=continue` on the scope, for the reason above. It is not in `scope.py` yet.

**Recommendation:** B is the right end state. A is the fix to use today. A alone costs one line and removes the harm, and its leftovers are cosmetic. B is worth doing when restore is next touched for another reason. If the owner wants B, it needs a test on a real desktop: reopen one session, restart the service, and check that the session is still running.

## Acceptance (once decided)

- [ ] `systemctl --user restart agentview` leaves running every session that was in the service's cgroup beforehand. Checked by listing the `claude` processes in `systemctl --user status agentview` before, and counting them and the `session.gone` events in the log after.
- [ ] `systemctl --user stop agentview` says what happened to the sessions, or leaves them running, and the README says which.
- [ ] README: the restart rule is written down where the service is documented, whichever fix is chosen.
- [ ] Until then: the README's "Run it" section says that restarting `agentview` kills every process in the service's cgroup, which can include a tmux server and the sessions in it (check with `systemctl --user status agentview` first), and that server changes are tested on a second server on another port with its own `XDG_STATE_HOME`.
