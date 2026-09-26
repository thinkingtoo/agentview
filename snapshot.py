#!/usr/bin/env python3
"""Remember where every Claude session lives, and put them back after a reboot.

tmux-resurrect brings the tmux layout back, but every pane that ran Claude
comes back as a bare shell, the WezTerm windows do not come back at all, and
a session resumed by hand gets a new name. This keeps one more record next to
resurrect's: which conversation ran in which pane or tab, with which flags and
under which name, and which WezTerm window showed which tmux session.

    snapshot.py save              one snapshot, skipped if nothing changed
    snapshot.py restore [--login] [--dry-run]
    snapshot.py show
    snapshot.py tabs              name every WezTerm tab after what it shows

`save` runs on a timer. `restore --login` runs once per boot from the desktop
autostart and restores the last snapshot taken before this boot. Nothing is
ever started twice: a conversation already running is skipped.
"""
import fcntl
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from providers import claude, registry  # noqa: E402

SHELLS = {"bash", "zsh", "fish", "sh", "dash"}
KEEP = 60                       # snapshots on disk; saves are skipped when nothing moved
OFFER = 24 * 3600               # the reopen button's offer after a reboot
CRASH_OFFER = 3600              # ...and after a WezTerm crash, whose sessions the closed list keeps
# Arguments that pick *which* conversation to open. A restore supplies its own.
RESUME_ARGS = {"--resume", "-r", "--session-id"}
RESUME_FLAGS = {"--continue", "-c", "--fork-session"}


def store():
    return claude.claude_dir() / "agentview" / "snapshots"


def boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


# ------------------------------------------------------------------ capture

def parse_flags(argv):
    """The launch options worth repeating, from a running claude's argv.

    Drops the conversation selector (a restore brings its own) and anything
    with whitespace in it, which is an opening prompt, not an option.
    """
    out, skip = [], False
    for tok in argv[1:]:
        if skip:
            skip = False
            continue
        if tok in RESUME_ARGS:
            skip = True
            continue
        if tok in RESUME_FLAGS or tok.split("=", 1)[0] in RESUME_ARGS:
            continue
        if any(c.isspace() for c in tok):
            continue
        out.append(tok)
    return " ".join(shlex.quote(t) for t in out)


def build(peers, tmux_panes, wez_panes, tmux_clients, now, boot, terminals=()):
    """The snapshot, from facts already gathered. Pure, so tests can reach it.

    peers:        [{sessionId, name, cwd, tty, argv, tmux_pane}]
    tmux_panes:   [{pane_id, session, window, window_name, layout, pane, cwd}]
    wez_panes:    [{window_id, tab_id, pane_id, tty, cwd}]  in WezTerm's order
    tmux_clients: [{tty, session}]
    terminals:    pids of the WezTerm GUIs running, so a crash can be told apart
    """
    by_pane = {p["pane_id"]: p for p in tmux_panes}
    sessions = []
    for peer in peers:
        rec = {"sessionId": peer["sessionId"], "name": peer.get("name") or "",
               "cwd": peer.get("cwd") or "",
               "flags": parse_flags(peer.get("argv") or ["claude"])}
        if peer.get("pid"):
            rec["pid"] = peer["pid"]
        pane = by_pane.get(peer.get("tmux_pane") or "")
        if pane:
            rec["tmux"] = {"session": pane["session"], "window": pane["window"],
                           "pane": pane["pane"]}
        sessions.append(rec)

    in_tmux = {(s["tmux"]["session"], s["tmux"]["window"], s["tmux"]["pane"]): s
               for s in sessions if "tmux" in s}
    hosting = {s["tmux"]["session"] for s in sessions if "tmux" in s}
    tmux = []
    for name in sorted(hosting, key=_natural):
        windows = {}
        for p in tmux_panes:
            if p["session"] != name:
                continue
            w = windows.setdefault(p["window"], {"index": p["window"],
                                                 "name": p["window_name"],
                                                 "layout": p["layout"], "panes": []})
            hit = in_tmux.get((name, p["window"], p["pane"]))
            w["panes"].append({"index": p["pane"], "cwd": p["cwd"],
                               "sessionId": hit["sessionId"] if hit else ""})
        for w in windows.values():
            w["panes"].sort(key=lambda x: x["index"])
        tmux.append({"name": name,
                     "windows": sorted(windows.values(), key=lambda w: w["index"])})

    client_at = {c["tty"]: c["session"] for c in tmux_clients}
    direct_at = {p["tty"]: p for p in peers if p.get("tty") and not by_pane.get(p.get("tmux_pane") or "")}
    windows, seen_tabs = {}, set()
    for wp in wez_panes:
        # One entry per tab: the first pane WezTerm lists for it.
        if wp["tab_id"] in seen_tabs:
            continue
        seen_tabs.add(wp["tab_id"])
        if wp["tty"] in client_at:
            tab = {"kind": "tmux", "session": client_at[wp["tty"]]}
        elif wp["tty"] in direct_at:
            tab = {"kind": "claude", "sessionId": direct_at[wp["tty"]]["sessionId"]}
        else:
            tab = {"kind": "shell", "cwd": wp["cwd"]}
        windows.setdefault(wp["window_id"], []).append(tab)
    wezterm = [{"tabs": tabs} for _, tabs in sorted(windows.items())]

    return {"version": 2, "taken_at": now, "boot_id": boot,
            "sessions": sessions, "tmux": tmux, "wezterm": wezterm,
            "terminals": sorted(terminals)}


