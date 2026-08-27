"""Read Claude Code's own session files and answer: who is on what, right now.

Claude Code already writes everything this needs. Peer files under
`~/.claude/sessions/` say who is alive and how busy; transcripts under
`~/.claude/projects/` carry an `ai-title` record -- Claude's own one-line
answer to "what is this session about" -- and a `last-prompt` record. Nothing
here generates a summary; it collects the ones already on disk.
"""
import collections
import datetime
import json
import os
import re
import time
from pathlib import Path


def resolve_project(cwd, shelves):
    """Name the project a session is working on, or None if it has none.

    A *shelf* is a directory that holds projects without being one --
    `~/Projects`, or `~/Projects/clients`. The project is the
    first directory below the deepest shelf that contains `cwd`.
    """
    cwd = os.path.normpath(cwd)
    # Scratch space is where work passes through, never where it lives.
    if cwd.startswith(("/tmp/", "/var/tmp/")):
        return None
    shelf = max(
        (s for s in (os.path.normpath(x) for x in shelves)
         if cwd == s or cwd.startswith(s + os.sep)),
        key=len,
        default=None,
    )
    if shelf is None:
        # Outside every shelf -- a checkout somewhere unusual. Its own name is
        # the best guess available.
        return os.path.basename(cwd) or None
    rest = cwd[len(shelf):].strip(os.sep)
    if not rest:
        return None
    parts = rest.split(os.sep)
    # A dotted directory is configuration or state, not a project -- and it
    # used to outvote the real answer when guessing from touched files.
    if any(p.startswith(".") for p in parts):
        return None
    # At most client › project. Deeper is a path inside a project, and a file
    # buried in a repo must land on the same label as the repo itself.
    return " \u203a ".join(parts[:2])


def read_summary(path):
    """Pull the summary records Claude Code already wrote to a transcript.

    Returns `title` (the `ai-title` record -- Claude's own line about what the
    session is doing), `prompt` (the last thing it was asked) and `branch`.
    Later records win: a title is rewritten as the session's subject drifts.
    """
    out = {"title": "", "prompt": "", "branch": ""}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("type") == "ai-title" and rec.get("aiTitle"):
                    out["title"] = rec["aiTitle"]
                elif rec.get("type") == "last-prompt" and rec.get("lastPrompt"):
                    out["prompt"] = rec["lastPrompt"]
                branch = rec.get("gitBranch")
                if branch and branch != "HEAD":
                    out["branch"] = branch
    except OSError:
        pass
    return out


DEFAULT_SHELVES = [
    "~",
    "~/Projects",
    "~/Projects/clients",
]

_cache = {}


CONFIG = Path(__file__).resolve().parent / "config.json"


def read_config():
    try:
        with CONFIG.open(encoding="utf-8") as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def config_value(key, default):
    got = read_config().get(key, default)
    return got if isinstance(got, type(default)) else default


def write_config(patch):
    """Merge a patch into config.json, atomically.

    The file is hand-editable and holds comments as `_`-prefixed keys, so it is
    read, merged and rewritten rather than regenerated.
    """
    merged = read_config()
    merged.update(patch)
    tmp = CONFIG.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(CONFIG)
    return merged


def config(cfg_dir=None):
    """The shelves, expanded."""
    return [os.path.expanduser(s) for s in config_value("shelves", DEFAULT_SHELVES)]


def claude_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))


def alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def transcript_for(session_id, cwd, cfg=None):
    """Locate a session's transcript.

    Claude Code files transcripts by encoded cwd, so the direct path is one
    stat away; a session that moved is found by looking wider.
    """
    projects = (cfg or claude_dir()) / "projects"
    encoded = cwd.replace(os.sep, "-")
    direct = projects / encoded / f"{session_id}.jsonl"
    if direct.is_file():
        return direct
    for hit in projects.glob(f"*/{session_id}.jsonl"):
        return hit
    return None


def summary_cached(path):
    """read_summary, reparsing only when the transcript actually changed."""
    try:
        stat = path.stat()
    except OSError:
        return {"title": "", "prompt": "", "branch": ""}
    key = str(path)
    stamp = (stat.st_mtime_ns, stat.st_size)
    hit = _cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    summary = read_summary(path)
    _cache[key] = (stamp, summary)
    return summary


def _on_a_terminal(pid):
    try:
        return os.readlink(f"/proc/{pid}/fd/0").startswith("/dev/pts/")
    except OSError:
        return False


