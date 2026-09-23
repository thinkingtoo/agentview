"""Claude Code as a provider: read its own session files and say who is alive.

Claude Code already writes everything this needs. Peer files under
`~/.claude/sessions/` say who was there and how busy, and `/proc` says
which of them still is -- the file outlives the session. Transcripts under
`~/.claude/projects/` carry an `ai-title` record -- Claude's own one-line
answer to "what is this session about" -- and a `last-prompt` record. Nothing
here generates a summary; it collects the ones already on disk.

The two lines under a name (`did`, `ask`) come from `hooks/team-line`, which
the session runs inside its own turn; the core reads them by session id.
"""
import collections
import datetime
import json
import os
import re
import time
from pathlib import Path

import lines
from providers.base import (Provider, Tailed, alive, controlling_tty,
                            on_a_terminal, read_from as _read_from)


def claude_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))


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

# A skill starts in one of two ways, and they look nothing alike on disk:
# the model calls the `Skill` tool, or you type `/boss` and Claude Code
# writes a `<command-name>` line. Matching only the first missed a boss for
# a whole morning.
TYPED_SKILL = re.compile(r"<command-name>/([\w:-]+)</command-name>")
BOSS_MARKS = (b'"skill":"boss"', b'"skill": "boss"',
              b"<command-name>/boss</command-name>")


def boss_line(rec):
    """Is this record a session starting the `boss` skill?

    Deliberately strict about *where* the marker sits. A session that reads
    the skill's files, or prints them, carries the same words in a tool
    result -- and that session is not running a team.
    """
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        hit = TYPED_SKILL.search(content)
        return bool(hit) and hit.group(1) == "boss"
    for part in content or []:
        if (isinstance(part, dict) and part.get("type") == "tool_use"
                and part.get("name") == "Skill"
                and (part.get("input") or {}).get("skill") == "boss"):
            return True
    return False