def _natural(name):
    return (0, int(name), "") if name.isdigit() else (1, 0, name)


def _run(argv, timeout=5):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _environ_var(pid, key):
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return ""
    for item in raw.split(b"\0"):
        k, _, v = item.partition(b"=")
        if k.decode(errors="replace") == key:
            return v.decode(errors="replace")
    return ""


def _argv(pid):
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [a.decode(errors="replace") for a in raw.split(b"\0") if a]


def _tty(pid):
    try:
        return os.readlink(f"/proc/{pid}/fd/0")
    except OSError:
        return ""


def live_peers():
    """Interactive sessions at a terminal. Routines and `-p` runs are not ours to restart."""
    cfg = claude.claude_dir()
    out = []
    for rec in registry.live(cfg):
        if rec.get("entrypoint") != "cli":
            continue
        if rec.get("kind") != "interactive" or claude.routine_of(rec, cfg):
            continue
        pid = rec.get("pid")
        out.append({"sessionId": rec.get("sessionId") or "", "name": rec.get("name") or "",
                    "cwd": rec.get("cwd") or "", "pid": pid, "tty": _tty(pid),
                    "argv": _argv(pid), "tmux_pane": _environ_var(pid, "TMUX_PANE")})
    return [p for p in out if p["sessionId"]]


TMUX_FMT = "\t".join(["#{pane_id}", "#{session_name}", "#{window_index}", "#{window_name}",
                      "#{window_layout}", "#{pane_index}", "#{pane_current_path}",
                      "#{pane_current_command}", "#{pane_pid}"])


def tmux_panes():
    res = _run(["tmux", "list-panes", "-a", "-F", TMUX_FMT])
    if not res or res.returncode != 0:
        return []
    out = []
    for line in res.stdout.splitlines():
        f = line.split("\t")
        if len(f) != 9:
            continue
        out.append({"pane_id": f[0], "session": f[1], "window": int(f[2]),
                    "window_name": f[3], "layout": f[4], "pane": int(f[5]),
                    "cwd": f[6], "command": f[7], "pid": int(f[8] or 0)})
    return out


def tmux_clients():
    res = _run(["tmux", "list-clients", "-F", "#{client_tty}\t#{client_session}"])
    if not res or res.returncode != 0:
        return []
    return [{"tty": t, "session": s} for t, _, s in
            (line.partition("\t") for line in res.stdout.splitlines()) if t]


# Without --no-auto-start, `wezterm cli` run while no WezTerm window is open
# quietly starts a headless wezterm-mux-server and talks to that. A restore at
# login then put every tab in it, alive and attached, with nothing on screen
# (2026-09-24). With the flag the call fails instead, and the caller knows the
# GUI still has to be started.
WEZ_CLI = ["wezterm", "cli", "--no-auto-start"]


