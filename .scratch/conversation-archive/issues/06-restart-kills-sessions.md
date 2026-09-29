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

**B needs one more flag.** Put `-p OOMPolicy=continue` on the scope, for the reason above. It is in `SYSTEMD_RUN` in `scope.py`, so the launch sites and the probe both carry it.

**Recommendation:** B is the right end state. A is the fix to use today. A alone costs one line and removes the harm, and its leftovers are cosmetic. B is worth doing when restore is next touched for another reason. If the owner wants B, it needs a test on a real desktop: reopen one session, restart the service, and check that the session is still running.

## Acceptance (once decided)

- [ ] `systemctl --user restart agentview` leaves running every session that was in the service's cgroup beforehand. Checked by listing the `claude` processes in `systemctl --user status agentview` before, and counting them and the `session.gone` events in the log after.
- [ ] `systemctl --user stop agentview` says what happened to the sessions, or leaves them running, and the README says which.
- [x] README: the restart rule is written down where the service is documented, whichever fix is chosen. ("Restarting the service, and what survives it", under "Run it".)
- [x] Until then: the README's "Run it" section says that restarting `agentview` kills every process in the service's cgroup, which can include a tmux server and the sessions in it (check with `systemctl --user status agentview` first), and that server changes are tested on a second server on another port with its own `XDG_STATE_HOME`.

The first two boxes are about the live service and stay open until the last open step under "Live switchover" is done.

## Fix B, built and checked (2026-09-29)

**Built.** `scope.py` puts `systemd-run --user --scope --quiet --collect -p OOMPolicy=continue` in front of the commands that start something long-lived: the tmux server (`snapshot._tmux_argv`, for the `new-session` that can start it), the WezTerm window `restore` opens (`snapshot._start_gui`) and the one the closed list opens (`jump.open_tab`). It fails open: with no user manager the command runs as before and `scope.unavailable` goes to the event log; `AGENTVIEW_SCOPE=off` turns it off. README section added. Observed in a separate run, not part of the check below: `python3 -m pytest tests` gave 558 passed on this branch rebased onto `dev` (19 tests in `tests/test_scope.py`, 71 in `tests/test_scope_check.py`).