def _ancestry(pid, depth=6):
    """The command lines above a pid, closest parent first.

    Six is generous: a routine is `timer -> script -> claude`, and the extra
    room covers the shells and pipes those scripts wrap themselves in.
    """
    for _ in range(depth):
        try:
            with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
                pid = next(int(line.split()[1]) for line in fh
                           if line.startswith("PPid:"))
            if pid <= 1:
                return
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                yield fh.read().decode("utf-8", "replace").replace("\0", " ")
        except (OSError, ValueError, StopIteration):
            return


def routine_of(rec, cfg=None, ancestry=None):
    """Which routine started this session, if a routine did.

    A routine is `claude -p` fired by a systemd timer, so its peer file says
    `entrypoint: sdk-cli` where a terminal says `cli`. That alone only proves
    it is headless -- the *name* comes from the script above it in the
    process tree, `~/.claude/routines/nightly-report.sh` -> `nightly-report`.

    Both halves are required. Headless with no routine script above it is
    somebody running `claude -p` by hand, and calling that a routine would be
    a guess.
    """
    if rec.get("entrypoint") == "cli":
        return ""
    root = str((cfg or claude_dir()) / "routines") + os.sep
    if ancestry is None:
        ancestry = _ancestry(rec.get("pid"))
    for cmd in ancestry:
        for token in cmd.split():
            if token.startswith(root):
                return os.path.splitext(os.path.basename(token))[0]
    return ""


PATH_IN_TEXT = re.compile(r"(?:~|/home/[\w.-]+)/[\w./@-]+")
TAIL_LINES = 400


