"""Work out how to put a session's terminal in front of you, and do it.

Every route ends the same way: some emulator is told which tab to show, then
its window is raised. What differs is who has to be asked -- WezTerm's CLI,
tmux, or Konsole over D-Bus -- and a session inside tmux inside WezTerm needs
two of them in order.
"""

import re


# `claude --bg` names a background session by eight hex digits. That, and
# nothing else, is what may reach `claude attach`'s command line.
JOB_ID = re.compile(r"[a-f0-9]{8}")


def is_job(value):
    return isinstance(value, str) and bool(JOB_ID.fullmatch(value))


def choose_route(*, tty, ancestry, tmux, panes, clients, konsole, job=""):
    """Return {"steps": [argv, ...], "window_pid": pid} or None.

    A background session has no terminal of its own: `job` is its job id, and
    when no terminal route is found a new tab that attaches to it is asked
    for. Whoever calls with a job has already ruled out that a `claude attach`
    is showing it (`attach()` does), because two windows on one conversation
    would both write to it.

    Pure on purpose: the awkward part is deciding, not executing, so deciding
    is what the tests can reach.
    """
    route = _terminal_route(tty, ancestry, tmux, panes, clients, konsole)
    if route or not is_job(job):
        return route
    return {"steps": [], "window_pid": None, "open": ["claude", "attach", job]}


