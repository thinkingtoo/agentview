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
from providers.minutes import (KEEP_MINUTES, STRIP_MINUTES, blank_counts as _blank_counts,
                               cold_counts as _cold_counts, count as _count,
                               minute_of as _minute_of, prune as _prune,
                               seconds_of as _seconds_of, strip as _strip)


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


MARKER_READ = 256


def boss_marker(sid, cfg=None):
    """The track a registered boss's marker names -- "" when it names none --
    or None for a session that is no boss.

    A regular file of this user, opened without following a link: the marker
    is read and checked through the one descriptor, so it cannot be swapped
    between the check and the read.
    """
    if not sid or not SID_RE.match(sid):
        return None
    path = Path(cfg or claude_dir()) / "pm" / ".boss-sessions" / sid
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            return None
        text = os.read(fd, MARKER_READ).decode("utf-8", errors="replace")
    except OSError:
        return None
    finally:
        os.close(fd)
    return (text.splitlines() or [""])[0].strip()


def is_boss(sid, cfg=None):
    """Has claude-boss registered this session?"""
    return boss_marker(sid, cfg) is not None


# How many outstanding calls to remember. Only the newest matters, but a
# message can carry several in parallel and each one deserves its place.
MAX_USES = 64

# How many of the directories a session has worked in to remember: where a
# teammate it spawns may write (`_subagent_files`).
MAX_CWDS = 8


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


def _dict(value):
    return value if isinstance(value, dict) else {}


# What Claude Code writes when the person runs a slash command, or a `!` shell
# line, at the prompt: user records, but nothing is asked of the model.
LOCAL_RECORDS = ("<local-command-caveat>", "<local-command-stdout>", "<local-command-stderr>",
                 "<command-name>", "<command-message>",
                 "<bash-input>", "<bash-stdout>", "<bash-stderr>")


def _first_words(rec):
    """The text of a user record: its string, or the first text part of a list."""
    content = _dict(rec.get("message")).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                return part["text"]
    return ""


def _local(rec):
    """Is this user record only the person using Claude Code's own commands?"""
    return rec.get("type") == "user" and _first_words(rec).lstrip().startswith(LOCAL_RECORDS)


def _api_error(rec):
    """Is this Claude Code's synthetic reply for an API error?"""
    return rec.get("type") == "assistant" and rec.get("isApiErrorMessage") is True


def _compaction(rec):
    """Is this the summary Claude Code writes when it compacts a session, by
    itself while the session is idle or at the person's /compact? A user record
    in form only: the model was asked to summarise, not to go on. (At a
    /compact the command is usually written first as an ordinary user record,
    which does open the turn; the summary after it changes nothing.)"""
    return rec.get("type") == "user" and rec.get("isCompactSummary") is True


# What a user record that nobody typed begins with, in a Claude Code that does
# not say so in `origin`: a job's notice, a teammate's message (bare, or after
# the sentence Claude Code 2.1.291 to 2.1.295 puts before it: 340 records of 14
# days), and the notice of the person's interrupt (40 records, all in list form).
NOT_TYPED = ("<task-notification>", "<teammate-message", "Another Claude session sent a message",
             "[Request interrupted by user")


def _typed(rec):
    """Is this user record the person typing at the prompt?

    A Claude Code that writes `origin` says who wrote the record: `human`, or
    `task-notification`, or `peer` (a message from another session); anything
    but `human` is a machine's, and so is a kind not yet invented. Older ones
    wrote none, and then a user record is the person's unless it is a tool's
    result, a meta record (a skill's expanded prompt, a hook's text) or one of
    the notices above.
    """
    if rec.get("type") != "user":
        return False
    origin = rec.get("origin")
    if origin is not None:
        return _dict(origin).get("kind") == "human"
    if rec.get("isMeta"):
        return False
    content = _dict(rec.get("message")).get("content")
    if isinstance(content, list) and any(
            isinstance(part, dict) and part.get("type") == "tool_result" for part in content):
        return False
    return not _first_words(rec).lstrip().startswith(NOT_TYPED)