**Checked.** `scripts/scope-check` runs a driver in a transient user unit that stands in for `agentview.service` (`KillMode=control-group`). The driver starts a window through `jump.open_tab`, a window through `snapshot._start_gui` and a tmux server and pane through `snapshot._tmux_argv`, with fake `wezterm`, `pgrep` and `claude`, and `tmux` forced onto a private socket with no config file. The harness then restarts the unit. A second run with `AGENTVIEW_SCOPE=off` is the control. No server, port or HTTP is involved. Codex reviewed the script in three rounds before it was run (NO-GO, NO-GO, GO). Run once on 2026-09-29, exit 0 (process ids and the scope's uuid replaced by placeholders):

```
== scoped
  window via jump.open_tab         pid <pid>  run-u2451.scope (agentview: wezterm window, OOMPolicy=continue)        alive after the restart
  window via snapshot._start_gui   pid <pid>  run-u2455.scope (agentview: wezterm window, OOMPolicy=continue)        alive after the restart
  tmux server                      pid <pid>  run-u2458.scope (agentview: tmux server, OOMPolicy=continue)           alive after the restart
  tmux pane                        pid <pid>  tmux-spawn-<uuid>.scope (tmux child pane <pid> launched by process <pid>, OOMPolicy=stop) alive after the restart

== control, AGENTVIEW_SCOPE=off
  window via jump.open_tab         pid <pid>  avsc-9c5471c9-off.service                                              gone after the restart
  window via snapshot._start_gui   pid <pid>  avsc-9c5471c9-off.service                                              gone after the restart
  tmux server                      pid <pid>  avsc-9c5471c9-off.service                                              gone after the restart
  tmux pane                        pid <pid>  avsc-9c5471c9-off.service                                              gone after the restart

== the real desktop
  tmux sessions and WezTerm windows: exactly as before
```

What that shows, and what it does not:

- Observed: with the scope, the tmux server and both windows were each in a scope of their own, described `agentview: ...`, with `OOMPolicy=continue`, and all four processes were alive after the restart of the unit that had started them. Without it, all four were in the unit's cgroup and none was alive after the restart.
- Observed: the pane was in a scope tmux made itself (`OOMPolicy=stop`) in the scoped run, and in the unit's own cgroup in the control run. Why was not looked into.
- Observed, by hand after the run: no unit, scope or process named for the run was left; the real tmux server's 6 sessions and 12 WezTerm tabs were the same before and after; `agentview.service` had the same InvocationID before and after.
- Not shown: that `restore` and `launch` reach these helpers (`tests/test_scope.py` covers that, with fake leaves); the live service, as it was at the time of the check (the sessions running then were in its old cgroup, so a restart of it would still have killed them; see "Live switchover" below for what was done about that; and reading `restore` says it reuses a tmux server and WezTerm window that are already running and does not move them, so they stay there until they are shut down and started again, for instance by the login restore after a reboot); the login autostart unit, which has not been run since the change; `systemctl stop` on its own (the check restarts, which is a stop followed by a start). The restore process itself (`server.py`, `_restore`) is not in a scope, so a restart in the middle of a restore aborts it. The check for a user manager and the launch are two `systemd-run` calls; if the manager goes away between them that one launch fails (running the command again unwrapped cannot be done safely: `systemd-run --scope` returns the command's own exit status).

`Status:` stays as it is until the last open step under "Live switchover" is done.

## Live switchover, way 1 (2026-09-29)

The check above proves the mechanism on a stand-in unit. The live service was switched over the same day, without ending any session, in three steps.

**Proved first on a throwaway unit** with a random name (a file unit, so the mechanism is the same as for the live one). A drop-in with `KillMode=process` and `OOMPolicy=continue` was added while it ran and `systemctl --user daemon-reload` was run: `systemctl --user show` then reported `process` and `continue` on the running unit, with its main process unchanged. After `restart`, its main process was new and the two processes it had started earlier were still alive with the same start times. The unit and its files were removed afterwards. The journal of the user manager showed, once, "Found left-over process ... (sleep) in control group while starting unit. Ignoring." Inference: that is what `KillMode=process` looks like in the log.

**Then on the live unit.** The same drop-in was added to `agentview.service` (`~/.config/systemd/user/agentview.service.d/switchover.conf`) and `daemon-reload` run. `show` reported `KillMode=process` and `OOMPolicy=continue`, main process unchanged. The main checkout was clean at `75f303d`. At 14:42:10 `systemctl --user restart agentview.service` gave the service a new main process and a new InvocationID. Before and after, compared process by process:

- The service's cgroup: 278 processes before, 278 after. The only difference is the old `server.py` replaced by the new one.
- The 15 processes that host sessions (8 `claude`, 1 tmux server, 5 tmux clients, 1 wezterm-gui): all 15 alive with the same start times at the first reading, at least 12 seconds after the restart; all 15 still alive at 49 and 72 seconds.
- The real tmux server: 6 sessions before and after. WezTerm: 12 tabs before and after.
- `session.gone` events in the log: 574 before, 574 at each of those readings.
- `GET /` gave 200 before and after. A search request answered with an extra `meaning` field after the restart and without it before. Inference: the restart loaded the new code; the evidence does not name the commit, only that the checkout it started from was clean at `75f303d`.

The drop-in also changed the `OOMPolicy` that `systemctl --user show` reports for that cgroup (7.7 GB in it) from `stop` to `continue`. That is all that was observed; no OOM kill was induced. Inference, from the systemd documentation: one OOM-killed process there no longer stops the unit and every process in it.

**The last open step: remove the drop-in after the next reboot.** Not before, because without it a restart kills the sessions again.

- Why it has to wait: the tmux server and the WezTerm window that exist today were started before scopes existed, so they, and every session in them, are still in `agentview.service`'s cgroup. Restore reuses a running server and window and does not move them. Inference from reading `snapshot.py` and the autostart entry: after a reboot the login restore starts them through `scope.wrap`. The login restore has not run since the change, so confirm below that it did, before removing anything.
- Check that first. Every tmux server and every WezTerm window must be outside `agentview.service`, in an `agentview: ...` scope with `OOMPolicy=continue`:

  ```
  T=$(pgrep -x 'tmux: server'); W=$(pgrep -x wezterm-gui)
  [ -n "$T" ] && [ -n "$W" ] || echo "FAIL: no tmux server or no wezterm-gui is running, so there is nothing to confirm"
  for p in $T $W; do
    S=$(basename "$(sed 's/^0:://' /proc/$p/cgroup)")
    echo "pid $p in $S"; systemctl --user show "$S" -p Description -p OOMPolicy
  done
  # expected: no FAIL line, and for every pid a run-....scope, "agentview: tmux server" or "agentview: wezterm window", OOMPolicy=continue
  for p in $(cat /sys/fs/cgroup$(systemctl --user show agentview.service -p ControlGroup --value)/cgroup.procs); do cat /proc/$p/comm; done | sort | uniq -c | grep -E 'tmux|wezterm|claude'
  # expected: no output (the service holds no tmux, wezterm or claude process)
  ```
  If either check fails, leave the drop-in in place and find out why.
- Then remove only this drop-in, and confirm the settings reverted:

  ```
  rm ~/.config/systemd/user/agentview.service.d/switchover.conf
  rmdir ~/.config/systemd/user/agentview.service.d      # only succeeds if nothing else is in it
  systemctl --user daemon-reload
  systemctl --user show agentview.service -p KillMode -p OOMPolicy      # expected: control-group, stop
  ```
- After that the restart must lose no session. A count is not enough (a killed and restored process gives the same count), so compare the processes themselves, by pid and start time, and the desktop:

  ```
  snap() { for p in $(pgrep -x claude); do echo "$p $(awk '{print $22}' /proc/$p/stat)"; done | sort; }
  snap > $XDG_RUNTIME_DIR/claude-before.txt
  G=$(grep -c '"session.gone"' ~/.local/state/agentview/events.jsonl)
  echo "$(tmux list-sessions | wc -l) tmux sessions, $(wezterm cli --no-auto-start list | wc -l) wezterm panes"
  systemctl --user restart agentview
  sleep 15; snap > $XDG_RUNTIME_DIR/claude-after.txt
  comm -23 $XDG_RUNTIME_DIR/claude-before.txt $XDG_RUNTIME_DIR/claude-after.txt   # expected: no output (no claude process lost)
  echo "session.gone: $G -> $(grep -c '"session.gone"' ~/.local/state/agentview/events.jsonl)"   # expected: equal
  echo "$(tmux list-sessions | wc -l) tmux sessions, $(wezterm cli --no-auto-start list | wc -l) wezterm panes"   # expected: as before
  ```

  If nothing was lost, tick the first acceptance box.
- Then the same for a stop, which the second box is about and which nobody has tested yet without the drop-in:

  ```
  snap > $XDG_RUNTIME_DIR/claude-before.txt
  systemctl --user stop agentview
  systemctl --user is-active agentview                       # expected: inactive
  snap > $XDG_RUNTIME_DIR/claude-after.txt
  comm -23 $XDG_RUNTIME_DIR/claude-before.txt $XDG_RUNTIME_DIR/claude-after.txt   # expected: no output
  systemctl --user start agentview
  ```

  Write one sentence into the README's "Restarting the service" section saying what a stop does (what was observed), then tick the second box and set `Status:` to `resolved`. If the stop lost sessions, say so in the README instead and leave the box and `Status:` open.
- Inference from the documented behaviour of `KillMode=process`, not tested (only a restart was): while the drop-in exists, `systemctl --user stop agentview` reports the unit stopped and leaves everything running. Observed: the unit's task count and memory include the sessions, since they are in its cgroup.
