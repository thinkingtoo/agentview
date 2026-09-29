"""Start long-lived processes in a cgroup of their own.

`agentview.service` kills everything in its cgroup when it restarts, and a
process the server starts stays in that cgroup however it detaches:
`start_new_session` is `setsid`, which gives a process its own session, not
its own cgroup. A tmux server or a WezTerm window started from here therefore
died with the service and took every session inside it along.

`wrap` puts `systemd-run --user --scope` in front of such a command.
systemd-run moves itself into a new transient scope and then execs the
command, so the command runs exactly as before -- same environment, same
arguments, same exit code -- in a scope a restart of the service does not
touch. (tmux 3.4 already gives each pane a scope of its own; what dies with
the service is the tmux server that owns the panes, and the WezTerm GUI.)

Fail-open. Without a user manager to talk to (no `systemd-run`, no bus) the
command comes back as it was: starting it in the service's cgroup beats not
starting it. The reason goes to the event log. `AGENTVIEW_SCOPE=off` turns
scoping off, to compare against the old behaviour.
"""
import os
import shutil
import subprocess

import log

# OOMPolicy=continue: a scope defaults to `stop`, so one process the kernel kills
# for memory takes the whole scope down, and with it every session in a tmux server.
SYSTEMD_RUN = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "-p", "OOMPolicy=continue"]
OFF = ("off", "0", "no", "false")


def why_not():
    """Why a command cannot be put in a scope of its own right now, or ''.

    Asked for every launch rather than remembered: a launch is a click, and
    the answer changes when the bus goes away.
    """
    if os.environ.get("AGENTVIEW_SCOPE", "").lower() in OFF:
        return "AGENTVIEW_SCOPE is off"
    if not shutil.which("systemd-run"):
        return "no systemd-run"
    try:
        res = subprocess.run(SYSTEMD_RUN + ["--", "true"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"systemd-run: {exc}"
    if res.returncode != 0:
        return f"systemd-run exited {res.returncode}: {(res.stderr or '').strip()[:120]}"
    return ""


def wrap(argv, what):
    """`argv`, started in a scope of its own; `what` says which in `systemctl
    --user status`. `what` is a fixed word, never anything a conversation said."""
    reason = why_not()
    if reason:
        if reason != "AGENTVIEW_SCOPE is off":
            log.event("scope.unavailable", what=what, why=reason)
        return list(argv)
    return SYSTEMD_RUN + [f"--description=agentview: {what}", "--"] + list(argv)