def _synthetic(rec):
    """Is this assistant record one Claude Code wrote itself, with no model call?

    Its model is `<synthetic>`: the API errors carry it, and so does the "No
    response requested." that a resumed session gets (46 records in 5,915
    transcripts, 2 of them after an error).
    """
    return _dict(rec.get("message")).get("model") == "<synthetic>"


def _resumes(rec):
    """Does this record end an API error that was the session's last word?

    The model answering, the summary of a compaction (a model call that worked)
    or the person typing. Nothing else calls the model: a task notification or a
    message from another session waits in the queue while a rate limit holds or
    the account is logged out, a tool's result answers a call made before the
    error, and a reply Claude Code wrote itself (`_synthetic`) is not the model's.
    """
    return (rec.get("type") == "assistant" and not _synthetic(rec)) or _compaction(rec) or _typed(rec)


def _failure(state, rec):
    """Is the session's last turn an API error?

    `state["failure"]` is set by an API error that is the newest conversational
    record and cleared by `_resumes`: the model's reply (not one Claude Code
    wrote itself), a compaction, a prompt the person typed. Records Claude Code writes on its own after an error (a
    turn duration, a title, a queued line, a snapshot) are not the session
    moving on, and neither is a user record that asks the model nothing (a slash
    command run locally, a `!` line) or one that nobody typed (a notification, a
    message from another session, a tool's result, a meta prompt): the model
    has not been called again, or has not answered yet. A subagent's records
    are not the session's.
    Claude Code marks the error itself (`isApiErrorMessage`) and names it
    (`error`); a rate limit also carries the quota, with the reset time.
    """
    if rec.get("type") not in ("user", "assistant") or rec.get("isSidechain") or _local(rec):
        return
    if not _api_error(rec):
        if _resumes(rec):
            state["failure"] = None
        return
    name, status = rec.get("error"), rec.get("apiErrorStatus")
    content = _dict(rec.get("message")).get("content")
    words = next((" ".join(part["text"].split()) for part in content if isinstance(part, dict)
                  and part.get("type") == "text" and isinstance(part.get("text"), str)),
                 "") if isinstance(content, list) else ""
    seconds = _seconds_of(rec.get("timestamp"))
    quota = _dict(rec.get("quotaLimits")).get("resetsAt")
    if base.milliseconds(quota, seconds=True) is None:
        quota = _dict(_dict(rec.get("apiErrorParams")).get("rate_limit_info")).get("resetsAt")
    state["failure"] = {
        "kind": "limit" if name == "rate_limit" else "error",
        "type": name if isinstance(name, str) else "",
        "status": base.whole_number(status),
        "text": words if len(words) <= base.FAILURE_LEN else words[:base.FAILURE_LEN - 1].rstrip() + "…",
        "at": None if seconds is None else int(seconds * 1000),
        "resetsAt": base.milliseconds(quota, seconds=True)}


# The system records that end a turn: the summary of the stop hooks, and the
# turn's duration. A stop hook may send the session on, and then the model
# speaks again within seconds (455 of the 8,648 summaries on this machine, the
# longest wait 15 s), which opens the turn again.
TURN_ENDS = ("turn_duration", "stop_hook_summary")