def _boss_file(path):
    """Did this session ever start the boss skill? One read, once.

    Bounded scanning was tried and was wrong: `/boss` was typed a third of
    the way into a 1.8 MB transcript, well past any sensible head. The
    substring pass over the raw bytes is what makes reading it all cheap --
    only a file that mentions the skill at all is ever parsed.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    if not any(mark in raw for mark in BOSS_MARKS):
        return False
    for line in raw.decode("utf-8", "replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and boss_line(rec):
            return True
    return False


# How many outstanding calls to remember. Only the newest matters, but a
# message can carry several in parallel and each one deserves its place.
MAX_USES = 64


def _blank_state():
    return {"offset": 0, "ino": None, "head": b"", "title": "", "prompt": "", "branch": "",
            "uses": {}, "done": set(), "said": "", "spoke": "", "boss": False,
            "sent": collections.Counter(),
            "paths": collections.deque(maxlen=400)}


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
        if not state["boss"] and boss_line(rec):
            state["boss"] = True
        # A typed prompt ends the turn that said something. Kept past it, the
        # previous turn's closing sentence reads on a busy row as what the
        # session is doing now. A tool result is a list, and the hook's own
        # block arrives as a meta record -- neither is you speaking.
        if (kind == "user" and not rec.get("isMeta")
                and isinstance(content, str) and content.strip()):
            state["said"] = ""
        if not isinstance(content, list):
            continue
        # When the session last said anything at all. A tool call is only in
        # flight while it is the newest thing in the file: after this moves
        # past it, the result is never coming and nothing is running.
        if kind in ("user", "assistant") and rec.get("timestamp"):
            state["spoke"] = max(state["spoke"], rec["timestamp"])
        # A subagent must never speak for the session it works for.
        if kind == "assistant" and not rec.get("isSidechain"):
            for part in content:
                if (isinstance(part, dict) and part.get("type") == "text"
                        and isinstance(part.get("text"), str) and part["text"].strip()):
                    state["said"] = part["text"].strip()
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use":
                if part.get("id"):
                    state["uses"][part["id"]] = (
                        rec.get("timestamp"), part.get("name") or "",
                        _kept(part.get("input")))
                # Who it works with: every peer it has messaged. `to` is
                # the address -- a name, sometimes with a disambiguating ref.
                if part.get("name") == "SendMessage":
                    peer = (part.get("input") or {}).get("to")
                    if isinstance(peer, str) and not peer.startswith("uds:"):
                        state["sent"][peer.split(" [")[0].strip()] += 1
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
    # Unanswered ones need a bound of their own: a result that never arrives
    # would otherwise be remembered for the life of the session. Dicts keep
    # insertion order, so this drops the oldest.
    for tid in list(state["uses"])[:-MAX_USES]:
        state["uses"].pop(tid, None)
        state["done"].discard(tid)
    return state


def _cold(state, path):
    """What the tail of a big transcript cannot answer, read once."""
    if not state["boss"]:
        state["boss"] = _boss_file(path)
    if not state["title"]:
        # A title set early and never again needs the whole file.
        head_text, _ = _read_from(path, 0)
        for line in head_text.splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") == "ai-title" and rec.get("aiTitle"):
                state["title"] = rec["aiTitle"]


TAIL = Tailed(_blank_state, _absorb, _cold)
_cache = TAIL.cache


# What each tool is, said the way you would say it. Anything not here says
# its own name -- vague beats wrong, and an unknown tool is still news.
VERBS = {
    "Edit": "Editing", "Write": "Writing", "NotebookEdit": "Editing",
    "Read": "Reading", "Glob": "Looking for", "Grep": "Searching for",
    "WebFetch": "Fetching", "Skill": "Running", "Task": "Running",
    "Agent": "Running", "SendMessage": "Messaging",
}
# Which input field names the thing being worked on, per tool.
TARGET = {
    "Edit": "file_path", "Write": "file_path", "NotebookEdit": "notebook_path",
    "Read": "file_path", "Glob": "pattern", "Grep": "pattern",
    "WebFetch": "url", "Skill": "skill", "Task": "description",
    "Agent": "description", "SendMessage": "to",
}
PLURAL = {"Read": "files", "Edit": "files", "Write": "files",
          "Grep": "searches", "WebFetch": "pages"}

# A Write carries a whole file in its input and a Task a whole prompt. Only
# the fields that name the work are kept, and only their first words: this
# state lives for the life of the session, times every session on the page.
KEEP = ("description", "command", "file_path", "notebook_path", "path",
        "pattern", "url", "skill", "to", "query")

ASK_LIMIT = lines.LIMIT


def _kept(inp):
    if not isinstance(inp, dict):
        return {}
    return {k: v[:200] for k, v in inp.items()
            if k in KEEP and isinstance(v, str)}


def activity(calls):
    """What a session is doing, from the calls that have not come back.

    A busy row printed your own last prompt back at you, which you wrote and
    already know. This is the one thing on the card that moves while it works.
    """
    if not calls:
        return ""
    # Parallel reads are the common case and three filenames do not fit.
    names = {name for name, _ in calls}
    if len(calls) > 1 and len(names) == 1:
        name = calls[0][0]
        if name in PLURAL:
            return f"{VERBS[name]} {len(calls)} {PLURAL[name]}"
    name, inp = calls[-1]
    inp = inp if isinstance(inp, dict) else {}
    if name == "Bash":
        # Every Bash call carries a description already; nothing here needs
        # to invent a phrase when the caller wrote one.
        said = inp.get("description")
        return _fit(said if isinstance(said, str) and said.strip()
                    else f"Running {inp.get('command', '')}".strip())
    verb = VERBS.get(name)
    if not verb:
        return _plain(name)
    target = inp.get(TARGET.get(name, ""), "")
    if not isinstance(target, str) or not target.strip():
        return _plain(name)
    if TARGET[name].endswith("path"):
        target = os.path.basename(target.rstrip("/")) or target
    if name == "Skill":
        target = "/" + target
    return _fit(f"{verb} {target}")


def _plain(name):
    """A tool's own name, said out loud.

    An MCP tool is addressed `mcp__<server>__<tool>`, which is a wire address
    and reads like one on a card.
    """
    parts = name.split("__")
    if len(parts) < 3 or parts[0] != "mcp":
        return name
    words = " ".join(parts[2].split("_"))
    return words[:1].upper() + words[1:]


def _fit(text):
    text = " ".join(str(text).split())
    return text if len(text) <= ASK_LIMIT else text[:ASK_LIMIT - 1].rstrip() + "…"


def _view(state):
    # Only calls in the session's newest message. An unanswered call the
    # session has since talked past is not running -- and because this file
    # is read incrementally, it would otherwise be remembered forever and
    # flag the session `tool 40m` on every busy poll for the rest of the day.
    running = [call for tid, call in state["uses"].items()
               if tid not in state["done"] and call[0] and call[0] >= state["spoke"]]
    stamps = [call[0] for call in running]
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
            # The raw last message: the core shapes it into the one line the
            # card shows, and reads the ask out of the whole of it.
            "said": state["said"], "boss": state["boss"],
            "doing": activity([(name, inp) for _, name, inp in running]),
            # Liveliest correspondent first: a boss's team, in the order it
            # actually deals with them.
            "sent": [name for name, _ in state["sent"].most_common()],
            "pending": pending}


def scan_cached(path):
    """What the page needs from a transcript, reading only what is new."""
    return _view(TAIL.scan(path))


EMPTY = {"title": "", "prompt": "", "branch": "", "paths": [], "said": "",
         "boss": False, "sent": [], "pending": None, "doing": ""}


def _peers(cfg):
    for path in (cfg / "sessions").glob("*.json"):
        try:
            with path.open(encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict):
            yield rec


def present(rec):
    """Is this peer record a session you could still reach?

    `alive(pid)` was the whole test, and a pid answering signal 0 is a
    weaker claim than it looks. Close the window on a running Claude and
    the process is orphaned rather than reaped: it stops the first time it
    reads from the terminal that is no longer there, and a stopped process
    answers exactly like a working one. Petra stayed on the page for
    sixteen hours that way, frozen in the status her last turn left behind
    -- `waiting`, with nobody there to be waiting.

    A session started from a terminal is over when that terminal goes.
    Headless ones never had one, so they are never asked.
    """
    pid = rec.get("pid")
    if not alive(pid):
        return False
    return not (rec.get("entrypoint") == "cli" and controlling_tty(pid) == 0)


def live_session(pid, cfg=None):
    """The peer record for a live pid, reading nothing else.

    `live()` reads every transcript to build the page; a jump only needs to
    know this pid is really a session Claude Code registered, and paying
    1.5s for that makes the click feel broken.
    """
    for rec in _peers(cfg or claude_dir()):
        if rec.get("pid") == pid and present(rec):
            return rec
    return None


def session(rec, cfg=None, light=False):
    """The facts about one live peer, with its transcript summary attached.

    `light` skips the transcript: a click only needs to know the session is
    real and where its terminal is, and must not wait for a scan.
    """
    cwd = rec.get("cwd") or ""
    sid = rec.get("sessionId") or ""
    transcript = transcript_for(sid, cwd, cfg) if sid and not light else None
    summary = scan_cached(transcript) if transcript else EMPTY
    quiet = None
    if transcript:
        try:
            quiet = (time.time() - transcript.stat().st_mtime) / 60
        except OSError:
            quiet = None
    status = rec.get("status") or "?"
    # `shell` is idle with a background job still running -- the turn is
    # over either way. The contract has no such status: it is idle, flagged.
    bg = status == "shell"
    routine = routine_of(rec, cfg)
    return {
        "id": sid,
        "name": rec.get("name") or "(unnamed)",
        "status": "idle" if bg else status,
        "bg": bg,
        "kind": rec.get("kind") or "?",
        "cwd": cwd,
        "tmux": rec.get("tmux") or "",
        "pid": rec.get("pid"),
        # Keyed to the moment it stopped, so a session that works and stops
        # again is ready once more without anything having to clear it.
        "updatedAt": rec.get("statusUpdatedAt") or rec.get("updatedAt") or 0,
        "startedAt": rec.get("startedAt") or 0,
        "routine": routine,
        "quietFor": quiet,
        "toolFor": summary["pending"] if status == "busy" else None,
        # Claude Code's own words for what it is blocked on, and the last
        # thing it said to you. Neither is generated here.
        "waitingFor": rec.get("waitingFor") or "",
        "said": summary["said"],
        "boss": summary["boss"],
        "team": summary["sent"] if summary["boss"] else [],
        # A routine is never guessed for: it belongs to the routine that
        # started it, whatever files it happens to touch on the way.
        "paths": [] if routine else summary["paths"],
        # Cheap: a session on a pty is hosted by some emulator, so a route
        # exists. Working out which one costs subprocesses, so that waits
        # until you actually click.
        "canJump": (rec.get("kind") == "interactive"
                    and on_a_terminal(rec.get("pid"))),
        "title": summary["title"],
        "prompt": summary["prompt"],
        "branch": summary["branch"],
        "doing": summary["doing"],
    }


class ClaudeProvider(Provider):
    name = "claude"
    capabilities = frozenset({"jump", "branch", "waiting", "name", "status"})

    def __init__(self, cfg=None):
        self.cfg = cfg

    def live(self):
        cfg = self.cfg or claude_dir()
        return [session(rec, cfg) for rec in _peers(cfg) if present(rec)]

    def find(self, session_id):
        cfg = self.cfg or claude_dir()
        for rec in _peers(cfg):
            if rec.get("sessionId") == session_id and present(rec):
                return session(rec, cfg, light=True)
        return None