def _terminal_route(tty, ancestry, tmux, panes, clients, konsole):
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
                "steps": [["wezterm", "cli", "--no-auto-start", "activate-pane",
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
    # Nobody is attached: selecting the pane alone shows nothing. The caller
    # opens a terminal on the session first.
    return {"steps": steps, "window_pid": None, "attach": target} if steps else None


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
            return [["wezterm", "cli", "--no-auto-start", "set-tab-title",
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
import threading
import time

import scope  # noqa: E402


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
    res = _run(["wezterm", "cli", "--no-auto-start", "list", "--format", "json"])
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
    return _follow(route)


def _follow(route):
    """Carry a route out: run its steps, open the tab it asks for, raise the window."""
    ran = []
    for step in route["steps"]:
        res = _run(step)
        ran.append(" ".join(step))
        if res is None or res.returncode != 0:
            return {"ok": False, "reason": f"failed: {' '.join(step)}", "ran": ran}
    if route.get("attach"):
        opened = open_tab(["tmux", "attach", "-t", f"={route['attach']}"])
        ran += opened["ran"]
        return {**opened, "ran": ran}
    if route.get("open"):
        # The tab runs in WezTerm's environment, whose PATH may lack `claude`.
        import snapshot
        opened = open_tab([snapshot.claude_bin(), *route["open"][1:]])
        ran += opened["ran"]
        return {**opened, "ran": ran}
    _raise(route.get("window_pid"), ran)
    return {"ok": True, "ran": ran}


# ------------------------------------------------- background sessions

ATTACH_GRACE = 5             # seconds a new tab is given to show up as a process
COLD_START_GRACE = 30        # ...when no WezTerm was running: the window has to start first
_ATTACH = threading.Lock()   # asking whether it is attached and attaching are one step
_ATTACHING = {}              # job id -> until when a tab opened for it may still be starting


MAY_BE_SHOWN = "a claude attach on a name shared with another session may be showing it"


def attaches(proc="/proc"):
    """[(pid, what it was told to attach), ...] for every `claude attach` running."""
    found = []
    try:
        entries = list(os.scandir(proc))
    except OSError:
        return found
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            with open(os.path.join(entry.path, "cmdline"), "rb") as fh:
                args = fh.read().split(b"\0")
        except OSError:
            continue
        if len(args) >= 3 and args[1] == b"attach" \
                and os.path.basename(args[0].decode(errors="replace")) == "claude":
            found.append((int(entry.name), args[2].decode(errors="replace")))
    return found


def _now():
    """Seconds since boot, suspended time included: `time.monotonic()` stops
    while the machine sleeps, which would stretch the wait for a new tab."""
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def viewers(job, sid="", name="", proc="/proc", running=None, rivals=()):
    """Pids of `claude attach` processes that show this background session.

    `claude attach` takes the job id, the session id or part of the name, and
    a person attaching by hand may have used any of them: every one counts,
    because a missed viewer means a second window on the same conversation.
    `running` is `attaches()` when the caller has it already; `rivals` are the
    names of the other background sessions.
    """
    return _viewing("is", job, sid, name, proc, running, rivals)


def doubtful(job, sid="", name="", proc="/proc", running=None, rivals=()):
    """Pids of `claude attach` processes that may show this session.

    Part of a name that another background session has too fits both. Which
    one the person meant cannot be told, and neither can the one it meant be
    ruled out, so a session such a viewer fits is never attached to: a window
    raised for it could be the wrong one, a new tab a second copy.
    """
    return _viewing("may", job, sid, name, proc, running, rivals)


def _viewing(how, job, sid, name, proc, running, rivals):
    running = attaches(proc) if running is None else running
    return [pid for pid, token in running if _match(token, job, sid, name, rivals) == how]


def _match(token, job, sid, name, rivals):
    """How `claude attach <token>` relates to this session: "is" when it can
    only mean this one, "may" when it is part of a name another session has
    too, "" when it is not this session."""
    text = lambda v: v.lower() if isinstance(v, str) else ""
    token, sid, name = token.strip().lower(), text(sid), text(name)
    if not token:
        return ""
    if token == job or (len(token) >= 4 and job.startswith(token)):
        return "is"
    if len(token) >= 8 and sid.startswith(token):
        return "is"
    if token not in name:
        return ""
    return "may" if any(token in text(other) for other in rivals) else "is"


def attach(job, sid="", name="", proc="/proc", rivals=()):
    """Put a background session in front of the user, attaching it only once.

    Someone is already attached: their window is raised. Nobody is: a new tab
    attaches. A tab opened a moment ago shows no process yet, and a second
    click inside that moment waits instead of opening another. The whole
    thing runs one click at a time, because the server takes clicks on
    threads and two that both found nobody attached would both open a tab.
    """
    if not is_job(job):
        return {"ok": False, "reason": "no background job id is known for this session"}
    with _ATTACH:
        running = attaches(proc)
        seen = viewers(job, sid, name, proc, running, rivals)
        for pid in seen:
            route = route_for(pid)
            if route:
                return _follow(route)
        if seen:
            return {"ok": False, "reason": "already attached, and no window showing it can be raised"}
        if doubtful(job, sid, name, proc, running, rivals):
            return {"ok": False, "reason": MAY_BE_SHOWN}
        now = _now()
        for old in [j for j, until in _ATTACHING.items() if now >= until]:
            del _ATTACHING[old]
        if job in _ATTACHING:
            return {"ok": True, "did": "opening"}
        route = choose_route(tty="", ancestry=[], tmux="", panes=[], clients=[],
                             konsole=[], job=job)
        done = _follow(route)
        if done["ok"]:
            # A tab asked of a running WezTerm comes back with its pane; one
            # that started WezTerm is not confirmed, and its claude has no
            # process until the window is up.
            _ATTACHING[job] = _now() + (ATTACH_GRACE if done.get("pane") else COLD_START_GRACE)
        return done


def _raise(window_pid, ran):
    if not window_pid:
        return
    for wpid, wid in _x_windows():
        if wpid == window_pid:
            _run(["wmctrl", "-ia", wid])
            ran.append(f"wmctrl -ia {wid}")
            return


def open_tab(argv, cwd=None):
    """Run argv in a new WezTerm tab and put it in front. Returns a report.

    The tab goes into the first window WezTerm lists; with no WezTerm running
    a new one is started. The command runs in WezTerm's environment, not the
    caller's, so nothing of the server's leaks into it.
    """
    ran = []
    gui = _pid_of_command("wezterm-gui")
    if not gui:
        cmd = ["wezterm", "start"] + (["--cwd", cwd] if cwd else []) + ["--"] + argv
        # Started from the server, the window would share its cgroup and be
        # killed with it; the window that is already there is asked instead.
        cmd = scope.wrap(cmd, "wezterm window")
        try:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            return {"ok": False, "reason": f"wezterm: {e}", "ran": ran}
        ran.append(" ".join(cmd))
        return {"ok": True, "ran": ran}
    spawn = ["wezterm", "cli", "--no-auto-start", "spawn"]
    listed = _run(["wezterm", "cli", "--no-auto-start", "list", "--format", "json"])
    try:
        windows = [p["window_id"] for p in json.loads(listed.stdout)] if listed else []
    except (ValueError, KeyError, TypeError):
        windows = []
    spawn += ["--window-id", str(windows[0])] if windows else ["--new-window"]
    if cwd:
        spawn += ["--cwd", cwd]
    spawn += ["--"] + argv
    res = _run(spawn)
    ran.append(" ".join(spawn))
    if res is None or res.returncode != 0:
        why = (res.stderr.strip() if res else "") or "wezterm cli spawn failed"
        return {"ok": False, "reason": why, "ran": ran}
    pane = res.stdout.strip()
    if pane.isdigit():
        _run(["wezterm", "cli", "--no-auto-start", "activate-pane", "--pane-id", pane])
        ran.append(f"wezterm cli activate-pane --pane-id {pane}")
    _raise(gui, ran)
    return {"ok": True, "ran": ran, "pane": pane}


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
