"""The merge desk's Install items: a tool installed from a git URL that is behind its `main` is on the desk by itself, and a ticked one is installed.

`scan()` reads the `uv tool` receipts (`$UV_TOOL_DIR`, else `$XDG_DATA_HOME/uv/tools`, else
`~/.local/share/uv/tools`, one `<tool>/uv-receipt.toml` each). A receipt is taken for a tool only in
the one shape uv writes for `uv tool install --from git+https://github.com/<owner>/<repo>@<sha>`:
a single requirement with `git = "https://github.com/<owner>/<repo>?rev=<40 hex>"`, owner
`sweatshop-ai` or `tiroir`. Any other shape (a path, a registry, a branch, two requirements, a file
that does not parse) is skipped: it never becomes an item. A tool whose rev is behind `main` gets
one item under "Local installs waiting for you", pinned at `main`'s head as it is then; a tool at
`main`, ahead of it or diverged from it gets none, and an unticked item for a tool that has caught
up is dropped. An item is only re-pinned or dropped while unticked and not under a press.

`press(k)` installs exactly the pinned commit, `uv tool install --reinstall --from
git+<url>@<pinned> <package>`, never "whatever main is now". If main moved since, the install is
still the reviewed one and the next scan makes a new item for the new head. Before it runs it reads
the receipt again: a tool already at the pinned commit is "Already installed", and one whose
installed commit is not behind the pinned one (installed by hand since) is refused, so a press can
never go backwards. A failed `uv` leaves the old install as it was (uv builds and resolves before it
replaces anything: proved against uv 0.13.5 for an unresolvable and an unbuildable source); the
receipt is read again after a failure and the result says whether the old install is still there.
The tool's restart (sheaf: `sheaf stop`, then `sheaf start`) runs only after `uv` has succeeded and
the receipt names the pinned commit.

`uv` and `sheaf` are absolute paths found once in `~/.local/bin` and the system's own folders, and
the child of `uv` gets the system PATH: nothing a session put early on the service's PATH runs. The
restart runs in the environment the hub runs in now (its own `/proc/<pid>/environ`), and `sheaf
start` goes through `systemd-run --user --scope` so the new hub is not left in AgentView's own
cgroup, where restarting AgentView would kill it.

A press is the same press as a Merge: the same lock file (one at a time across processes), the same
`pressing` record before anything is run, the result on the page and an `installed` or `refused`
record after it (`deskwatch.finish`).
"""
import datetime
import os
import pwd
import re
import shutil
import subprocess
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

import desk
import deskfile
import deskwatch

OWNERS = ("sweatshop-ai", "tiroir")
SYSTEM_PATH = desk.SYSTEM_PATH
HOME = pwd.getpwuid(os.getuid()).pw_dir
# ~/.local/bin is searched because that is where uv and sheaf live; it is user-writable, unlike the system folders `gh` is taken from.
SEARCH = ":".join([f"{HOME}/.local/bin", SYSTEM_PATH])
EXES = {name: shutil.which(name, path=SEARCH) for name in ("uv", "sheaf", "systemd-run")}
SCAN_EVERY = 900            # seconds between scans of the receipts
GRACE = 600                 # an install that began and has no result is called interrupted after this
UV_TIMEOUT = 600
CALL_TIMEOUT = 120
SHA = re.compile(r"[0-9a-f]{40}")
GIT = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?\?rev=([0-9a-f]{40})")
_last_scan = [0.0]


class NotInstalled(Exception):
    """The press is refused; the text says why and goes under the item."""


class TakenBack(NotInstalled):
    """The person unticked or replaced the item while the press waited: nothing is written on the page."""


@dataclass
class Tool:
    name: str           # the folder under the tools folder, the key of the item
    package: str        # what `uv tool install` is given after --from
    repo: str           # owner/repo
    rev: str


def tools_dir():
    if os.environ.get("UV_TOOL_DIR"):
        return Path(os.environ["UV_TOOL_DIR"])
    data = os.environ.get("XDG_DATA_HOME")
    return (Path(data) if data and os.path.isabs(data) else Path(HOME) / ".local" / "share") / "uv" / "tools"


def read_receipt(folder):
    """The Tool a receipt describes, or None for any shape this does not know."""
    try:
        with open(folder / "uv-receipt.toml", "rb") as fh:
            data = tomllib.load(fh)
        reqs = data["tool"]["requirements"]
        if not isinstance(reqs, list) or len(reqs) != 1 or not isinstance(reqs[0], dict):
            return None
        req = reqs[0]
        got = GIT.fullmatch(req["git"]) if isinstance(req.get("git"), str) else None
        name = req.get("name")
        if not got or got.group(1) not in OWNERS or not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            return None
        if set(req) - {"name", "git"} or not re.fullmatch(r"[^\s:]+", folder.name):
            return None
        desk.check_repo(f"{got.group(1)}/{got.group(2)}")                # no "." or ".." for a name
        return Tool(folder.name, name, f"{got.group(1)}/{got.group(2)}", got.group(3))
    except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError, desk.Refused):
        return None