def _turn(state, rec):
    """Is the session's last word the end of a turn?

    `state["over"]` is set by a turn-end record the session itself wrote, or by
    an API error that is its reply (the model could not answer; Claude Code
    writes a turn end after most of these, not after all, so the error itself
    ends the turn), and cleared by anything that asks the model something (a
    prompt, a message to it, a tool result, its own reply) -- except while an
    API error is still the session's last word. `_failure` runs first and has
    then left `state["failure"]` set, and only what clears the error opens the
    turn again: a notification or a message from another session does not call
    the model.
    Bookkeeping, a notice, a user record that asks the model nothing (a slash
    command run locally) and the summary of a compaction leave it as it is. A
    subagent's records are not the session's.

    The peer registry may go on saying `busy` once a turn is over -- it does for
    a session that has teammates, until the session ends -- so this is what
    tells a lead that finished from one that is working.
    """
    if rec.get("isSidechain"):
        return
    kind = rec.get("type")
    if kind == "system":
        if rec.get("subtype") in TURN_ENDS:
            state["over"] = True
    elif kind in ("user", "assistant") and not _local(rec) and not _compaction(rec):
        state["over"] = state["failure"] is not None


def _places(state, rec):
    """The directories the session has worked in, the newest last. A session
    that moves keeps its transcript in the folder it started in, and a teammate
    it spawns later writes in the folder of the directory it was in then."""
    cwd = rec.get("cwd")
    if not isinstance(cwd, str) or not cwd or rec.get("isSidechain"):
        return
    state["cwds"].pop(cwd, None)
    state["cwds"][cwd] = True
    while len(state["cwds"]) > MAX_CWDS:
        del state["cwds"][next(iter(state["cwds"]))]


def _blank_state():
    return {**_blank_counts(),
            "failure": None, "tool": None, "over": False, "cwds": {},
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
        _failure(state, rec)
        _turn(state, rec)
        _places(state, rec)
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
                called, kept = part.get("name") or "", _kept(part.get("input"), part.get("name") or "")
                if part.get("id"):
                    state["uses"][part["id"]] = (rec.get("timestamp"), called, kept, mid)
                # The newest call the session itself made, answered or not.
                if (kind == "assistant" and not rec.get("isSidechain")
                        and _seconds_of(rec.get("timestamp")) is not None):
                    state["tool"] = (rec["timestamp"], called, kept)
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
            "failure": dict(state["failure"]) if state["failure"] else None,
            "lastTool": _last_tool(state["tool"]),
            # Whether its last word was the end of a turn, and the directories
            # it has worked in (oldest first): what the registry cannot say.
            "turnOver": state["over"],
            "cwds": list(state["cwds"]),
            "writes": _strip(state, now),
            # Open background shells, oldest first, with how long each has run.
            "tasks": sorted(({"id": tid, "label": t["label"],
                              "since": max(0.0, (now - started) / 60)}
                             for tid, t in state["tasks"].items()
                             if (started := _seconds_of(t["stamp"])) is not None),
                            key=lambda t: -t["since"])}


def _last_tool(call):
    """The newest call, said the way `doing` says one, and when it was made."""
    if not call:
        return None
    return {"text": activity([(call[1], call[2])]) or "a tool",
            "at": int(_seconds_of(call[0]) * 1000)}


def _entries(folder):
    try:
        return list(os.scandir(folder))
    except OSError:
        return []


# A named teammate does not write under the session's folder. It writes a
# transcript of its own beside the session's, and its first message says whose
# team it is in: `teamName: session-<first 8 characters of the session's id>`.
# What team a file is in is read once, from its first lines, and kept.
TEAM_LINES = 24
MAX_TEAMS = 4096
_UNDECIDED = object()
_teams = {}


def _team_of(path):
    """The team a transcript says it is in, in its first message: its name; None
    for a session of its own; `_UNDECIDED` while the file has no message yet."""
    try:
        with open(path, "rb") as fh:
            for _ in range(TEAM_LINES):
                line = fh.readline()
                if not line:
                    return _UNDECIDED
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("type") in ("user", "assistant"):
                    team = rec.get("teamName")
                    return team if isinstance(team, str) else None
    except OSError:
        return _UNDECIDED
    return None