def _wez_list(sock=None):
    env = None
    if sock:
        env = {k: v for k, v in os.environ.items() if k != "WEZTERM_PANE"}
        env["WEZTERM_UNIX_SOCKET"] = str(sock)
    try:
        res = subprocess.run(WEZ_CLI + ["list", "--format", "json"], capture_output=True,
                             text=True, timeout=5, env=env)
    except (OSError, subprocess.SubprocessError):
        return []
    if res.returncode != 0:
        return []
    try:
        panes = json.loads(res.stdout)
    except ValueError:
        return []
    out = []
    for p in panes:
        cwd = p.get("cwd") or ""
        if cwd.startswith("file://"):
            cwd = "/" + cwd[len("file://"):].partition("/")[2]
        out.append({"window_id": p["window_id"], "tab_id": p["tab_id"],
                    "pane_id": p["pane_id"], "tty": p.get("tty_name") or "", "cwd": cwd})
    return out


def wez_panes():
    """The panes of the WezTerm instance `wezterm cli` talks to by default:
    the one a spawn lands in."""
    return _wez_list()


def _wez_sockets():
    run = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "wezterm"
    socks = []
    for sock in sorted(run.glob("gui-sock-*")):
        pid = sock.name.rpartition("-")[2]
        if pid.isdigit() and Path(f"/proc/{pid}").exists():
            socks.append(sock)
    if (run / "sock").exists():
        socks.append(run / "sock")
    return socks


def wez_guis():
    """Pids of the WezTerm GUIs running now."""
    pids = [s.name.rpartition("-")[2] for s in _wez_sockets() if s.name.startswith("gui-sock-")]
    return sorted(int(p) for p in pids)


def every_wez_pane():
    """The panes of every WezTerm running, for the snapshot. With two open,
    `wezterm cli list` answers from one of them, and the tabs in the other
    were missing from every snapshot until the reboot lost them (2026-09-24).
    Window and tab ids restart at 0 in each instance, so they are prefixed."""
    out, ttys = [], set()
    for n, sock in enumerate(_wez_sockets()):
        for p in _wez_list(sock):
            if p["tty"] and p["tty"] in ttys:
                continue
            ttys.add(p["tty"])
            out.append({**p, "window_id": f"{n}:{p['window_id']}", "tab_id": f"{n}:{p['tab_id']}"})
    return out


def gather():
    return build(live_peers(), tmux_panes(), every_wez_pane(), tmux_clients(),
                 int(time.time()), boot_id(), wez_guis())


def _comparable(snap):
    return {k: v for k, v in snap.items() if k != "taken_at"}


def save(snap=None):
    """Write a snapshot unless it has no sessions or matches the last one."""
    snap = snap or gather()
    if not snap["sessions"]:
        return None                       # a machine going down, or one just up
    d = store()
    d.mkdir(parents=True, exist_ok=True)
    files = sorted(d.glob("*.json"))
    if files:
        try:
            if _comparable(json.loads(files[-1].read_text())) == _comparable(snap):
                return None
        except (OSError, ValueError):
            pass
    path = d / time.strftime("%Y%m%dT%H%M%S.json", time.localtime(snap["taken_at"]))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, indent=1))
    os.replace(tmp, path)
    for old in sorted(d.glob("*.json"))[:-KEEP]:
        old.unlink(missing_ok=True)
    return path


