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

import lines
import seen


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


def _head(path):
    """The first bytes of the file, as a cheap identity for its contents."""
    try:
        with path.open("rb") as fh:
            return fh.read(HEAD_BYTES)
    except OSError:
        return b""


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


SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
NOT_PROSE = ("|", "#", ">", "```", "---")


def last_words(text, limit=140):
    """The sentence a session left you with, fit to read at a glance.

    The last line rather than the first: a turn opens with what it did and
    ends with what it wants. Tables, headings and code blocks are not
    something anyone was told, so they are skipped rather than quoted.
    """
    if not text:
        return ""
    body = re.sub(r"```.*?```", " ", text, flags=re.S)
    lines = [line.strip() for line in body.splitlines()]
    lines = [line for line in lines if line and not line.startswith(NOT_PROSE)]
    if not lines:
        return ""
    line = re.sub(r"^[-*+]\s+", "", lines[-1])      # a bullet is still a sentence
    line = re.sub(r"[*_`]+", "", line)
    if len(line) > limit:
        tail = SENTENCE_END.split(line)[-1]
        line = tail if len(tail) <= limit else line[:limit - 1].rstrip() + "\u2026"
    return line


ASK_LIMIT = lines.LIMIT
FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`]*`")
PARA = re.compile(r"\n\s*\n")
LEADING = re.compile(r"^[^\w(\u00ab\"']+")


def ask_from(text):
    """What the last thing a session said wants from you: the ask, and how many.

    Counted by paragraph, not by question mark. A question that spells its
    own options out carries two marks and is still one question -- the round
    of this conversation that asked Q1, Q2 and Q3 has four marks in it.

    Conservative on purpose. It finds a question and nothing else: an
    imperative that plainly wants an answer ("Dis-moi : A, B, ou C.") reads
    here as no ask at all. That is the miss the Stop hook exists to cover --
    it blocks when nothing was found and lets the session say what it wants
    in its own words. Guessing instead would flag every message with a colon
    in it, and a card that claims to want you and does not is the one failure
    that teaches you to stop believing the page.
    """
    if not text:
        return ("", 0)
    asking = []
    for para in PARA.split(FENCE.sub(" ", text)):
        # A quoted line is someone else talking, and a table row is data.
        keep = [ln for ln in para.splitlines()
                if ln.strip() and not ln.lstrip().startswith((">", "|"))]
        if not keep:
            continue
        # `grep -c "?"` is code, not a question.
        clean = INLINE_CODE.sub(" ", " ".join(keep))
        if "?" in clean:
            asking.append(clean)
    if not asking:
        return ("", 0)
    if len(asking) > 1:
        return ("", len(asking))
    one = asking[0]
    sentence = SENTENCE_END.split(one[:one.rindex("?") + 1])[-1].strip()
    sentence = re.sub(r"^[-*+]\s+", "", sentence)
    sentence = re.sub(r"[*_`#]+", "", sentence)
    sentence = LEADING.sub("", sentence).strip()
    if len(sentence) > ASK_LIMIT:
        sentence = sentence[:ASK_LIMIT - 1].rstrip() + "\u2026"
    return (sentence, 1)


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
    return text if len(text) <= ASK_LIMIT else text[:ASK_LIMIT - 1].rstrip() + "\u2026"


