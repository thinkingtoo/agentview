# 06: Restarting agentview.service kills the sessions that restore resumed

**What to build:** nothing yet. This is a problem write-up for the owner to triage, and it changes how the owner's session launcher works, so the fix is their call. When it is decided, this ticket becomes the build.

**The problem:** `systemctl --user restart agentview` kills the Claude sessions that agentview itself launched (**↺ reopen**, a click in the closed list), and the tmux server and WezTerm windows they run in. They die with the server, in the middle of whatever they were doing. A session that was not launched by the service is not touched.

**Blocked by:** None

**Status:** needs-triage

## Evidence (2026-09-29)

What was observed, and what was not.

- **Before.** At 12:34 `systemctl --user status agentview` listed two things in the service's cgroup: `server.py`, and a tmux server whose command line is `tmux new-session -d -s _agentview_boot`, the command restore runs (`snapshot.py`, `_wait_tmux_settled`). 5 tasks. What else was in the cgroup at 13:02 was not looked at.
- **The restart.** At 13:02:10 `systemctl --user restart agentview` was run to load new code. The command that ran it was itself killed (exit 137), and its session with it. The event log has 7 `session.gone` at 13:02:13, two seconds after the new server's first scan, and 1 more at 13:04:15 that this ticket does not explain. One session that had started 15 hours earlier was seen at 13:02:11 and never went.
- **After.** Between 13:02:45 and 13:03:09, 14 sessions were resumed one after the other (14 new `session.seen` events with resumed ids, some under placeholder names of the form `<project>-<n>` until their real names were given back). The log does not say what ran restore. At 13:05 `systemctl --user status agentview` listed a new tmux server, `wezterm-gui`, about 14 `claude --resume` processes and their MCP servers: 2,008 tasks, 5.9 GB. At 13:06, `systemctl --user show agentview.service` said `TasksCurrent=2000`, `KillMode=control-group`, `Delegate=no`. This is what the next restart would kill.
- **What the restart cost.** At least one command in flight (the one above). The other sessions' in-flight turns were most likely lost too, but that was not checked, and the boss session reported it as "the workers fell asleep".

## Why it happens

- `agentview.service` is a plain service with the default `KillMode=control-group`. A restart or a stop sends SIGTERM to every process in its cgroup, then SIGKILL to what is left.
- The server launches what ends up in that cgroup itself. **↺ reopen** POSTs to `/api/restore`, and `server.py` starts `snapshot.py restore` with `subprocess.Popen(..., start_new_session=True)` (`server.py`, `_restore`). A click in the closed list runs `snapshot.revive`, which ends in `_start_gui` in `snapshot.py`: the same call, `wezterm start` under `start_new_session=True`. `start_new_session` only calls `setsid`. It gives the child its own session and process group. It does not leave the cgroup.
- The login autostart (`agentview-restore.desktop`) is not affected. It runs from the desktop session, so what it starts lives in that session's scope, not in the service.

## Two ways to fix it

**A. `KillMode=process` in `agentview.service`.** A restart then kills only the main process (`server.py`) and leaves the rest of the cgroup alone.
- Tradeoffs: one line, in one file, and it fixes every path at once. But the leftovers stay in the service's cgroup, so `systemctl --user stop agentview` would report the unit as stopped while a tmux server, WezTerm and a dozen sessions still count as it. systemd then logs "left-over process" warnings at every restart. Memory and task accounting for the unit stays wrong (6.5 GB attributed to a dashboard). Anything that reads the unit's cgroup to decide what is running gets the wrong answer. The tmux and WezTerm processes also keep the old environment of the service.

**B. Launch what restore starts outside the service's cgroup: `systemd-run --user --scope` (or `--slice=`) in front of the `tmux` and `wezterm` commands** in `snapshot.py` (`_start_gui`, and the `tmux new-session` calls of `restore`).
- Tradeoffs: they get a cgroup of their own, so a restart of agentview cannot touch them, and the accounting of the unit is right. It changes how the owner's session launcher starts every terminal, in a file that is 960 lines long and tested mostly against fakes: a wrong flag means restore starts nothing at all, or starts it with the wrong environment (`DISPLAY`, `WAYLAND_DISPLAY`, `SSH_AUTH_SOCK`, `CLAUDE_CODE_CHILD_SESSION`). `systemd-run --scope` blocks until the command exits, so it has to be started in the background too. Every scope is one more unit to name and to clean up.

**Recommendation:** B is the right end state. A is the fix to use today. A alone costs one line and removes the harm, and its leftovers are cosmetic. B is worth doing when restore is next touched for another reason. If the owner wants B, it needs a test on a real desktop: reopen one session, restart the service, and check that the session is still running.

## Acceptance (once decided)

- [ ] `systemctl --user restart agentview` with sessions running that were restored through **↺ reopen** or the closed list leaves every one of them running. Checked by counting `claude` processes and `session.gone` events in the log across the restart.
- [ ] `systemctl --user stop agentview` says what happened to the sessions, or leaves them running, and the README says which.
- [ ] README: the restart rule is written down where the service is documented, whichever fix is chosen.
- [ ] Until then: the README's "Run it" section says that restarting `agentview` restarts the sessions it restored, and that server changes are tested on a second server on another port with its own `XDG_STATE_HOME`.
