"""Work out how to put a session's terminal in front of you, and do it.

Every route ends the same way: some emulator is told which tab to show, then
its window is raised. What differs is who has to be asked -- WezTerm's CLI,
tmux, or Konsole over D-Bus -- and a session inside tmux inside WezTerm needs
two of them in order.
"""


def choose_route(*, tty, ancestry, tmux, panes, clients, konsole):
    """Return {"steps": [argv, ...], "window_pid": pid} or None.

    Pure on purpose: the awkward part is deciding, not executing, so deciding
    is what the tests can reach.
    """
    direct = _wezterm(tty, panes)
    if direct:
        return direct

    if tmux and any(comm.startswith("tmux") for comm, _ in ancestry):
        return _through_tmux(tmux, panes, clients, konsole)

    return _konsole(ancestry, konsole)


def _wezterm(tty, panes):
    for pane in panes:
        if pane.get("tty_name") and pane["tty_name"] == tty:
            return {
                "steps": [["wezterm", "cli", "activate-pane",
                           "--pane-id", str(pane["pane_id"])]],
                "window_pid": pane["term_pid"],
            }
    return None


def _through_tmux(tmux, panes, clients, konsole):
    """`session:@window.%pane` -- select it, then reveal whoever is attached."""
    target, _, rest = tmux.partition(":")
    window, _, pane = rest.partition(".")
    steps = []
    if window:
        steps.append(["tmux", "select-window", "-t", window])
    if pane:
        steps.append(["tmux", "select-pane", "-t", pane])

    for client in clients:
        if client.get("session") != target:
            continue
        # The client lives in some emulator too; that one has to come forward.
        host = _wezterm(client.get("client_tty"), panes)
        if host:
            return {"steps": steps + host["steps"],
                    "window_pid": host["window_pid"]}
    return {"steps": steps, "window_pid": None} if steps else None


def _konsole(ancestry, konsole):
    pids = {pid for _, pid in ancestry}
    for app in konsole:
        if app.get("term_pid") not in pids:
            continue
        for window in app.get("windows", []):
            for sid, shell_pid in window.get("sessions", {}).items():
                if shell_pid in pids:
                    return {
                        "steps": [["qdbus", app["service"], window["path"],
                                   "org.kde.konsole.Window.setCurrentSession",
                                   str(sid)]],
                        "window_pid": app["term_pid"],
                    }
    return None

def title_steps(*, text, tty, ancestry, tmux, panes, clients, konsole):
    """How to label this session's tab with `text`. Empty text clears it.

    Deliberately not the same shape as a jump: a session inside tmux is
    labelled by *tmux*, not by the WezTerm tab hosting the client, because
    that tab only ever shows what tmux draws into it.
    """
    if tmux and any(comm.startswith("tmux") for comm, _ in ancestry):
        window = tmux.partition(":")[2].partition(".")[0]
        if not window:
            return []
        if text:
            return [["tmux", "rename-window", "-t", window, text]]
        # Handing the name back to tmux is what "no override" means here.
        return [["tmux", "set-window-option", "-t", window,
                 "automatic-rename", "on"]]

    for pane in panes:
        if pane.get("tty_name") and pane["tty_name"] == tty:
            return [["wezterm", "cli", "set-tab-title",
                     "--pane-id", str(pane["pane_id"]), text]]

    pids = {pid for _, pid in ancestry}
    for app in konsole:
        if app.get("term_pid") not in pids:
            continue
        for window in app.get("windows", []):
            for sid, shell_pid in window.get("sessions", {}).items():
                if shell_pid in pids:
                    return [["qdbus", app["service"], f"/Sessions/{sid}",
                             "org.kde.konsole.Session.setTitle", "1", text]]
    return []


# ---------------------------------------------------------------- adapters

import json
import os
import shutil
import subprocess


def _run(argv, timeout=4):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def ancestry_of(pid, depth=12):
    """[(comm, pid), ...] from the process up towards init."""
    out, cur = [], int(pid)
    for _ in range(depth):
        try:
            with open(f"/proc/{cur}/stat", encoding="utf-8") as fh:
                data = fh.read()
        except OSError:
            break
        close = data.rindex(")")
        comm = data[data.index("(") + 1:close]
        ppid = int(data[close + 2:].split()[1])
        out.append((comm, cur))
        if ppid <= 1:
            break
        cur = ppid
    return out


def tty_of(pid):
    try:
        return os.readlink(f"/proc/{pid}/fd/0")
    except OSError:
        return ""