def _team(entry, now):
    """The team of a transcript beside the session's. A file is looked into
    while it is being written, which is how a teammate is met; one first seen
    untouched for longer than the strip shows is not looked into at all, so
    the many old transcripts in a project folder cost a stat and no more."""
    key = (entry.path, entry.inode())
    if key in _teams:
        return _teams[key]
    try:
        if (now - entry.stat().st_mtime) / 60 > KEEP_MINUTES:
            return None
    except OSError:
        return None
    team = _team_of(entry.path)
    if team is _UNDECIDED:
        return None
    if len(_teams) >= MAX_TEAMS:
        _teams.clear()
    _teams[key] = team
    return team


def _subagent_files(path, now, cwds=()):
    """The transcripts the session's subagents write. A background agent writes
    `<session>/subagents/agent-*.jsonl`, the agents of a workflow one folder
    deeper, `<session>/subagents/workflows/<run>/agent-*.jsonl`, and a named
    teammate a transcript of its own in the session's project folder -- or in
    the project folder of a directory the session has since moved to (`cwds`)."""
    found = []
    for entry in _entries(path.with_suffix("") / "subagents"):
        if entry.name == "workflows" and entry.is_dir():
            for run in _entries(entry.path):
                if run.is_dir():
                    found.extend(e for e in _entries(run.path) if e.name.endswith(".jsonl"))
        elif entry.name.endswith(".jsonl"):
            found.append(entry)
    team = f"session-{path.stem[:8]}"
    folders = [path.parent]
    for cwd in cwds:
        folder = path.parent.parent / registry._encode(cwd)
        if folder not in folders:
            folders.append(folder)
    for folder in folders:
        found.extend(e for e in _entries(folder)
                     if e.name.endswith(".jsonl") and e.name != path.name and _team(e, now) == team)
    return found


def _subagents(path, now, cwds=()):
    """The session's subagents: their transcript states, and how many minutes
    ago the newest of them wrote (None when it has none).

    They are files under the session's own folder, so they are read here, as
    part of the session they work for, and are never sessions of their own:
    nothing lists them as peers. A file untouched for longer than the strip
    shows cannot add to it, and is not even opened.
    """
    states, quiet = [], None
    for entry in _subagent_files(path, now, cwds):
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
    subs, view["subQuiet"] = _subagents(path, now, view["cwds"])
    for state in subs:
        view["writes"] = _add(view["writes"], _strip(state, now))
    return view


EMPTY = {"title": "", "prompt": "", "branch": "", "paths": [], "said": "",
         "sent": [], "pending": None, "doing": "", "writes": None, "subQuiet": None, "tasks": [],
         "calls": [], "failure": None, "lastTool": None, "turnOver": False, "cwds": []}


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

    `unread` is whether `/proc` could not say: it would not answer, or this is
    the first look at a command and there is nothing to compare its CPU with.
    Then "no CPU" is not "uses none", and a caller that wants to call the
    session hung must wait for a look that can tell. `cpu_ago` is how many
    minutes ago CPU was last seen moving, whether or not it moves now.
    """
    nothing = {"tasks": [], "cpu": False, "cpu_ago": None, "unread": False}
    tasks = summary["tasks"]
    if shells is None or not rec.get("pid") or not (
            tasks or (status == "busy" and summary["pending"] is not None)):
        return nothing
    seen = shells.look(rec["pid"])
    if seen is None:
        return {**nothing, "unread": True}
    return {"tasks": [t for t in tasks if t["id"] in seen["tasks"]], "cpu": seen["cpu"] is True,
            "cpu_ago": shells.cpu_ago(rec["pid"]), "unread": seen["cpu"] is None}


# The one word Claude Code uses for a `waiting` session that is not asking the
# person anything: a menu or panel they opened themselves. Every other word it
# writes (input needed, permission prompt, sandbox request, worker request,
# goal proposal) waits on an answer or an approval.
MENUS = ("dialog open",)

# A dialog Claude Code raises itself, and that waits on the person, says
# `dialog open` too, but writes a `needs` text beside it (read out of 2.1.295's
# own dialog table, 2026-10-19). These are the texts it has, by the kind each
# is counted under; a text not here is `other`. `usage` is "Session paused" for
# usage credits, the one that is a limit and not a thing to decide.
DIALOG_KINDS = {
    "choose: continue on usage credits or switch models": "usage",
    "choose: retry on fallback model or edit prompt": "fallback",
    "acknowledge the classifier billing notice (enter continues in auto mode)": "billing",
    "choose: run ultraplan in the cloud": "ultraplan",
    "choose: make auto mode the default permission mode": "auto mode",
}
USAGE = "usage"


def dialog_needs(status, waiting_for, needs):
    """What a dialog that says it is open waits on, as the words it wrote in
    `needs`, or None: a menu the person opened has none, and a `needs` beside
    anything else is not read (another process writes it too, for a session
    that is not in a dialog at all)."""
    if status != "waiting" or not isinstance(waiting_for, str) or waiting_for.strip().lower() not in MENUS:
        return None
    if not isinstance(needs, str):
        return None
    return " ".join(needs.split()) or None


def dialog_kind(words):
    """The kind of dialog its `needs` words belong to, as a short label to count
    under: one of `DIALOG_KINDS`' kinds, or `other`. Never the words themselves."""
    return DIALOG_KINDS.get(words.lower(), "other")