def receipts():
    try:
        folders = sorted(p for p in tools_dir().iterdir() if p.is_dir())
    except OSError:
        return []
    return [t for t in map(read_receipt, folders) if t]


def tool_named(name):
    return next((t for t in receipts() if t.name == name), None)


def main_head(repo):
    code, out = deskwatch.gh("api", f"repos/{repo}/commits/main", "--jq", ".sha")
    if code or not SHA.fullmatch(out):
        raise NotInstalled(f"GitHub could not be asked for {repo}'s main: {desk.flatten(out, 120)}")
    return out


def compare(repo, base, head):
    """(status, ahead_by) of `head` against `base`: 'ahead' means head has commits base lacks."""
    code, out = deskwatch.gh("api", f"repos/{repo}/compare/{base}...{head}", "--jq", '.status + " " + (.ahead_by|tostring)')
    status, _, n = out.partition(" ")
    if code or not n.isdigit():
        raise NotInstalled(f"GitHub could not compare {base[:7]} with {head[:7]}: {desk.flatten(out, 120)}")
    return status, int(n)


def item_block(tool, head, behind, when):
    plural = "commit" if behind == 1 else "commits"
    return "\n".join([
        f"- [ ] Install {tool.name}: {tool.repo} is {behind} {plural} behind main",
        "  - Recommendation: found by the scan, no recommendation yet.",
        f"  - Pinned commit: {head}, main of {tool.repo}; installed now: {tool.rev}",
        f"  - Handed over by AgentView's scan, {when}.",
    ]) + "\n"


def last(k):
    return deskwatch.last_event(k)


def scan_tool(tool):
    """Bring the item of one tool in line with GitHub. Raises NotInstalled when GitHub cannot be asked."""
    k = "install:" + tool.name
    head = main_head(tool.repo)
    status, behind = compare(tool.repo, tool.rev, head)
    with deskfile.locked():
        cur = deskwatch.item(k)
        rec = last(k)
        pressing = bool(rec) and rec["event"] == "pressing"
        waiting_on_press = bool(cur) and cur.ticked and (rec is None or rec["event"] != "installed")
        if pressing or waiting_on_press:                        # a ticked item is the watcher's, not the scan's
            return
        if status != "ahead":                                   # at main, or ahead of it, or diverged: nothing to install
            if cur and not cur.ticked:
                deskfile.drop_item(k)
                desk.log("withdrawn", k)
            return
        if cur and not cur.ticked and cur.pinned == head and f"installed now: {tool.rev}" in cur.block:
            return
        block = item_block(tool, head, behind, time.strftime("%Y-%m-%d %H:%M"))
        deskfile.put_item(k, block, section="install")
        desk.log("ready", k, pinned=head, installed=tool.rev, by="AgentView's scan")


def scan():
    for tool in receipts():
        try:
            scan_tool(tool)
        except NotInstalled as why:
            deskwatch.log.error("desk-install-scan", why, key="install:" + tool.name)
        except OSError as why:
            deskwatch.log.error("desk-install-scan", why, key="install:" + tool.name)


def scan_if_due():
    """Called by the watcher's loop; a scan at most every SCAN_EVERY seconds, one at a time with the presses."""
    if _last_scan[0] and time.monotonic() - _last_scan[0] < SCAN_EVERY:
        return
    with deskwatch.press_lock() as got:
        if not got:
            return
        _last_scan[0] = time.monotonic()
        scan()


def run(argv, env, timeout=CALL_TIMEOUT):
    """(exit code, output) of one command, never through a shell; CANNOT when it could not be run."""
    try:
        got = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as err:
        return deskwatch.CANNOT, str(err)
    return got.returncode, (got.stdout + got.stderr).strip()


def exe(name):
    path = EXES.get(name)
    if not path or not os.path.isabs(path):
        raise NotInstalled(f"{name} was not found in " + SEARCH.replace(":", ", "))
    return path