def wezterm_panes():
    if not shutil.which("wezterm"):
        return []
    res = _run(["wezterm", "cli", "list", "--format", "json"])
    if not res or res.returncode != 0:
        return []
    try:
        panes = json.loads(res.stdout)
    except ValueError:
        return []
    # Every pane belongs to the one GUI process; its window is what gets raised.
    term_pid = _pid_of_command("wezterm-gui")
    return [{"pane_id": p["pane_id"], "tty_name": p.get("tty_name"),
             "term_pid": term_pid} for p in panes]


def _pid_of_command(name):
    res = _run(["pgrep", "-x", name])
    if not res or res.returncode != 0:
        return None
    return int(res.stdout.split()[0])


def tmux_clients():
    if not shutil.which("tmux"):
        return []
    res = _run(["tmux", "list-clients", "-F", "#{client_tty}\t#{client_session}"])
    if not res or res.returncode != 0:
        return []
    out = []
    for line in res.stdout.splitlines():
        tty, _, session = line.partition("\t")
        if tty:
            out.append({"client_tty": tty, "session": session})
    return out


def konsole_apps():
    if not shutil.which("qdbus"):
        return []
    res = _run(["qdbus"])
    if not res:
        return []
    apps = []
    for service in res.stdout.split():
        if not service.startswith("org.kde.konsole-"):
            continue
        try:
            term_pid = int(service.rsplit("-", 1)[1])
        except ValueError:
            continue
        windows = []
        for n in range(1, 9):
            path = f"/Windows/{n}"
            listing = _run(["qdbus", service, path,
                            "org.kde.konsole.Window.sessionList"])
            if not listing or listing.returncode != 0 or not listing.stdout.strip():
                continue
            sessions = {}
            for sid in listing.stdout.split():
                got = _run(["qdbus", service, f"/Sessions/{sid}",
                            "org.kde.konsole.Session.processId"])
                if got and got.returncode == 0 and got.stdout.strip().isdigit():
                    sessions[int(sid)] = int(got.stdout.strip())
            if sessions:
                windows.append({"path": path, "sessions": sessions})
        if windows:
            apps.append({"service": service, "term_pid": term_pid, "windows": windows})
    return apps


def _x_windows():
    """[(pid, window_id), ...] from wmctrl."""
    res = _run(["wmctrl", "-lp"])
    if not res or res.returncode != 0:
        return []
    out = []
    for line in res.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 3 and parts[2].isdigit():
            out.append((int(parts[2]), parts[0]))
    return out


def route_for(pid, tmux=""):
    """The route to a live session's terminal, or None if it has no terminal.

    Konsole is asked last and only if nothing else claimed the session:
    enumerating its sessions is one `qdbus` call each, on a path a click is
    waiting for.
    """
    args = dict(tty=tty_of(pid), ancestry=ancestry_of(pid), tmux=tmux,
                panes=wezterm_panes(), clients=tmux_clients())
    return choose_route(konsole=[], **args) or choose_route(
        konsole=konsole_apps(), **args)


def jump(pid, tmux=""):
    """Put that session's terminal in front of the user. Returns a report."""
    route = route_for(pid, tmux)
    if not route:
        return {"ok": False, "reason": "no terminal hosts this session"}
    ran = []
    for step in route["steps"]:
        res = _run(step)
        ran.append(" ".join(step))
        if res is None or res.returncode != 0:
            return {"ok": False, "reason": f"failed: {' '.join(step)}", "ran": ran}
    window_pid = route.get("window_pid")
    if window_pid:
        for wpid, wid in _x_windows():
            if wpid == window_pid:
                _run(["wmctrl", "-ia", wid])
                ran.append(f"wmctrl -ia {wid}")
                break
    return {"ok": True, "ran": ran}


def set_title(pid, tmux, text):
    """Label a session's terminal tab, so the page and the tab agree.

    Konsole is asked for last and only if nothing else claimed the session:
    enumerating its sessions costs one `qdbus` call each, which is seconds of
    latency on a path the page waits for.
    """
    tty, ancestry = tty_of(pid), ancestry_of(pid)
    args = dict(text=text, tty=tty, ancestry=ancestry, tmux=tmux,
                panes=wezterm_panes(), clients=tmux_clients())
    steps = title_steps(konsole=[], **args)
    if not steps:
        steps = title_steps(konsole=konsole_apps(), **args)
    for step in steps:
        _run(step)
    return [" ".join(s) for s in steps]
