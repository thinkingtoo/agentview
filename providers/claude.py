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
import stat
import time
from pathlib import Path

import lines
from providers import base, procs, registry
from providers.base import (Provider, Tailed, on_a_terminal,
                            read_from as _read_from)


def claude_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))


def helper_dir(cfg=None):
    """Where agentview runs its own `claude -p` helpers: the conversation
    summaries. A folder of their own keeps their transcripts out of every
    project's, and tells the page which sessions are not sessions."""
    return Path(cfg or claude_dir()) / "agentview" / "summaries"


def is_helper(rec, cfg=None):
    """A peer record that is one of agentview's own helper runs. A helper is
    headless and lives in `helper_dir`, for as long as one model call takes.
    Someone at a terminal who happens to sit there is still a session."""
    cwd = rec.get("cwd")
    if rec.get("entrypoint") == "cli" or not isinstance(cwd, str) or not cwd:
        return False
    try:
        return Path(cwd).resolve() == helper_dir(cfg).resolve()
    except (OSError, RuntimeError):
        return False


def transcript_for(session_id, cwd, cfg=None):
    """Locate a session's transcript: the registry's rule, by id and cwd."""
    return registry.transcript_of({"sessionId": session_id, "cwd": cwd}, cfg or claude_dir())


def last_title(path):
    """The newest ai-title record, else the last prompt. Found from the end of
    the file: parsing a 20 MB transcript whole held the poll for seconds.

    The closed list and the conversation archive both name a conversation
    with this, so the two never disagree about what one was called."""
    if not path:
        return ""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return ""
    for marker, field in ((b'"type":"ai-title"', "aiTitle"), (b'"type":"last-prompt"', "lastPrompt")):
        at = len(raw)
        # The newest record can be empty; walk back to one that says something.
        while (at := raw.rfind(marker, 0, at)) >= 0:
            start, end = raw.rfind(b"\n", 0, at) + 1, raw.find(b"\n", at)
            try:
                text = json.loads(raw[start:end if end >= 0 else None]).get(field) or ""
            except ValueError:
                text = ""
            if isinstance(text, str) and text.strip():
                return " ".join(text.split())[:120]
    return ""


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

# claude-boss marks a boss with `pm/.boss-sessions/<session id>`, and its
# hooks act on that file alone. Reading the same file keeps the badge honest:
# a transcript that typed `/boss` never registered, and a boss that did is
# one whether its `/boss` sits in the tail or megabytes back.
SID_RE = re.compile(r"^[\w-]{1,80}$")


def is_boss(sid, cfg=None):
    """Has claude-boss registered this session? A regular file of this user."""
    if not sid or not SID_RE.match(sid):
        return False
    try:
        st = os.lstat(Path(cfg or claude_dir()) / "pm" / ".boss-sessions" / sid)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()


# How many outstanding calls to remember. Only the newest matters, but a
# message can carry several in parallel and each one deserves its place.
MAX_USES = 64


# Movement is counted per minute, 30 of them, as the records go by. A minute
# is a whole number of minutes since the epoch; the strip is read off it.
STRIP_MINUTES = 30
KEEP_MINUTES = STRIP_MINUTES + 10


def _seconds_of(stamp):
    try:
        return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError, OverflowError):
        return None