def hub_env(sheaf):
    """The environment the sheaf hub runs in now (read from its own process), so `sheaf stop` and
    `sheaf start` meet the same home, port and runtime folder. Without a readable hub: ours, with no SHEAF_*."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SHEAF_")}
    code, out = run([sheaf, "status"], env)
    pid = re.search(r"\bpid\s+(\d+)", out) if code == 0 else None
    if pid:
        try:
            raw = Path(f"/proc/{pid.group(1)}/environ").read_bytes().decode("utf-8", "replace")
            env = dict(p.split("=", 1) for p in raw.split("\0") if "=" in p)
        except OSError:
            pass
    return env


def restart_sheaf():
    """(ok, what went wrong). `sheaf start` only when `sheaf stop` was fine."""
    sheaf = exe("sheaf")
    env = hub_env(sheaf)
    code, out = run([sheaf, "stop"], env)
    if code:
        return False, f"sheaf stop failed: {desk.flatten(out, 120)}"
    start = [sheaf, "start"]
    scope = EXES.get("systemd-run")
    if not scope or not os.path.isabs(scope):                   # no systemd-run at all: start it where we are
        code, out = run(start, env)
    else:                                                       # never a plain start after a failed scope: it would land in our cgroup
        code, out = run([scope, "--user", "--scope", "--quiet", "--collect", "--", *start], env)
    return (True, "") if not code else (False, f"sheaf start failed: {desk.flatten(out, 120)}")


RESTARTS = {"sheafmd": ("sheaf", restart_sheaf)}


def uv_env():
    return {**os.environ, "PATH": SYSTEM_PATH, "GIT_TERMINAL_PROMPT": "0"}


def old_install(tool):
    """What to say about the install that was there, after a failure."""
    now = tool_named(tool.name)
    if now and now.rev == tool.rev:
        return f"the old install ({tool.rev[:7]}) is still in place"
    return f"could not confirm the old install ({tool.rev[:7]}): the receipt now says {now.rev[:7] if now else 'nothing'}"


def install(k, pinned):
    """Install `pinned` and restart. Returns the text for the page and the log fields; raises NotInstalled."""
    tool = tool_named(k.removeprefix("install:"))
    if tool is None:
        raise NotInstalled(f"no uv receipt of a known shape for {k.removeprefix('install:')} under {tools_dir()}")
    if not SHA.fullmatch(pinned or ""):
        raise NotInstalled("the item names no pinned commit")
    when = time.strftime("%H:%M")
    if tool.rev == pinned:
        return f"Already installed as {pinned[:7]} at {when}", {"sha": pinned, "already": True}
    status, _ = compare(tool.repo, tool.rev, pinned)
    if status != "ahead":
        raise NotInstalled(f"the installed commit changed since the hand-over (now {tool.rev[:7]}, which is not behind {pinned[:7]}); the scan will look again")
    on_main, _ = compare(tool.repo, pinned, main_head(tool.repo))
    if on_main not in ("ahead", "identical"):
        raise NotInstalled(f"the pinned commit {pinned[:7]} is not on {tool.repo}'s main")
    uv = exe("uv")
    now = deskwatch.item(k)                                     # the person may have taken the press back meanwhile
    if not now or not now.ticked or now.pinned != pinned:
        raise TakenBack("the press was taken back before the install")
    code, out = run([uv, "tool", "install", "--reinstall", "--from", f"git+https://github.com/{tool.repo}@{pinned}", tool.package],
                    uv_env(), UV_TIMEOUT)
    if code:
        raise NotInstalled(f"uv failed: {desk.flatten(out[-400:], 220)}; " + old_install(tool))
    now = tool_named(tool.name)
    if not now or now.rev != pinned:
        raise NotInstalled(f"uv finished but the receipt says {now.rev[:7] if now else 'nothing'}, not {pinned[:7]}; nothing was restarted")
    text, fields = f"Installed as {pinned[:7]} at {when}", {"sha": pinned, "restarted": None}
    if tool.name in RESTARTS:
        label, restart = RESTARTS[tool.name]
        with deskfile.locked():
            desk.log("pressing", k, pinned=pinned, step="restart")
        try:
            ok, why = restart()
        except NotInstalled as err:
            ok, why = False, str(err)
        fields["restarted"] = ok
        text += f"; {label} restarted" if ok else f"; the restart failed ({why}), so the running {label} may still be the old one"
    return text, fields


def press(k):
    with deskfile.locked():
        it = deskwatch.item(k)
        rec = last(k)
        if not it or not it.ticked or (rec and rec["event"] in ("pressing", "installed")):
            return
        pinned = it.pinned
        desk.log("pressing", k, pinned=pinned)
    try:
        text, fields = install(k, pinned)
    except TakenBack as why:
        deskwatch.finish(k, pinned, "refused", "", False, why=str(why), page=False)
    except NotInstalled as why:
        deskwatch.finish(k, pinned, "refused", f"Not installed: {why}", True, why=str(why))
    else:
        deskwatch.finish(k, pinned, "installed", text, **fields)


def recover(k, rec):
    """Settle an install that began and never recorded a result. Never installs."""
    pinned = rec.get("pinned", "")
    tool = tool_named(k.removeprefix("install:"))
    now = tool.rev if tool else ""
    if pinned and now == pinned:
        tail = ""
        if tool.name in RESTARTS:
            tail = f"; the restart may not have run: run {RESTARTS[tool.name][0]} stop, then {RESTARTS[tool.name][0]} start"
        deskwatch.finish(k, pinned, "installed", f"Installed as {pinned[:7]} at {time.strftime('%H:%M')}{tail}",
                         sha=pinned, recovered=True)
    elif deskwatch.age(rec) >= GRACE:
        why = f"the install was interrupted before it finished; the installed commit is {now[:7] or 'unknown'}"
        deskwatch.finish(k, pinned, "refused", f"Not installed: {why}", True, why=why, recovered=True)