def load_all():
    out = []
    for f in sorted(store().glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return out


def choose(snaps, boot, terminals=()):
    """The last state before the sessions lost their terminal: the last
    snapshot of the previous boot, or of a WezTerm that is no longer running.
    A crashed WezTerm kills the sessions in its tabs as surely as a reboot."""
    alive = set(terminals)
    earlier = [s for s in snaps if s.get("boot_id") != boot
               or set(s.get("terminals") or ()) - alive]
    return max(earlier, key=lambda s: s["taken_at"]) if earlier else None


def boot_time():
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                return int(line.split()[1])
    except OSError:
        pass
    return 0


def still_offered(snap, booted, now):
    """How long the reopen button offers a lost state, from when it was lost:
    the reboot for an earlier boot's snapshot, the snapshot itself for a
    crashed WezTerm. Thursday's crash still on the button on Friday morning read as a warning
    that rebooting now would lose something (2026-09-25). A crash gets an hour:
    its sessions stay on the closed list, one click each, for the rest of the
    boot. An earlier boot's are on no other list, so they get the day."""
    if not snap:
        return False
    if snap["taken_at"] > booted:
        return now - snap["taken_at"] < CRASH_OFFER
    return now - booted < OFFER


def latest(snaps, boot):
    """The newest snapshot of this boot: what a shutdown now would restore."""
    mine = [s for s in snaps if s.get("boot_id") == boot]
    return max(mine, key=lambda s: s["taken_at"]) if mine else None


def missing(snap, live_ids):
    return [s for s in (snap or {}).get("sessions", []) if s["sessionId"] not in live_ids]


def closed(snaps, boot, live_ids, skip=(), live=()):
    """Sessions this boot had running that no longer run, newest first.

    Each comes back as it was last seen: its name, directory and flags from
    the newest snapshot that still had it. The earlier boot's sessions are
    the reopen button's, so they are not repeated here.

    `live` is what runs now, with each process's start time. A conversation
    whose own process is still running was replaced in its terminal (/clear,
    /resume), not closed. Snapshots older than the pid field match on name
    and directory, and only a process that started before the conversation
    was last seen counts: names are handed out again during the day.
    """
    last = {}
    for snap in sorted(snaps, key=lambda s: s.get("taken_at", 0)):
        if snap.get("boot_id") != boot:
            continue
        for rec in snap.get("sessions", []):
            last[rec["sessionId"]] = {**rec, "last_seen": snap["taken_at"]}

    def replaced(rec):
        for proc in live:
            if (proc.get("started") or 0) > rec["last_seen"]:
                continue
            if rec.get("pid"):
                if proc.get("pid") == rec["pid"]:
                    return True
            elif proc.get("name") and (proc["name"], proc.get("cwd")) == (rec.get("name"), rec.get("cwd")):
                return True
        return False

    gone = [r for sid, r in last.items()
            if sid not in live_ids and sid not in skip and not replaced(r)]
    return sorted(gone, key=lambda r: -r["last_seen"])


def started_at(pid):
    """When a process started, in epoch seconds, or 0."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            ticks = int(fh.read().rsplit(")", 1)[1].split()[19])
        with open("/proc/stat", encoding="utf-8") as fh:
            btime = next(int(l.split()[1]) for l in fh if l.startswith("btime"))
        return btime + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        return 0


def dismissed_path():
    return store().parent / "dismissed.json"


def dismissed():
    try:
        return set(json.loads(dismissed_path().read_text()))
    except (OSError, ValueError, TypeError):
        return set()


def dismiss(session_id):
    """Take a closed session off the list: you closed that one on purpose."""
    ids = dismissed() | {session_id}
    path = dismissed_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(ids)))
    os.replace(tmp, path)


def revive(rec):
    """Resume a closed session in a new WezTerm tab, under its old name."""
    import jump
    if not os.path.isdir(rec.get("cwd") or ""):
        return {"ok": False, "reason": f"its directory is gone: {rec.get('cwd')}"}
    seed_name(rec["sessionId"], rec.get("name") or "")
    return jump.open_tab(shlex.split(_claude_cmd(rec)), cwd=rec["cwd"])


def unseen_tmux(peers, panes, clients):
    """tmux sessions running a Claude session that no terminal is attached to.
    Taken from what runs now, so a snapshot that never saw the tab (or a
    session resumed into a tmux session of its own) still gets one."""
    session_of = {p["pane_id"]: p["session"] for p in panes}
    attached = {c["session"] for c in clients}
    hosting = {session_of[p["tmux_pane"]] for p in peers if p.get("tmux_pane") in session_of}
    return sorted(hosting - attached, key=_natural)


def missing_tabs(snap, clients):
    """tmux sessions a WezTerm tab showed that no terminal shows now. The
    sessions inside can all be running while you see none of them."""
    attached = {c["session"] for c in clients}
    return [t["session"] for w in (snap or {}).get("wezterm", []) for t in w["tabs"]
            if t["kind"] == "tmux" and t["session"] not in attached]


# ------------------------------------------------------------------ restore

def pane_plan(saved_panes, current, live_ids):
    """What to do with each saved pane of one tmux window. Pure.

    current: {pane_index: {"command", "busy"}} for the window as it is now,
    where busy means the pane's shell has children. Returns a list of
    ("resume", index, sessionId) | ("split", cwd, sessionId|"").
    A pane is only reused when it holds an idle shell -- never on top of
    something you started yourself.
    """
    steps = []
    for p in saved_panes:
        sid = p["sessionId"]
        now = current.get(p["index"])
        if now is None:
            steps.append(("split", p["cwd"], "" if sid in live_ids else sid))
        elif sid and sid not in live_ids and now["command"] in SHELLS and not now["busy"]:
            steps.append(("resume", p["index"], sid))
    return steps


def seed_name(session_id, name):
    """Tell cc-agent-names what this conversation was called before, so the
    resume gets its name back instead of a fresh one."""
    state = claude.claude_dir() / "agent-names"
    if not name or not state.is_dir():
        return
    path = state / "sessions.json"
    with open(state / "pick.lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = {}
        data[session_id] = {"name": name, "last_used": int(time.time())}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
        os.replace(tmp, path)


def wait_named(session_id, timeout=20):
    """Resumes go one at a time: the name picker is first-come, first-served."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = registry.by_sid(session_id, claude.claude_dir())
        if rec and rec.get("name") and registry.is_live(rec):
            return rec["name"]
        time.sleep(0.5)
    return ""


def _children(pid):
    try:
        return bool(Path(f"/proc/{pid}/task/{pid}/children").read_text().split())
    except OSError:
        return False


def _wait_tmux_settled(max_wait=90):
    """tmux-continuum restores on server start and takes a while; wait for it
    so a pane is not built twice."""
    if _run(["tmux", "has-session"]) is None or _run(["tmux", "has-session"]).returncode != 0:
        _run(["tmux", "new-session", "-d", "-s", "_agentview_boot"])
        started = True
    else:
        started = False
    last, stable_since, deadline = None, time.time(), time.time() + max_wait
    while time.time() < deadline:
        res = _run(["tmux", "list-panes", "-a", "-F", "#{pane_id}"])
        count = len(res.stdout.split()) if res and res.returncode == 0 else 0
        if count != last:
            last, stable_since = count, time.time()
        elif time.time() - stable_since > 6:
            break
        time.sleep(1)
    if started:
        _run(["tmux", "kill-session", "-t", "=_agentview_boot"])


def _claude_cmd(rec):
    return f"claude --resume {rec['sessionId']} {rec.get('flags') or ''}".strip()


def restore(snap, dry=False, log=print):
    live_ids = {p["sessionId"] for p in live_peers()}
    todo = {s["sessionId"]: s for s in missing(snap, live_ids)}
    if not todo and not missing_tabs(snap, tmux_clients()) and not unseen_tmux(
            live_peers(), tmux_panes(), tmux_clients()):
        log("nothing to restore: every session and tab in the snapshot is open")
        return 0
    started = 0

    def launch(rec, where, argv):
        nonlocal started
        log(f"resume  {rec['name'] or rec['sessionId'][:8]:28} {where}")
        if dry:
            return
        seed_name(rec["sessionId"], rec["name"])
        res = _run(argv)
        if res is None or res.returncode != 0:
            log(f"  failed: {res.stderr.strip() if res else 'no tmux/wezterm'}")
            return
        started += 1
        todo.pop(rec["sessionId"], None)
        got = wait_named(rec["sessionId"])
        if got and rec["name"] and got != rec["name"]:
            log(f"  came back as {got} (was {rec['name']})")

    if not dry:
        _wait_tmux_settled()

    # tmux first: the WezTerm tabs attach to these sessions.
    for ts in snap.get("tmux", []):
        name = ts["name"]
        exists = _run(["tmux", "has-session", "-t", f"={name}"])
        exists = bool(exists and exists.returncode == 0)
        for w in ts["windows"]:
            panes = {p["pane"]: p for p in tmux_panes()
                     if p["session"] == name and p["window"] == w["index"]}
            if not exists or not panes:
                first = w["panes"][0]
                rec = todo.get(first["sessionId"])
                cmd = [_claude_cmd(rec)] if rec else []
                log(f"create  tmux {name}:{w['index']}")
                if not dry:
                    base = (["tmux", "new-session", "-d", "-s", name] if not exists
                            else ["tmux", "new-window", "-d", "-t", f"={name}:{w['index']}"])
                    if rec:
                        seed_name(rec["sessionId"], rec["name"])
                    _run(base + ["-c", first["cwd"]] + cmd)
                    if not exists:
                        _run(["tmux", "move-window", "-s", f"={name}:", "-t", f"={name}:{w['index']}"])
                    exists = True
                    if rec:
                        started += 1
                        todo.pop(rec["sessionId"], None)
                        wait_named(rec["sessionId"])
                panes = {p["pane"]: p for p in tmux_panes()
                         if p["session"] == name and p["window"] == w["index"]}
                if not panes and dry:
                    panes = {first["index"]: {"command": "bash", "pid": 0}}
            current = {i: {"command": p["command"], "busy": _children(p["pid"])}
                       for i, p in panes.items()}
            live_now = set(live_ids) | (set(snap_ids(snap)) - set(todo))
            target = f"={name}:{w['index']}"
            for step in pane_plan(w["panes"], current, live_now):
                if step[0] == "resume":
                    rec = todo[step[2]]
                    launch(rec, f"tmux {name}:{w['index']}.{step[1]}",
                           ["tmux", "respawn-pane", "-k", "-t", f"{target}.{step[1]}",
                            "-c", rec["cwd"], _claude_cmd(rec)])
                else:
                    _, cwd, sid = step
                    rec = todo.get(sid)
                    argv = ["tmux", "split-window", "-d", "-t", target, "-c", cwd]
                    if rec:
                        launch(rec, f"tmux {name}:{w['index']} (new pane)", argv + [_claude_cmd(rec)])
                    else:
                        log(f"split   tmux {name}:{w['index']} {cwd}")
                        if not dry:
                            _run(argv)
            if not dry and len(w["panes"]) > 1:
                _run(["tmux", "select-layout", "-t", target, w["layout"]])

    # WezTerm: the windows and tabs as they were.
    clients = tmux_clients()
    attached = {c["session"] for c in clients}
    # A mux server with no window also answers `wezterm cli`: only a running
    # wezterm-gui means a spawned tab lands somewhere you can see it.
    gui = _gui_running()
    panes_now = wez_panes() if gui else []
    window_of_tty = {p["tty"]: p["window_id"] for p in panes_now}
    window_of_session = {c["session"]: window_of_tty.get(c["tty"]) for c in clients}
    live_tab_window = {}
    for rec in live_peers():
        if rec["tty"] in window_of_tty:
            live_tab_window[rec["sessionId"]] = window_of_tty[rec["tty"]]
    for win in snap.get("wezterm", []):
        # A window that is partly still open gets its missing tabs back.
        window_id = next((w for w in (
            window_of_session.get(t.get("session")) if t["kind"] == "tmux"
            else live_tab_window.get(t.get("sessionId")) for t in win["tabs"])
            if w is not None), None)
        for tab in win["tabs"]:
            if tab["kind"] == "tmux":
                if tab["session"] in attached:
                    continue
                argv, cwd, what = ["tmux", "attach", "-t", f"={tab['session']}"], None, f"tmux {tab['session']}"
                rec = None
            elif tab["kind"] == "claude":
                rec = todo.get(tab["sessionId"])
                if not rec:
                    continue
                argv, cwd, what = shlex.split(_claude_cmd(rec)), rec["cwd"], "wezterm tab"
            else:
                rec, argv, cwd, what = None, [], tab["cwd"], f"shell {tab['cwd']}"
            if dry:
                (launch(rec, what, []) if rec else log(f"tab     {what}"))
                continue
            if not gui:
                window_id, gui = _start_gui(cwd, argv, rec), True
                if rec:
                    started += 1
                    todo.pop(rec["sessionId"], None)
                    wait_named(rec["sessionId"])
                else:
                    log(f"tab     {what} (new WezTerm)")
                continue
            spawn = WEZ_CLI + ["spawn"]
            spawn += ["--window-id", str(window_id)] if window_id is not None else ["--new-window"]
            if cwd:
                spawn += ["--cwd", cwd]
            if argv:
                spawn += ["--"] + argv
            if rec:
                seed_name(rec["sessionId"], rec["name"])
            res = _run(spawn)
            if res and res.returncode == 0 and window_id is None:
                window_id = _window_of(res.stdout.strip())
            if rec:
                if res and res.returncode == 0:
                    started += 1
                    todo.pop(rec["sessionId"], None)
                    log(f"resume  {rec['name'] or rec['sessionId'][:8]:28} {what}")
                    wait_named(rec["sessionId"])
            else:
                log(f"tab     {what}")

    # Anything left had no known place: its own tmux session, as before.
    for rec in list(todo.values()):
        launch(rec, f"tmux (own session) {rec['cwd']}",
               ["tmux", "new-session", "-d", "-s", _tmux_name(rec), "-c", rec["cwd"], _claude_cmd(rec)])

    # Every tmux session with Claude in it and no terminal gets a tab, in one
    # window, so nothing is running where you cannot see it.
    if not dry:
        time.sleep(1)
    extra = None
    for name in unseen_tmux(live_peers(), tmux_panes(), tmux_clients()):
        argv = ["tmux", "attach", "-t", f"={name}"]
        log(f"tab     tmux {name}")
        if dry:
            continue
        if not _gui_running():
            extra = _start_gui(None, argv, None)
            continue
        spawn = WEZ_CLI + ["spawn"] + (["--window-id", str(extra)] if extra is not None
                                      else ["--new-window"]) + ["--"] + argv
        res = _run(spawn)
        if res and res.returncode == 0 and extra is None:
            extra = _window_of(res.stdout.strip())
    log(f"{'would resume' if dry else 'resumed'} {started if not dry else len(missing(snap, live_ids))} session(s)")
    return started


def snap_ids(snap):
    return [s["sessionId"] for s in snap.get("sessions", [])]


def _tmux_name(rec):
    import re
    base = re.sub(r"[^A-Za-z0-9_-]", "_", rec["name"] or rec["sessionId"][:8])[:40]
    name, n = base, 2
    while (r := _run(["tmux", "has-session", "-t", f"={name}"])) and r.returncode == 0:
        name, n = f"{base}-{n}", n + 1
    return name


def _window_of(pane_id):
    for p in wez_panes():
        if str(p["pane_id"]) == pane_id:
            return p["window_id"]
    return None


def _gui_running():
    res = _run(["pgrep", "-x", "wezterm-gui"])
    return bool(res and res.returncode == 0)


def _start_gui(cwd, argv, rec):
    if rec:
        seed_name(rec["sessionId"], rec["name"])
    cmd = ["wezterm", "start"] + (["--cwd", cwd] if cwd else []) + (["--"] + argv if argv else [])
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + 20
    while time.time() < deadline:
        panes = wez_panes() if _gui_running() else []
        if panes:
            return panes[-1]["window_id"]
        time.sleep(0.5)
    return None


# ------------------------------------------------------------- tab titles

TITLE_MAX = 36      # matches tab_max_width in ~/.wezterm.lua


def _clip(text, n):
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def tab_title(members, project):
    """The best short name for a tab. Pure.

    members: the Claude sessions the tab shows, in pane order, as
    {name, title, own}; `own` is your text for that session from agentview,
    which beats Claude's generated title. One session reads "Name · topic";
    several read "project · Name, Name +n"; none reads the project.
    """
    if not members:
        return project or ""
    if len(members) == 1:
        m = members[0]
        topic = m.get("own") or m.get("title") or project or ""
        head = m.get("name") or ""
        if not head:
            return _clip(topic, TITLE_MAX)
        return _clip(f"{head} · {topic}", TITLE_MAX) if topic else head
    names = [m.get("name") or "?" for m in members]
    shown, rest = names[:2], len(names) - 2
    tail = ", ".join(shown) + (f" +{rest}" if rest > 0 else "")
    if not project:
        return _clip(tail, TITLE_MAX)
    full = f"{project} · {tail}"
    if len(full) > TITLE_MAX:
        # "client › project" is the dashboard's label; the names matter more here.
        full = f"{project.split(' › ')[-1]} · {tail}"
    return _clip(full, TITLE_MAX)


def _tab_state():
    return store().parent / "tab-titles.json"


def name_tabs(log=lambda *_: None):
    """Give every WezTerm tab that hosts Claude (directly or through tmux) its
    best name. A title you typed yourself is never replaced: only a tab still
    carrying the last title set here, or none, is touched."""
    import fleet
    res = _run(WEZ_CLI + ["list", "--format", "json"])
    if not res or res.returncode != 0:
        return
    try:
        raw = json.loads(res.stdout)
    except ValueError:
        return
    gui = _run(["pgrep", "-x", "wezterm-gui"])
    gui = gui.stdout.split()[0] if gui and gui.returncode == 0 and gui.stdout.split() else ""
    try:
        state = json.loads(_tab_state().read_text())
    except (OSError, ValueError):
        state = {}
    if state.get("gui") != gui:
        state = {"gui": gui, "tabs": {}}

    cfg = fleet.read_config()
    shelves = fleet.config()
    names, assign, lines = cfg.get("names", {}), cfg.get("assign", {}), cfg.get("lines", {})

    def label(sid, cwd):
        proj = assign.get(f"claude:{sid}") if sid else None
        proj = proj or fleet.resolve_project(cwd, shelves) or ""
        return names.get(proj, proj)

    cdir = claude.claude_dir()
    peers = {}
    for p in live_peers():
        t = claude.transcript_for(p["sessionId"], p["cwd"], cdir)
        title = claude.scan_cached(t)["title"] if t else ""
        peers[p["sessionId"]] = {**p, "title": title,
                                 "own": lines.get(f"claude:{p['sessionId']}", "")}
    by_tty = {p["tty"]: p for p in peers.values() if p["tty"]}
    by_pane = {p["tmux_pane"]: p for p in peers.values() if p["tmux_pane"]}
    clients = {c["tty"]: c["session"] for c in tmux_clients()}
    panes = tmux_panes()

    seen = set()
    for wp in raw:
        tab = str(wp["tab_id"])
        if tab in seen:
            continue
        seen.add(tab)
        tty = wp.get("tty_name") or ""
        if tty in clients:
            sess = clients[tty]
            here = [p for p in panes if p["session"] == sess]
            members = [by_pane[p["pane_id"]] for p in here if p["pane_id"] in by_pane]
            cwd = members[0]["cwd"] if members else (here[0]["cwd"] if here else "")
            projects = {label(m["sessionId"], m["cwd"]) for m in members} or {label("", cwd)}
            heads = {x.split(" › ")[0] for x in projects}
            common = projects.pop() if len(projects) == 1 else (heads.pop() if len(heads) == 1 else "")
            want = tab_title(members, common)
        elif tty in by_tty:
            m = by_tty[tty]
            want = tab_title([m], label(m["sessionId"], m["cwd"]))
        else:
            continue
        have = wp.get("tab_title") or ""
        ours = state["tabs"].get(tab, "")
        if have and have != ours:
            continue                      # you named this one yourself
        if want and want != have:
            _run(WEZ_CLI + ["set-tab-title", "--pane-id", str(wp["pane_id"]), want])
            log(f"tab {tab}: {want}")
        state["tabs"][tab] = want
    try:
        _tab_state().parent.mkdir(parents=True, exist_ok=True)
        _tab_state().write_text(json.dumps(state))
    except OSError:
        pass


def _marker():
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / f"agentview-restored-{boot_id()}"


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "show"
    if cmd == "save":
        path = save()
        if path:
            print(path)
        name_tabs()
        return 0
    if cmd == "tabs":
        name_tabs(log=print)
        return 0
    snap = choose(load_all(), boot_id(), wez_guis())
    if cmd == "show":
        if not snap:
            print("no snapshot from an earlier boot")
            return 0
        live = {p["sessionId"] for p in live_peers()}
        print(f"taken {time.strftime('%Y-%m-%d %H:%M', time.localtime(snap['taken_at']))}: "
              f"{len(snap['sessions'])} session(s), {len(missing(snap, live))} not running")
        for s in snap["sessions"]:
            where = (f"tmux {s['tmux']['session']}:{s['tmux']['window']}.{s['tmux']['pane']}"
                     if "tmux" in s else "wezterm tab")
            flag = " " if s["sessionId"] in live else "*"
            print(f" {flag} {s['name'] or '-':28} {where:16} {s['cwd']}")
        return 0
    if cmd == "restore":
        # Run from inside a Claude session, every resumed session inherited
        # its CLAUDE_CODE_CHILD_SESSION marker: no transcript was saved and
        # none of them registered as a peer (2026-09-24).
        for key in [k for k in os.environ if k == "CLAUDECODE" or k.startswith("CLAUDE_CODE_")]:
            del os.environ[key]
        if not snap:
            print("no snapshot from an earlier boot")
            return 1
        if "--login" in argv:
            if _marker().exists():
                return 0
            _marker().touch()
        restore(snap, dry="--dry-run" in argv)
        if "--dry-run" not in argv:
            time.sleep(3)
            name_tabs(log=print)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