def _minute_of(stamp):
    seconds = _seconds_of(stamp)
    return None if seconds is None else int(seconds // 60)


def _blank_counts():
    # `seen_from` is the first minute this reader saw from its beginning. 0
    # means the file was read from the top, so every minute is known; a larger
    # number means a cold start began mid-file, and earlier minutes are
    # unknown rather than empty.
    return {"offset": 0, "ino": None, "head": b"",
            "minutes": collections.Counter(), "first": None, "seen_from": 0}


def _count(state, rec):
    """One more write, in the minute its record is stamped with. A record with
    no stamp (a title, a mode switch) is bookkeeping, not the session at work."""
    minute = _minute_of(rec.get("timestamp"))
    if minute is None:
        return
    state["minutes"][minute] += 1
    if state["first"] is None or minute < state["first"]:
        state["first"] = minute


def _prune(state):
    """Minutes the strip can no longer show are not kept. Measured from the
    newest write, not the clock, so a session quiet for a day keeps its last
    few minutes and nothing older."""
    minutes = state["minutes"]
    if minutes:
        edge = max(minutes) - KEEP_MINUTES
        for minute in [m for m in minutes if m < edge]:
            del minutes[minute]


def _cold_counts(state):
    """The first sight of a big file read only its tail. The first minute in
    that tail may be cut short, so what is known starts one minute after it."""
    first = state["first"]
    state["seen_from"] = (first + 1 if first is not None
                          else int(time.time() // 60) + 1)


def _strip(state, now):
    """30 per-minute write counts, oldest first, newest (this minute) last.
    None where this reader was not yet looking."""
    newest = int(now // 60)
    return [None if minute < state["seen_from"] else state["minutes"].get(minute, 0)
            for minute in range(newest - STRIP_MINUTES + 1, newest + 1)]


# Background commands the session started and has not been told are over.
# Only an id that starts with `b` is a shell task (a background Bash, or a
# Monitor); an `a` is a background agent, whose evidence is its own transcript.
MAX_TASKS = 32
TASK_ID = re.compile(r"<task-id>([^<]+)</task-id>")
TASK_STATUS = re.compile(r"<status>(completed|failed|killed|stopped)</status>")


def _tasks(state, rec):
    """Open and close background tasks from one record.

    A task opens when a tool result hands back its id. It closes when the
    session is told it ended (a task-notification, which reaches the file as
    a queued command, an attachment or a typed turn) or when it stops it
    itself. A notice quoted inside a tool result is somebody else's text, not
    the session being told.
    """
    tasks = state["tasks"]
    result = rec.get("toolUseResult")
    if isinstance(result, dict):
        stopped = result.get("task_id")
        if isinstance(stopped, str):
            tasks.pop(stopped, None)
        opened = result.get("backgroundTaskId") or result.get("taskId")
        stamp = rec.get("timestamp")
        if (isinstance(opened, str) and opened.startswith("b")
                and isinstance(stamp, str) and opened not in tasks):
            label = "a background job"
            content = (rec.get("message") or {}).get("content")
            for part in content if isinstance(content, list) else ():
                call = state["uses"].get(part.get("tool_use_id")) if isinstance(part, dict) else None
                if call:
                    label = activity([(call[1], call[2])]) or label
                    break
            tasks[opened] = {"stamp": stamp, "label": label}
            while len(tasks) > MAX_TASKS:
                del tasks[next(iter(tasks))]
    kind = rec.get("type")
    if kind == "queue-operation":
        text = rec.get("content")
    elif kind == "attachment":
        text = (rec.get("attachment") or {}).get("prompt")
    elif kind == "user":
        text = (rec.get("message") or {}).get("content")
    else:
        text = None
    if isinstance(text, str) and "<task-id>" in text:
        for notice in text.split("</task-notification>"):
            task, status = TASK_ID.search(notice), TASK_STATUS.search(notice)
            if task and status:
                tasks.pop(task.group(1), None)


def _blank_state():
    return {**_blank_counts(),
            "title": "", "prompt": "", "branch": "", "tasks": {},
            "uses": {}, "done": set(), "said": "", "spoke": "", "msg": "",
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
        _count(state, rec)
        _tasks(state, rec)
        kind = rec.get("type")
        if kind == "ai-title" and rec.get("aiTitle"):
            state["title"] = rec["aiTitle"]
        elif kind == "last-prompt" and rec.get("lastPrompt"):
            state["prompt"] = rec["lastPrompt"]
        branch = rec.get("gitBranch")
        if branch and branch != "HEAD":
            state["branch"] = branch
        content = (rec.get("message") or {}).get("content")
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
        # The message these records belong to: a message's calls are written
        # as one record each, and a result for one of them is not the session
        # moving on from the others.
        mid = (rec.get("message") or {}).get("id")
        mid = mid if isinstance(mid, str) else ""
        if kind == "assistant" and not rec.get("isSidechain"):
            state["msg"] = mid
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
                        _kept(part.get("input"), part.get("name") or ""), mid)
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
    _prune(state)
    return state


def _cold(state, path):
    """What the tail of a big transcript cannot answer, read once."""
    _cold_counts(state)
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


def _absorb_counts(state, text):
    """A subagent's file: nothing is read out of it but when it wrote."""
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            _count(state, rec)
    _prune(state)
    return state


TAIL = Tailed(_blank_state, _absorb, _cold)
_cache = TAIL.cache
SUBS = Tailed(_blank_counts, _absorb_counts, lambda state, path: _cold_counts(state))


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


def _kept(inp, name=""):
    if not isinstance(inp, dict):
        return {}
    kept = {k: v[:200] for k, v in inp.items()
            if k in KEEP and isinstance(v, str)}
    # Two calls are what a person may be asked about, so they keep what the
    # person needs to read: a shell command whole (a prompt shows it, and it
    # is copied), and a question with its options. Both bounded.
    if name == "Bash" and isinstance(inp.get("command"), str):
        kept["command"] = inp["command"][:base.COMMAND_LIMIT + 1]
    elif name == "AskUserQuestion":
        kept["questions"] = _questions(inp.get("questions"))
    return kept


def _questions(value):
    """An AskUserQuestion's questions, as the page reads them and no longer
    than a tile holds."""
    def words(v, limit):
        return v.strip()[:limit] if isinstance(v, str) else ""

    out = []
    for q in value[:base.MAX_QUESTIONS] if isinstance(value, list) else ():
        if not isinstance(q, dict) or not words(q.get("question"), base.QUESTION_LEN):
            continue
        out.append({
            "question": words(q.get("question"), base.QUESTION_LEN),
            "header": words(q.get("header"), base.LABEL_LEN),
            "multi": q.get("multiSelect") is True,
            "options": [{"label": words(o.get("label"), base.LABEL_LEN),
                         "description": words(o.get("description"), base.HINT_LEN)}
                        for o in q["options"][:base.MAX_OPTIONS]
                        if isinstance(o, dict)]
                       if isinstance(q.get("options"), list) else [],
        })
    return out


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


def _view(state, now):
    # Only calls in the session's newest message. An unanswered call the
    # session has since talked past is not running -- and because this file
    # is read incrementally, it would otherwise be remembered forever and
    # flag the session `tool 40m` on every busy poll for the rest of the day.
    running = [call for tid, call in state["uses"].items()
               if tid not in state["done"] and call[0] and call[0] >= state["spoke"]]
    # What it has asked and not been answered in its newest message, oldest
    # first: the calls a dialog can be about.
    asked = [(call[1], call[2]) for tid, call in state["uses"].items()
             if tid not in state["done"] and call[3] == state["msg"]]
    stamps = [call[0] for call in running]
    pending = None
    if stamps:
        try:
            started = max(datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
                          for s in stamps)
            current = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
            pending = max(0.0, (current - started).total_seconds() / 60)
        except ValueError:
            pending = None
    return {"title": state["title"], "prompt": state["prompt"],
            "branch": state["branch"], "paths": list(state["paths"]),
            # The raw last message: the core shapes it into the one line the
            # card shows, and reads the ask out of the whole of it.
            "said": state["said"],
            "doing": activity([(call[1], call[2]) for call in running]),
            # Liveliest correspondent first: a boss's team, in the order it
            # actually deals with them.
            "sent": [name for name, _ in state["sent"].most_common()],
            "pending": pending,
            "calls": asked,
            "writes": _strip(state, now),
            # Open background shells, oldest first, with how long each has run.
            "tasks": sorted(({"id": tid, "label": t["label"],
                              "since": max(0.0, (now - started) / 60)}
                             for tid, t in state["tasks"].items()
                             if (started := _seconds_of(t["stamp"])) is not None),
                            key=lambda t: -t["since"])}


def _subagents(path, now):
    """The session's subagents: their transcript states, and how many minutes
    ago the newest of them wrote (None when it has none).

    They are files under the session's own folder, so they are read here, as
    part of the session they work for, and are never sessions of their own:
    nothing lists them as peers. A file untouched for longer than the strip
    shows cannot add to it, and is not even opened.
    """
    folder = path.with_suffix("") / "subagents"
    states, quiet = [], None
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return states, quiet
    for entry in entries:
        if not entry.name.endswith(".jsonl"):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        age = max(0.0, (now - mtime) / 60)
        quiet = age if quiet is None else min(quiet, age)
        if age > KEEP_MINUTES:
            SUBS.cache.pop(("state", entry.path), None)
            continue
        states.append(SUBS.scan(Path(entry.path)))
    return states, quiet


def _add(strip, other):
    """Two strips summed, minute by minute. A minute either of them did not
    see is a minute nobody saw."""
    return [None if a is None or b is None else a + b for a, b in zip(strip, other)]


def scan_cached(path, now=None):
    """What the page needs from a transcript, reading only what is new."""
    try:
        path.stat()
    except OSError:
        return dict(EMPTY)
    return _view(TAIL.scan(path), time.time() if now is None else now)


def scan_session(path, now=None):
    """A live session's transcript, and its subagents' writes counted in. The
    archive only wants a title and calls `scan_cached`; looking into a
    subagent folder is for a session that is running."""
    view = scan_cached(path, now)
    if view["writes"] is None:
        return view
    now = time.time() if now is None else now
    subs, view["subQuiet"] = _subagents(path, now)
    for state in subs:
        view["writes"] = _add(view["writes"], _strip(state, now))
    return view


EMPTY = {"title": "", "prompt": "", "branch": "", "paths": [], "said": "",
         "sent": [], "pending": None, "doing": "", "writes": None, "subQuiet": None, "tasks": [],
         "calls": []}


def _peers(cfg):
    """Every peer record, live or not. `registry.live()` is the live ones."""
    return registry.records(cfg)


def _str(rec, key):
    """A peer file field that must be text, or "" -- a hand-edited or newer
    file with something else in it must not be able to stop a poll."""
    got = rec.get(key)
    return got if isinstance(got, str) else ""


def reach(rec, proc="/proc", running=None, rivals=()):
    """How a click gets to this session: `canJump`, `jobId`, `attach`, `noJump`.

    A session at a terminal has a pane to raise. A background session
    (`claude --bg`) has none of its own: what shows it is a `claude attach`
    in some window, so it is that window's pane when there is one, and
    otherwise a new tab that attaches (`attach` is the job id then). One
    attached somewhere nothing can raise, or by a name another session has
    too, is neither: attaching again could put two windows on one
    conversation, so `noJump` says why.
    """
    # Imported here: jump -> scope -> log -> this module would be a cycle.
    import jump
    way = {"canJump": False, "jobId": "", "attach": "", "noJump": ""}
    if rec.get("kind") != "bg":
        way["canJump"] = rec.get("kind") == "interactive" and on_a_terminal(rec.get("pid"), proc)
        return way
    job = rec.get("jobId")
    if not jump.is_job(job):
        return way
    way["jobId"] = job
    sid, name = _str(rec, "sessionId"), _str(rec, "name")
    running = jump.attaches(proc) if running is None else running
    shown = jump.viewers(job, sid, name, proc, running, rivals)
    if not shown and jump.doubtful(job, sid, name, proc, running, rivals):
        way["noJump"] = jump.MAY_BE_SHOWN
    elif not shown:
        way["attach"] = job
    elif any(on_a_terminal(pid, proc) for pid in shown):
        way["canJump"] = True
    else:
        way["noJump"] = "attached, but in no window that can be raised"
    return way


def _processes(rec, summary, status, shells):
    """Open background shells and CPU under the session, from `/proc`.

    Only looked at when the session has something a process could belong to:
    a call that has not come back, or a background task it was not told had
    ended. A session with neither has nothing to wait on, and a shell burning
    CPU under it is somebody else's. A task counts only while the shell that
    writes to its own output file is alive: a task whose shell died and sent
    no notice (the session was resumed, say) is not running, and another
    command's shell does not make it so.
    """
    tasks = summary["tasks"]
    if shells is None or not rec.get("pid") or not (
            tasks or (status == "busy" and summary["pending"] is not None)):
        return [], False
    seen = shells.look(rec["pid"])
    if seen is None:
        return [], False
    return [t for t in tasks if t["id"] in seen["tasks"]], seen["cpu"]


def asking_of(status, waiting_for, calls):
    """The dialog a session has open, or None: what Claude Code says is open
    (the peer record's status and `waitingFor`) and what the transcript says
    it is about (the calls that have not come back).

    A question is an unanswered AskUserQuestion while the session is waiting.
    A permission prompt is Claude Code's own `permission prompt`, about the
    oldest call still waiting -- a running call is not one, and a menu
    (`dialog open`) is neither.
    """
    if status != "waiting":
        return None
    for name, inp in calls:
        if name == "AskUserQuestion" and inp.get("questions"):
            return {"kind": "question", "questions": inp["questions"]}
    if waiting_for != "permission prompt":
        return None
    name, inp = calls[0] if calls else ("", {})
    target = inp.get(TARGET.get(name, ""))
    return {"kind": "permission", "tool": name,
            # Only a shell command is a command. Another tool may well have a
            # field called that, and what it holds is not for a terminal.
            "command": inp.get("command", "") if name == "Bash" else "",
            "target": target if isinstance(target, str) and name != "Bash" else ""}


def session(rec, cfg=None, light=False, shells=None, proc="/proc", running=None, rivals=()):
    """The facts about one live peer, with its transcript summary attached.

    `light` skips the transcript: a click only needs to know the session is
    real and where its terminal is, and must not wait for a scan.
    """
    cwd = rec.get("cwd") or ""
    sid = rec.get("sessionId") or ""
    transcript = transcript_for(sid, cwd, cfg) if sid and not light else None
    summary = scan_session(transcript) if transcript else EMPTY
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
    boss = is_boss(sid, cfg)
    background, cpu = _processes(rec, summary, status, shells)
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
        "asking": asking_of(status, rec.get("waitingFor") or "", summary["calls"]),
        "said": summary["said"],
        "boss": boss,
        "team": summary["sent"] if boss else [],
        # A routine is never guessed for: it belongs to the routine that
        # started it, whatever files it happens to touch on the way.
        "paths": [] if routine else summary["paths"],
        # Cheap: a session on a pty is hosted by some emulator, so a route
        # exists. Working out which one costs subprocesses, so that waits
        # until you actually click.
        **reach(rec, proc, running, rivals),
        "title": summary["title"],
        "prompt": summary["prompt"],
        "branch": summary["branch"],
        "doing": summary["doing"],
        # Movement: writes per minute (own and subagents', oldest first, None
        # where unseen), minutes since a subagent wrote, open background
        # tasks with a live shell behind them, and CPU under a shell.
        "writes": summary["writes"],
        "subQuiet": summary["subQuiet"],
        "bgTasks": background,
        "shellCpu": cpu,
    }


def _rivals(rec, live):
    """The names of the other background sessions, so that a fragment of a
    name both share is not taken for either."""
    return [_str(r, "name") for r in live
            if r.get("kind") == "bg" and r.get("pid") != rec.get("pid")]


class ClaudeProvider(Provider):
    name = "claude"
    capabilities = frozenset({"jump", "branch", "waiting", "name", "status"})

    def __init__(self, cfg=None, proc="/proc"):
        self.cfg = cfg
        self.proc = proc
        self.shells = procs.Shells(proc)

    def live(self):
        cfg = self.cfg or claude_dir()
        recs = [rec for rec in registry.live(cfg, self.proc) if not is_helper(rec, cfg)]
        # Who is attached to a background session is read once for the poll.
        running = None
        if any(rec.get("kind") == "bg" for rec in recs):
            import jump
            running = jump.attaches(self.proc)
        return [session(rec, cfg, shells=self.shells, proc=self.proc, running=running,
                        rivals=_rivals(rec, recs) if rec.get("kind") == "bg" else ())
                for rec in recs]

    def find(self, session_id):
        cfg = self.cfg or claude_dir()
        rec = registry.by_sid(session_id, cfg, self.proc)
        if rec and registry.is_live(rec, self.proc):
            rivals = _rivals(rec, registry.live(cfg, self.proc)) if rec.get("kind") == "bg" else ()
            return session(rec, cfg, light=True, proc=self.proc, rivals=rivals)
        return None

    def jump(self, session):
        """A background session is attached to; every other is the core's pane search."""
        if session.get("kind") != "bg":
            return None
        import jump
        # The record's own name, not the page's "(unnamed)" stand-in for none.
        cfg = self.cfg or claude_dir()
        rec = registry.by_sid(session.get("id") or "", cfg, self.proc) or {}
        return jump.attach(session.get("jobId") or "", sid=_str(rec, "sessionId"),
                           name=_str(rec, "name"), proc=self.proc,
                           rivals=_rivals(rec, registry.live(cfg, self.proc)))