def asking_of(status, waiting_for, calls, needs):
    """The dialog a session has open, or None: what Claude Code says is open
    (the peer record's status, `waitingFor` and `needs`) and what the
    transcript says it is about (the calls that have not come back).

    A question is Claude Code's `input needed`, with the unanswered
    AskUserQuestion as its content. Claude Code writes that call into the
    transcript late -- minutes after the dialog opens, sometimes hours -- so
    until the read finds it the question is open with nothing to show
    (`questions` empty), and fills in on the read that does. A permission
    prompt is Claude Code's own `permission prompt`, about the oldest call
    still waiting -- a running call is not one, and a menu (`dialog open`) is
    neither. Any other word it names is a request waiting on the person (a
    sandbox asking for the network, a teammate's worker, a goal it proposes),
    and is told by that word; a word this reader has not met is one too, since
    Claude Code only says `waiting` when it waits on someone. A menu
    (`dialog open`) is told by its `needs` text when it has one, and a dialog
    that is open on usage credits is a `pause` and not a request: it is a limit.
    """
    if status != "waiting":
        return None
    for name, inp in calls:
        if name == "AskUserQuestion" and inp.get("questions"):
            return {"kind": "question", "questions": inp["questions"]}
    if waiting_for == "input needed":
        return {"kind": "question", "questions": []}
    if waiting_for != "permission prompt":
        word = waiting_for.strip() if isinstance(waiting_for, str) else ""
        if word.lower() in MENUS:
            words = dialog_needs(status, word, needs)
            if words is None:
                return None
            return {"kind": "pause" if dialog_kind(words) == USAGE else "request", "what": words}
        return {"kind": "request", "what": word} if word else None
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
    track = boss_marker(sid, cfg)
    boss = track is not None
    under = _processes(rec, summary, status, shells)
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
        "asking": asking_of(status, rec.get("waitingFor") or "", summary["calls"], rec.get("needs")),
        "said": summary["said"],
        "boss": boss,
        # The name of the boss's tracker, which is the project its workers
        # share. Read from the marker; the core falls back to the pane's name
        # when the marker names none.
        "track": track or "",
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
        "bgTasks": under["tasks"],
        "shellCpu": under["cpu"],
        "shellCpuAgo": under["cpu_ago"],
        "procsUnknown": under["unread"],
        # An API error as the newest thing the session said, and the last
        # call it made: what Limit, Error and Hung are told from.
        "failure": summary["failure"],
        "lastTool": summary["lastTool"],
        # Its last word ended a turn, whatever the registry says it is doing.
        "turnOver": summary["turnOver"],
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