def own_line(session_id, status, asked, root=None, said="", doing=""):
    """The two lines a card shows, and whether the session is stopped on you.

    The session writes its own when it finishes -- it is the only thing that
    knows where the work stands. Everything else here is what to show until
    it has: the ask read out of the last thing it said.

    A read ask fills the words and does not raise the count. Extraction can
    see a question; it cannot tell one that stops the session from one that
    offers to do more, and a tab that says (6) has to mean six.
    """
    if status == "busy":
        # The prompt that restarted it is the answer to what it asked. A
        # need kept past that point makes the page lie at the next stop.
        lines.drop(session_id, root)
        # Between calls there is nothing in flight and the model is writing.
        # The page used to print your own last prompt back at you there --
        # words you wrote and already know.
        return {"did": "", "ask": "", "n": 0, "blocked": False,
                "doing": doing or last_words(said)}
    got = lines.read(session_id, root)
    if got:
        return {"did": got["did"], "ask": got["ask"], "n": got["n"],
                "blocked": got["n"] > 0, "doing": ""}
    ask, n = asked
    return {"did": "", "ask": ask, "n": n, "blocked": False, "doing": ""}


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
            "said": last_words(state["said"]), "boss": state["boss"],
            "doing": activity([(name, inp) for _, name, inp in running]),
            # Read once here, where the whole of the last message is: `said`
            # above is only its closing line.
            "asked": ask_from(state["said"]),
            # Liveliest correspondent first: a boss's team, in the order it
            # actually deals with them.
            "sent": [name for name, _ in state["sent"].most_common()],
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
        if not state["boss"]:
            state["boss"] = _boss_file(path)
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
    marks = seen.load()
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
            "title": "", "prompt": "", "branch": "", "paths": [], "said": "",
            "boss": False, "sent": [], "pending": None, "doing": "",
            "asked": ("", 0)}
        quiet = None
        if transcript:
            try:
                quiet = (time.time() - transcript.stat().st_mtime) / 60
            except OSError:
                quiet = None
        in_flight = summary["pending"] if rec.get("status") == "busy" else None
        status_since = rec.get("statusUpdatedAt") or rec.get("updatedAt") or 0
        status = rec.get("status") or "?"
        # Keyed to the moment it stopped, so a session that works and stops
        # again is ready once more without anything having to clear it.
        unseen = seen.ready(sid, rec.get("statusUpdatedAt"), marks)
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
            "status": status,
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
            # Claude Code's own words for what it is blocked on, and the last
            # thing it said to you. Neither is generated here.
            "waitingFor": rec.get("waitingFor") or "",
            "said": summary["said"],
            "boss": summary["boss"],
            "team": summary["sent"] if summary["boss"] else [],
            "bg": status == "shell",
            "flag": classify(
                status, quiet,
                config_value("stuck_after_minutes", 5),
                in_flight=in_flight,
                tool_after=config_value("long_tool_minutes", 20),
                waiting_for=(time.time() * 1000 - status_since) / 60000,
                waiting_after=config_value("waiting_after_seconds", 20) / 60,
                named=bool(rec.get("waitingFor")),
                unseen=unseen),
            # Cheap: a session on a pty is hosted by some emulator, so a route
            # exists. Working out which one costs subprocesses, so that waits
            # until you actually click.
            "canJump": (rec.get("kind") == "interactive"
                        and _on_a_terminal(rec.get("pid"))),
            "title": summary["title"],
            "prompt": summary["prompt"],
            "branch": summary["branch"],
            # What it is doing while it works, and what it left you with when
            # it stopped. Never both: a busy session has no line of its own.
            **own_line(sid, status, summary["asked"],
                       said=summary["said"], doing=summary["doing"]),
        })
    return out


ROUTINES = "Routines"


def sessions_in(groups):
    """Every session across every group, flattened."""
    return [s for members in groups.values() for s in members]


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

    # Two bosses talk to each other, and one message between them is not a
    # chain of command: a boss reports to nobody. A name in a team with no
    # session behind it is someone who has since been retired, and the page
    # is about who is running now.
    everyone = sessions_in(groups)
    live = {s["name"] for s in everyone}
    leaders = {s["name"] for s in everyone if s["boss"]}
    for s in everyone:
        s["team"] = [name for name in s["team"]
                     if name in live and name not in leaders]
    bosses = {name: s["name"]
              for s in everyone if s["boss"]
              for name in s["team"]}
    blocks = []
    for (routines, project), members in groups.items():
        order_members(members)
        # A boss leads its own block whatever the activity, and the team it
        # dispatches to follows underneath: the block then has the shape of
        # the team rather than being a flat list of eight equals.
        for s in members:
            s["reportsTo"] = bosses.get(s["name"], "")
        leads = {s["name"] for s in members if s["boss"]}
        members.sort(key=lambda s: (not s["boss"],
                                    s["reportsTo"] not in leads))
        branches = sorted({s["branch"] for s in members if s["branch"]})
        blocks.append({
            "alarms": sum(1 for s in members
                          if s["flag"] in ("waiting", "stuck") or s["blocked"]),
            "blocked": sum(1 for s in members if s["blocked"]),
            "ready": sum(1 for s in members if s["flag"] == "ready"),
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


def order_members(members):
    """What wants you, then what is ready for you, then what is working.

    A session that wrote down what it is blocked on leads with the ones that
    have a dialog open: both are stopped until you speak, and which of them
    you see first is a question of recency, not of what they are called.
    """
    def rank(s):
        if s.get("blocked") or s["flag"] in ("waiting", "stuck"):
            return 0
        if s["flag"] == "ready":
            return 1
        return 2 if s["status"] == "busy" else 3

    members.sort(key=lambda s: (rank(s), -s["updatedAt"]))
    return members


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
             waiting_for=None, waiting_after=0, named=False, unseen=False):
    """Is this session stuck, waiting on you, ready, running long, or working?

    - `ready` -- it finished its turn and you have not looked since. This is
      the common case the page used to say nothing about: `idle` covered
      both "your move" and "abandoned on Tuesday" with the same grey dot.
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
        # Claude Code writes `waitingFor` when a dialog is genuinely open --
        # "input needed", "sandbox request", the dialog's own label. If it
        # names what it wants, that is a real question and it is real now.
        if named:
            return "waiting"
        # Unnamed, it may be a `/btw` helper sitting in `waiting` for a few
        # seconds. A flag that fires on those is one you learn to ignore.
        if waiting_for is not None and waiting_for < waiting_after:
            return None
        return "waiting"
    if status in ("idle", "shell"):
        # `shell` is idle with a background job still running -- the turn is
        # over either way, which is what ready is about.
        return "ready" if unseen else None
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
        -b.get("alarms", 0),     # something needing you outranks something busy
        -b.get("ready", 0),      # and something finished outranks something running
        -b["busy"],
        -b["updatedAt"],
    ))