def touched_paths(path):
    """Filesystem paths a session's recent tool calls mention.

    Only the tail: what it is doing now, not what it did on Tuesday.
    """
    out = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return out
    for line in lines[-TAIL_LINES:]:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        content = (rec.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "tool_use":
                continue
            inp = part.get("input") or {}
            for key in ("file_path", "path", "notebook_path"):
                if isinstance(inp.get(key), str):
                    out.append(inp[key])
            for key in ("command", "pattern", "prompt"):
                if isinstance(inp.get(key), str):
                    out += PATH_IN_TEXT.findall(inp[key])
    home = str(Path.home())
    return [os.path.normpath(p.replace("~", home, 1)) for p in out]


def pending_tool(path):
    """Minutes the current tool call has been outstanding, or None if none.

    A `tool_use` with no matching `tool_result` after it is a call still
    running -- or still waiting for you to approve it.
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    uses, done = {}, set()
    for line in lines[-TAIL_LINES:]:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        content = (rec.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use" and part.get("id"):
                uses[part["id"]] = rec.get("timestamp")
            elif part.get("type") == "tool_result" and part.get("tool_use_id"):
                done.add(part["tool_use_id"])
    stamps = [t for tid, t in uses.items() if tid not in done and t]
    if not stamps:
        return None
    try:
        started = max(
            datetime.datetime.fromisoformat(s.replace("Z", "+00:00")) for s in stamps)
    except ValueError:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    return max(0.0, (now - started).total_seconds() / 60)


def scan(path):
    """Everything the page needs from a transcript, in one pass.

    Title, last prompt, branch, the paths it has been touching and whether a
    tool call is outstanding used to be three separate full reads of a file
    that runs to hundreds of kilobytes -- per session, per poll. The page
    polls every three seconds; that cost is what made a click feel broken.
    """
    out = {"title": "", "prompt": "", "branch": "", "paths": [], "pending": None}
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return out

    home = str(Path.home())
    uses, done = {}, set()
    tail_from = max(0, len(lines) - TAIL_LINES)
    for i, line in enumerate(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        kind = rec.get("type")
        if kind == "ai-title" and rec.get("aiTitle"):
            out["title"] = rec["aiTitle"]
            continue
        if kind == "last-prompt" and rec.get("lastPrompt"):
            out["prompt"] = rec["lastPrompt"]
        branch = rec.get("gitBranch")
        if branch and branch != "HEAD":
            out["branch"] = branch
        if i < tail_from:
            continue                       # the rest is about recent activity
        content = (rec.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use":
                if part.get("id"):
                    uses[part["id"]] = rec.get("timestamp")
                inp = part.get("input") or {}
                for key in ("file_path", "path", "notebook_path"):
                    if isinstance(inp.get(key), str):
                        out["paths"].append(inp[key])
                for key in ("command", "pattern", "prompt"):
                    if isinstance(inp.get(key), str):
                        out["paths"] += PATH_IN_TEXT.findall(inp[key])
            elif part.get("type") == "tool_result" and part.get("tool_use_id"):
                done.add(part["tool_use_id"])

    out["paths"] = [os.path.normpath(p.replace("~", home, 1)) for p in out["paths"]]
    stamps = [t for tid, t in uses.items() if tid not in done and t]
    if stamps:
        try:
            started = max(datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
                          for s in stamps)
            now = datetime.datetime.now(datetime.timezone.utc)
            out["pending"] = max(0.0, (now - started).total_seconds() / 60)
        except ValueError:
            pass
    return out


def _read_from(path, offset):
    """Bytes appended since `offset`, up to the last complete line.

    A session may be mid-write, so the final fragment is left for next time
    rather than parsed as a broken record.
    """
    with path.open("rb") as fh:
        fh.seek(offset)
        data = fh.read()
    cut = data.rfind(b"\n") + 1
    return data[:cut].decode("utf-8", errors="ignore"), offset + cut


HEAD_BYTES = 256
COLD_BYTES = 2_000_000   # enough tail to answer 'what is it doing now'


def _head(path):
    """The first bytes of the file, as a cheap identity for its contents."""
    try:
        with path.open("rb") as fh:
            return fh.read(HEAD_BYTES)
    except OSError:
        return b""


def _blank_state():
    return {"offset": 0, "ino": None, "head": b"", "title": "", "prompt": "", "branch": "",
            "uses": {}, "done": set(), "paths": collections.deque(maxlen=400)}


def _absorb(state, text):
    """Fold newly written lines into what we already know."""
    home = str(Path.home())
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        kind = rec.get("type")
        if kind == "ai-title" and rec.get("aiTitle"):
            state["title"] = rec["aiTitle"]
        elif kind == "last-prompt" and rec.get("lastPrompt"):
            state["prompt"] = rec["lastPrompt"]
        branch = rec.get("gitBranch")
        if branch and branch != "HEAD":
            state["branch"] = branch
        content = (rec.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use":
                if part.get("id"):
                    state["uses"][part["id"]] = rec.get("timestamp")
                inp = part.get("input") or {}
                for key in ("file_path", "path", "notebook_path"):
                    if isinstance(inp.get(key), str):
                        state["paths"].append(
                            os.path.normpath(inp[key].replace("~", home, 1)))
                for key in ("command", "pattern", "prompt"):
                    if isinstance(inp.get(key), str):
                        for hit in PATH_IN_TEXT.findall(inp[key]):
                            state["paths"].append(
                                os.path.normpath(hit.replace("~", home, 1)))
            elif part.get("type") == "tool_result" and part.get("tool_use_id"):
                state["done"].add(part["tool_use_id"])
    # Answered calls stop mattering, and neither set may grow without end.
    for tid in [t for t in state["uses"] if t in state["done"]][:-8]:
        state["uses"].pop(tid, None)
        state["done"].discard(tid)
    return state


def _view(state):
    stamps = [t for tid, t in state["uses"].items()
              if tid not in state["done"] and t]
    pending = None
    if stamps:
        try:
            started = max(datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
                          for s in stamps)
            now = datetime.datetime.now(datetime.timezone.utc)
            pending = max(0.0, (now - started).total_seconds() / 60)
        except ValueError:
            pending = None
    return {"title": state["title"], "prompt": state["prompt"],
            "branch": state["branch"], "paths": list(state["paths"]),
            "pending": pending}


def scan_cached(path):
    """What the page needs from a transcript, reading only what is new.

    These files reach tens of megabytes and the busy ones change every few
    seconds. Re-reading them whole on every poll cost ~9 seconds a round and
    made clicking feel broken.
    """
    try:
        stat = path.stat()
    except OSError:
        return _view(_blank_state())
    key = ("state", str(path))
    state = _cache.get(key)
    head = _head(path)
    # Same inode and a file that only grew is the normal case. A shrunken file
    # or a changed opening means it was rewritten, and what we remember about
    # it is about a file that no longer exists.
    # A file shorter than HEAD_BYTES grows its own head as it is appended to,
    # so one being a prefix of the other still means the same file.
    same_file = (state is not None
                 and state["ino"] == stat.st_ino
                 and stat.st_size >= state["offset"]
                 and (head.startswith(state["head"])
                      or state["head"].startswith(head)))
    if not same_file:
        state = _blank_state()          # new file, or rewritten from the top
        state["ino"] = stat.st_ino
    state["head"] = head
    if state["offset"] == 0 and stat.st_size > COLD_BYTES:
        # First sight of a large transcript. Every value here is a *latest*
        # one, so the tail answers them; only a title that was set early and
        # never again needs the whole file, and that is one read, once.
        text, offset = _read_from(path, stat.st_size - COLD_BYTES)
        state = _absorb(state, text)
        state["offset"] = offset
        if not state["title"]:
            head_text, _ = _read_from(path, 0)
            for line in head_text.splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") == "ai-title" and rec.get("aiTitle"):
                    state["title"] = rec["aiTitle"]
    elif stat.st_size > state["offset"]:
        text, offset = _read_from(path, state["offset"])
        state = _absorb(state, text)
        state["offset"] = offset
    _cache[key] = state
    return _view(state)


def suggestion_cached(path, shelves):
    key = ("suggest", str(path))
    try:
        stat = path.stat()
    except OSError:
        return None
    stamp = (stat.st_mtime_ns, stat.st_size)
    hit = _cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    guess = suggest_project(touched_paths(path), shelves)
    _cache[key] = (stamp, guess)
    return guess


def live_session(pid, cfg=None):
    """The peer record for a live pid, reading nothing else.

    `sessions()` reads every transcript to build the page; a jump only needs
    to know this pid is really a session Claude Code registered, and paying
    1.5s for that makes the click feel broken.
    """
    cfg = cfg or claude_dir()
    for path in (cfg / "sessions").glob("*.json"):
        try:
            with path.open(encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("pid") == pid and alive(pid):
            return rec
    return None


def sessions(cfg=None):
    """Every live Claude session on this machine, with its summary attached."""
    cfg = cfg or claude_dir()
    shelves = config()
    assigned = config_value("assign", {})
    out = []
    for path in (cfg / "sessions").glob("*.json"):
        try:
            with path.open(encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or not alive(rec.get("pid")):
            continue
        cwd = rec.get("cwd") or ""
        sid = rec.get("sessionId") or ""
        transcript = transcript_for(sid, cwd, cfg) if sid else None
        summary = scan_cached(transcript) if transcript else {
            "title": "", "prompt": "", "branch": "", "paths": [], "pending": None}
        quiet = None
        if transcript:
            try:
                quiet = (time.time() - transcript.stat().st_mtime) / 60
            except OSError:
                quiet = None
        in_flight = summary["pending"] if rec.get("status") == "busy" else None
        status_since = rec.get("statusUpdatedAt") or rec.get("updatedAt") or 0
        project = assigned.get(sid) or resolve_project(cwd, shelves)
        routine = routine_of(rec, cfg)
        # Only guess for the ones that have nothing better -- the guess costs
        # a transcript scan, and a session with a real cwd does not need it.
        # A routine is never guessed for: it belongs to the routine that
        # started it, whatever files it happens to touch on the way.
        guess = (suggest_project(summary["paths"], shelves)
                 if not project and transcript and not routine else None)
        out.append({
            "name": rec.get("name") or "(unnamed)",
            "status": rec.get("status") or "?",
            "kind": rec.get("kind") or "?",
            "cwd": cwd,
            "tmux": rec.get("tmux") or "",
            "pid": rec.get("pid"),
            "sessionId": sid,
            "updatedAt": rec.get("statusUpdatedAt") or rec.get("updatedAt") or 0,
            "startedAt": rec.get("startedAt") or 0,
            "project": project,
            "routine": routine,
            "assigned": sid in assigned,
            "suggestion": guess,
            "quietFor": round(quiet, 1) if quiet is not None else None,
            "toolFor": round(in_flight, 1) if in_flight is not None else None,
            "stuck": classify(
                rec.get("status") or "", quiet,
                config_value("stuck_after_minutes", 5),
                in_flight=in_flight,
                tool_after=config_value("long_tool_minutes", 20),
                waiting_for=(time.time() * 1000 - status_since) / 60000,
                waiting_after=config_value("waiting_after_seconds", 20) / 60),
            # Cheap: a session on a pty is hosted by some emulator, so a route
            # exists. Working out which one costs subprocesses, so that waits
            # until you actually click.
            "canJump": (rec.get("kind") == "interactive"
                        and _on_a_terminal(rec.get("pid"))),
            "title": summary["title"],
            "prompt": summary["prompt"],
            "branch": summary["branch"],
        })
    return out


ROUTINES = "Routines"


def roster(cfg=None):
    """Sessions grouped into project blocks, liveliest project first.

    Project-first: the question is what is happening, and who is on it.

    Routines are the exception: they are grouped by being routines rather
    than by where they run. A routine runs from `~`, which is no project, so
    it used to land in `No project` -- the pile that means "assign me", which
    is the one thing a routine never needs. They get their own block, keyed
    apart from the projects so a real project of the same name cannot be
    swallowed into it.
    """
    groups = {}
    for s in sessions(cfg):
        key = (True, ROUTINES) if s["routine"] else (False, s["project"] or "")
        groups.setdefault(key, []).append(s)

    blocks = []
    for (routines, project), members in groups.items():
        members.sort(key=lambda s: (s["status"] != "busy", -s["updatedAt"]))
        branches = sorted({s["branch"] for s in members if s["branch"]})
        blocks.append({
            "stuck": sum(1 for s in members if s["stuck"]),
            "project": project or "No project",
            "orphan": not project,
            "routines": routines,
            "branches": branches,
            "busy": sum(1 for s in members if s["status"] == "busy"),
            "updatedAt": max(s["updatedAt"] for s in members),
            "members": members,
        })
    names = config_value("names", {})
    lines = config_value("lines", {})
    blocks = [apply_overrides(b, names, lines) for b in blocks]
    pinned = config_value("pinned", [])
    for b in blocks:
        b["pinned"] = b["project"] in pinned
    return order_blocks(blocks, pinned)


MIN_VOTES = 3          # below this it is noise, not a habit
LEAD = 1.5             # the winner has to be clearly ahead of the runner-up


def suggest_project(paths, shelves):
    """Guess a session's project from the files it keeps touching.

    Only ever a suggestion. It is right when a session works in one place and
    silent when it does not -- being confidently wrong is the one outcome that
    matters here, because you would never know to look.
    """
    votes = collections.Counter()
    for path in paths:
        # Files vote for the directory they live in.
        folder = os.path.dirname(path) if os.path.splitext(path)[1] else path
        project = resolve_project(folder, shelves)
        if project:
            votes[project] += 1
    if not votes:
        return None
    ranked = votes.most_common(2)
    top, count = ranked[0]
    if count < MIN_VOTES:
        return None
    if len(ranked) > 1 and count < ranked[1][1] * LEAD:
        return None
    return top


def classify(status, quiet, after, in_flight=None, tool_after=20,
             waiting_for=None, waiting_after=0):
    """Is this session stuck, waiting on you, running long, or just working?

    - `waiting` -- Claude Code has asked something and nobody replied. It
      needs *you*, and there is no grace period.
    - a tool call in flight -- the transcript is silent for the whole of a
      tool call, so silence proves nothing while one is running. Only when it
      has run absurdly long is it worth saying, and even then it is news, not
      an alarm.
    - `busy`, silent, nothing running -- it thinks it is working and it is
      not. The transcript's mtime is the only honest heartbeat: `updatedAt`
      in the peer file does not move while a session works.

    Idle is not stuck. A session idle for two days is finished or abandoned,
    and flashing it forever would only teach you to ignore the flashing.
    """
    if status == "waiting":
        # `/btw` and friends spawn helpers that sit in `waiting` for a few
        # seconds. A flag that fires on those is a flag you learn to ignore.
        if waiting_for is not None and waiting_for < waiting_after:
            return None
        return "waiting"
    if status != "busy":
        return None
    if in_flight is not None:
        return "tool" if in_flight >= tool_after else None
    if quiet is not None and quiet >= after:
        return "stuck"
    return None


def apply_overrides(block, names, lines):
    """Lay your own labels over the generated ones.

    `project` stays the key everything else is stored against -- pins, names,
    the lot -- so renaming a project never orphans its own pin. `label` is the
    only thing the page reads.
    """
    block["label"] = names.get(block["project"], block["project"])
    block["renamed"] = block["project"] in names
    for m in block["members"]:
        own = lines.get(m.get("sessionId"))
        m["overridden"] = bool(own)
        if own:
            m["title"] = own
    return block


def order_blocks(blocks, pinned):
    """Pinned projects in the order you put them; the rest sort themselves.

    A pin is muscle memory -- the two or three projects you look at every day
    should not move because something else woke up. Everything unpinned still
    floats liveliest-first underneath, and `No project` stays at the bottom
    whatever happens.

    Routines sit below even that. `No project` is asking you for something;
    routines are asking for nothing and will be gone in a few minutes.
    """
    rank = {name: i for i, name in enumerate(pinned)}
    return sorted(blocks, key=lambda b: (
        b.get("routines", False),
        b["orphan"],
        rank.get(b["project"], len(rank)),
        -b.get("stuck", 0),      # something needing you outranks something busy
        -b["busy"],
        -b["updatedAt"],
    ))
