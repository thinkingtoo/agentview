"""Read Claude Code's own session files and answer: who is on what, right now.

Claude Code already writes everything this needs. Peer files under
`~/.claude/sessions/` say who is alive and how busy; transcripts under
`~/.claude/projects/` carry an `ai-title` record -- Claude's own one-line
answer to "what is this session about" -- and a `last-prompt` record. Nothing
here generates a summary; it collects the ones already on disk.
"""
import json
import os
from pathlib import Path


def resolve_project(cwd, shelves):
    """Name the project a session is working on, or None if it has none.

    A *shelf* is a directory that holds projects without being one --
    `~/Projects`, or `~/Projects/clients`. The project is the
    first directory below the deepest shelf that contains `cwd`.
    """
    cwd = os.path.normpath(cwd)
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
    return " \u203a ".join(rest.split(os.sep))


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


def config(cfg_dir=None):
    """Shelves, from config.json next to this file, or the defaults."""
    here = Path(__file__).resolve().parent
    shelves = DEFAULT_SHELVES
    try:
        with (here / "config.json").open(encoding="utf-8") as fh:
            shelves = json.load(fh).get("shelves") or DEFAULT_SHELVES
    except (OSError, ValueError):
        pass
    return [os.path.expanduser(s) for s in shelves]


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


def sessions(cfg=None):
    """Every live Claude session on this machine, with its summary attached."""
    cfg = cfg or claude_dir()
    shelves = config()
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
        summary = summary_cached(transcript) if transcript else {
            "title": "", "prompt": "", "branch": ""}
        out.append({
            "name": rec.get("name") or "(unnamed)",
            "status": rec.get("status") or "?",
            "kind": rec.get("kind") or "?",
            "cwd": cwd,
            "tmux": rec.get("tmux") or "",
            "pid": rec.get("pid"),
            "sessionId": sid,
            "updatedAt": rec.get("statusUpdatedAt") or rec.get("updatedAt") or 0,
            "project": resolve_project(cwd, shelves),
            "title": summary["title"],
            "prompt": summary["prompt"],
            "branch": summary["branch"],
        })
    return out


def roster(cfg=None):
    """Sessions grouped into project blocks, liveliest project first.

    Project-first: the question is what is happening, and who is on it.
    """
    groups = {}
    for s in sessions(cfg):
        groups.setdefault(s["project"] or "", []).append(s)

    blocks = []
    for project, members in groups.items():
        members.sort(key=lambda s: (s["status"] != "busy", -s["updatedAt"]))
        branches = sorted({s["branch"] for s in members if s["branch"]})
        blocks.append({
            "project": project or "No project",
            "orphan": not project,
            "branches": branches,
            "busy": sum(1 for s in members if s["status"] == "busy"),
            "updatedAt": max(s["updatedAt"] for s in members),
            "members": members,
        })
    # Liveliest first; the orphan block always sinks to the bottom.
    blocks.sort(key=lambda b: (b["orphan"], -b["busy"], -b["updatedAt"]))
    return blocks
