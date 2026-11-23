"""The merge desk's Install items: a tool installed from a git URL that is behind its `main` is on the desk by itself, and a ticked one is installed.

`scan()` reads the `uv tool` receipts (`$UV_TOOL_DIR`, else `$XDG_DATA_HOME/uv/tools`, else
`~/.local/share/uv/tools`, one `<tool>/uv-receipt.toml` each). A receipt is taken for a tool only in
the one shape uv writes for `uv tool install --from git+https://github.com/<owner>/<repo>@<sha>`:
a single requirement with `git = "https://github.com/<owner>/<repo>?rev=<hex>"`, owner
`sweatshop-ai` or `tiroir`. Any other shape (a path, a registry, a branch, two requirements, a file
that does not parse) is skipped: it never becomes an item.

Three rules decide the item:

1. **A short rev is the commit GitHub names for it.** `uv tool install --from git+…@a30694be` writes
   the 8 hex as given. A rev of 7 to 39 hex is resolved once through `repos/<repo>/commits/<short>`
   and kept for the life of the process; a short rev GitHub does not resolve to one commit (unknown,
   or shared by several) is a refusal that names it, logged by the scan and written under a ticked item.
2. **The pin is the newest green commit of main**, never main's head as such: walking main's first
   parents from the head, at most `WINDOW` commits, the first whose checks all finished well (the
   scan's rule, `deskscan.green`: at least one check, every one success, neutral or skipped). A
   commit with no checks at all (a notes-only push that `paths-ignore` keeps out of CI) is passed
   over. With no green commit in the window there is no new item, and the scan logs it. The item
   says how far main is ahead of the pin.
3. **An install that left main gets an item too.** A tool behind the pin gets one; so does a tool
   whose commit GitHub calls diverged from it (a history rewrite left the install on no branch), and
   that item says the installed commit is not on main. A tool at the pin, or newer than it, gets
   none, and an unticked item for a tool that has caught up is dropped.

Items stand under "Local installs waiting for you". An item is only re-pinned or dropped while
unticked and not under a press.

`press(k)` installs exactly the pinned commit, `uv tool install --reinstall --from
git+<url>@<pinned> <package>`, never "whatever main is now". If main moved since, the install is
still the reviewed one and the next scan makes a new item for the new head. Before it runs it reads
the receipt again: a tool already at the pinned commit is "Already installed", and one whose
installed commit is not behind the pinned one (installed by hand since) is refused, so a press can
never go backwards. A diverged install is pressed over only when it is the very commit the scan
handed the item over for (its `ready` record), never one put there by hand since. A failed `uv` leaves the old install as it was (uv builds and resolves before it
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
import json
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
import deskscan
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
GIT = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?\?rev=([0-9a-f]{7,40})")
WINDOW = 50                 # first-parent commits of main looked through for a green one
HISTORY = 100               # commits of main's history asked for in that one call (merges' other parents take room too)
_last_scan = [0.0]
_resolved = {}              # (repo, short rev) -> full sha, as GitHub named it
GREEN_QUERY = """query($owner: String!, $name: String!, $n: Int!) {
  repository(owner: $owner, name: $name) { ref(qualifiedName: "refs/heads/main") { target { ... on Commit {
    oid
    history(first: $n) { nodes {
      oid
      parents(first: 1) { nodes { oid } }
      statusCheckRollup { contexts(first: 100) { nodes {
        __typename ... on CheckRun { status conclusion } ... on StatusContext { state } } } }
    } }
  } } } }
}"""


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


def full_sha(repo, name, short):
    """The commit GitHub names for a short rev; NotInstalled, naming it, when it names none or cannot be asked."""
    if (repo, short) in _resolved:
        return _resolved[(repo, short)]
    code, out = deskwatch.gh("api", f"repos/{repo}/commits/{short}", "--jq", ".sha")
    if code or not SHA.fullmatch(out) or not out.startswith(short):
        raise NotInstalled(f"the uv receipt of {name} names the short commit {short}, which GitHub does not resolve to "
                           f"one commit of {repo}: {desk.flatten(out, 120)}")
    _resolved[(repo, short)] = out
    return out


def read_receipt(folder):
    """The Tool a receipt describes, or None for any shape this does not know. A short rev is resolved
    through GitHub; one it does not resolve raises NotInstalled."""
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
        tool = Tool(folder.name, name, f"{got.group(1)}/{got.group(2)}", got.group(3))
    except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError, desk.Refused):
        return None
    if len(tool.rev) < 40:
        tool.rev = full_sha(tool.repo, tool.name, tool.rev)
    return tool


def folders():
    try:
        return sorted(p for p in tools_dir().iterdir() if p.is_dir())
    except OSError:
        return []


def receipts():
    """Every tool of a known shape; one whose short rev GitHub does not resolve is logged and left out."""
    out = []
    for folder in folders():
        try:
            tool = read_receipt(folder)
        except NotInstalled as why:
            deskwatch.log.error("desk-install-scan", why, key="install:" + folder.name)
            continue
        if tool:
            out.append(tool)
    return out


def tool_named(name):
    """The tool of that folder, None for no receipt of a known shape; NotInstalled for a short rev GitHub does not resolve."""
    return next((read_receipt(f) for f in folders() if f.name == name), None)


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


def node_green(node):
    """Whether one commit of the GraphQL history has finished checks that are all good (deskscan's rule)."""
    try:
        return deskscan.green(node["statusCheckRollup"]["contexts"]["nodes"])
    except (KeyError, TypeError):
        return False


def green_pin(repo):
    """(main's head, the newest green commit on main's first-parent line within WINDOW), the second None when none is green."""
    owner, name = repo.split("/")
    code, out = deskwatch.gh("api", "graphql", "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"n={HISTORY}",
                             "-f", f"query={GREEN_QUERY}")
    try:
        target = json.loads(out)["data"]["repository"]["ref"]["target"]
        head = target["oid"]
        nodes = {n["oid"]: n for n in target["history"]["nodes"]}
        if code or not SHA.fullmatch(head):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise NotInstalled(f"GitHub could not be asked for {repo}'s checks on main: {desk.flatten(out, 120)}") from None
    sha = head
    for _ in range(WINDOW):
        node = nodes.get(sha)
        if not isinstance(node, dict):
            break
        if node_green(node):
            return head, sha
        try:
            sha = node["parents"]["nodes"][0]["oid"]
        except (KeyError, IndexError, TypeError):
            break
    return head, None


def plural(n):
    return f"{n} commit" + ("" if n == 1 else "s")


def item_block(tool, pin, behind, main_ahead, diverged, when):
    title = f"installed commit {tool.rev[:7]} is not on main (history rewritten?)" if diverged \
        else f"{tool.repo} is {plural(behind)} behind its newest green main commit"
    lines = [
        f"- [ ] Install {tool.name}: {title}",
        "  - Recommendation: found by the scan, no recommendation yet.",
        pin_line(tool, pin, main_ahead),
    ]
    if diverged:
        lines.append(f"  - The installed commit {tool.rev[:7]} is not on main: installing puts the pinned commit in its place.")
    lines.append(f"  - Handed over by AgentView's scan, {when}.")
    return "\n".join(lines) + "\n"


def pin_line(tool, pin, main_ahead):
    ahead = f", main is {plural(main_ahead)} ahead of it" if main_ahead else ", main's head"
    return f"  - Pinned commit: {pin}, the newest green commit of main of {tool.repo}{ahead}; installed now: {tool.rev}"


def last(k):
    return deskwatch.last_event(k)


def scan_tool(tool):
    """Bring the item of one tool in line with GitHub. Raises NotInstalled when GitHub cannot be asked."""
    k = "install:" + tool.name
    head, pin = green_pin(tool.repo)
    if pin is None:
        raise NotInstalled(f"no green commit in the last {WINDOW} commits of {tool.repo}'s main (head {head[:7]}): no item")
    status, behind = compare(tool.repo, tool.rev, pin)
    main_ahead = compare(tool.repo, pin, head)[1] if pin != head else 0
    with deskfile.locked():
        cur = deskwatch.item(k)
        rec = last(k)
        pressing = bool(rec) and rec["event"] == "pressing"
        waiting_on_press = bool(cur) and cur.ticked and (rec is None or rec["event"] != "installed")
        if pressing or waiting_on_press:                        # a ticked item is the watcher's, not the scan's
            return
        if status not in ("ahead", "diverged"):                 # at the pin or newer than it: nothing to install
            if cur and not cur.ticked:
                deskfile.drop_item(k)
                desk.log("withdrawn", k)
            return
        if cur and not cur.ticked and cur.pinned == pin and pin_line(tool, pin, main_ahead) in cur.block:
            return
        block = item_block(tool, pin, behind, main_ahead, status == "diverged", time.strftime("%Y-%m-%d %H:%M"))
        deskfile.put_item(k, block, section="install")
        desk.log("ready", k, pinned=pin, installed=tool.rev, by="AgentView's scan")


def scan():
    for tool in receipts():
        try:
            scan_tool(tool)
        except (NotInstalled, OSError) as why:
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
        return False, f"sheaf stop failed, so the running sheaf may still be the old one: {desk.flatten(out, 120)}"
    start = [sheaf, "start"]
    scope = EXES.get("systemd-run")
    if not scope or not os.path.isabs(scope):                   # no systemd-run at all: start it where we are
        code, out = run(start, env)
    else:                                                       # never a plain start after a failed scope: it would land in our cgroup
        code, out = run([scope, "--user", "--scope", "--quiet", "--collect", "--", *start], env)
    return (True, "") if not code else (False, f"sheaf start failed after sheaf stop: {desk.flatten(out, 120)}; no hub is running now")


RESTARTS = {"sheafmd": ("sheaf", restart_sheaf)}


def uv_env():
    return {**os.environ, "PATH": SYSTEM_PATH, "GIT_TERMINAL_PROMPT": "0"}


def old_install(tool):
    """What to say about the install that was there, after a failure."""
    try:
        now = tool_named(tool.name)
    except NotInstalled as why:
        return f"could not confirm the old install ({tool.rev[:7]}): {why}"
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
    if status == "diverged":                                    # only over the install the item was handed over for
        ready = [r for r in desk.history(k) if r["event"] == "ready"]
        if not ready or ready[-1].get("installed") != tool.rev or ready[-1].get("pinned") != pinned:
            status = "changed"
    if status not in ("ahead", "diverged"):
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
        text += f"; {label} restarted" if ok else f"; the restart failed ({why})"
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
    try:
        tool = tool_named(k.removeprefix("install:"))
    except NotInstalled:
        tool = None
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
