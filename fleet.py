"""Who is on what, right now: every provider's live sessions, made into rows.

A provider (`providers/`) hands over facts about its sessions. This module
turns them into what the page draws: the project each one belongs to, the
flag it deserves, the two lines under its name, and the order they come in.
The provider gives the facts; the core gives the voice.
"""
import collections
import concurrent.futures
import functools
import json
import math
import os
import re
import shutil
import threading
import time
from pathlib import Path

import context
import finished
import jump
import lines
import projects
import providers
import seen
import working
from providers import base, claude
from providers.base import CAPABILITIES, STATUSES, on_a_terminal


def resolve_project(cwd, shelves):
    """Name the project a session is working on, or None if it has none.

    A *shelf* is a directory that holds projects without being one --
    `~/Projects`, or `~/Projects/clients`. The project is the
    first directory below the deepest shelf that contains `cwd`.
    """
    if not cwd:
        return None
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
    return " › ".join(parts[:2])


DEFAULT_SHELVES = [
    "~",
    "~/Projects",
    "~/Projects/clients",
]

CONFIG = Path(__file__).resolve().parent / "config.json"
# What ships with the repo. `config.json` is the user's own -- pins, labels,
# assignments, the shelves of one machine -- and is never committed.
EXAMPLE = CONFIG.with_name("config.example.json")


def read_config():
    for path in (CONFIG, EXAMPLE):
        try:
            with path.open(encoding="utf-8") as fh:
                got = json.load(fh)
        except (OSError, ValueError):
            continue
        return got if isinstance(got, dict) else {}
    return {}


def config_value(key, default):
    got = read_config().get(key, default)
    return got if isinstance(got, type(default)) else default


def positive_value(key, default):
    """A config number (a whole number or a fraction) that is more than
    nothing, else the default: minutes for `hung_after_minutes` and
    `finished_after_minutes`, megabytes for `disk_full_mb`. `config_value` takes any value of the default's type, and 0
    or less would call everything quiet hung at once."""
    got = read_config().get(key, default)
    ok = isinstance(got, (int, float)) and not isinstance(got, bool) and 0 < got < float("inf")
    return got if ok else default


# The page can send a rename, a move and a pin in the same breath, and the
# server answers each on a thread of its own. Every change to the file goes
# through here, one at a time.
_CONFIG_LOCK = threading.RLock()


def update_config(change):
    """Let `change(config)` edit config.json in place, atomically, and return
    what was written.

    Reading, editing and replacing happen under one lock, so two changes made
    at once both land -- a change that reads the file first and writes it
    later would put back what the other had just removed. Each write goes
    through a temp file of its own beside the config, so nobody replaces what
    another is still writing.

    The file is hand-editable and holds comments as `_`-prefixed keys, so it is
    read, edited and rewritten rather than regenerated.
    """
    with _CONFIG_LOCK:
        merged = read_config()
        change(merged)
        tmp = CONFIG.with_name(f"{CONFIG.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(merged, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            tmp.replace(CONFIG)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return merged


def write_config(patch):
    """Merge a patch into config.json, atomically."""
    return update_config(lambda config: config.update(patch))


def config(cfg_dir=None):
    """The shelves, expanded."""
    return [os.path.expanduser(s) for s in config_value("shelves", DEFAULT_SHELVES)]


# ------------------------------------------------------------------ keys

def qualified(key, default="claude"):
    """A store key as `provider:id`. A bare id is one from before providers
    existed, when everything was Claude."""
    return key if ":" in key else f"{default}:{key}"


def migrate_keys(default="claude"):
    """Once: bare session ids in config.json and seen.json become `provider:id`.

    Idempotent, so it runs at every start. The hand-written `assign` lines
    and `lines` overrides are what would otherwise silently stop matching.
    """
    patch = {}
    for field in ("assign", "lines"):
        got = config_value(field, {})
        new = {qualified(k, default): v for k, v in got.items()}
        if new != got:
            patch[field] = new
    if patch:
        write_config(patch)
    seen.migrate(default)
    return sorted(patch)


# ------------------------------------------------------------- the voice

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
        line = tail if len(tail) <= limit else line[:limit - 1].rstrip() + "…"
    return line


ASK_LIMIT = lines.LIMIT
FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`]*`")
PARA = re.compile(r"\n\s*\n")
LEADING = re.compile(r"^[^\w(«\"']+")


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
        sentence = sentence[:ASK_LIMIT - 1].rstrip() + "…"
    return (sentence, 1)


def _shown(got):
    """A stored line, and whether it counts as stopped on you.

    Only a session speaking for itself is believed. The hook writes what it
    read out of the transcript into the same file, and extraction cannot tell
    a question that stopped the session from one that offered to do more.
    """
    return {"did": got["did"], "ask": got["ask"], "n": got["n"],
            "blocked": got["n"] > 0 and got["by"] == "session"}


def own_line(session_id, status, asked, root=None, said="", doing=""):
    """The two lines a card shows, and whether the session is stopped on you.

    The session writes its own inside the turn it was already having -- it is
    the only thing that knows where the work stands. What it is stopped on
    belongs to that turn: the next prompt forgets `ask` and `n`, and one that
    survives that is caught by its turn rather than by its age. Comparing
    ages could not do it. A moment only proves a line was written somewhere
    inside a working stretch, and a session can go idle, busy and idle again
    between two polls of this page.

    Where the work stands is not scoped to a turn: the session is on the same
    job after the next prompt, so the last `did` it wrote stays until it
    writes another.

    Everything else here is what to show until the session has written a line
    this turn: the ask read out of the last thing it said. That fills the
    words and does not raise the count. A provider without a hook lives on
    this fallback -- it shows the right words and never rings.
    """
    # Between calls there is nothing in flight and the model is writing. The
    # page used to print your own last prompt back at you there -- words you
    # wrote and already know.
    now = {"doing": (doing or last_words(said)) if status == "busy" else ""}
    got = lines.fresh(session_id, root)
    if got:
        shown = _shown(got)
        shown["did"] = shown["did"] or lines.kept_did(session_id, root)
        return {**shown, **now}
    ask, n = asked
    return {"did": lines.kept_did(session_id, root), "ask": ask, "n": n,
            "blocked": False, **now}


# ------------------------------------------------------------ the round

# A poll is due every 3 seconds; a provider that has not answered in this
# long is reported, and the others are shown without it.
LIVE_BUDGET = 2.0

# Two polls can overlap -- the server is threaded -- and the providers keep
# caches. One lock serialises the round.
POLL = threading.RLock()

# What the last round found out, for the server to report beside the rows.
ROUND = {"failed": {}, "answered": set()}

_pools = {}
_pending = {}


def _ask(p):
    """`p.live()`, bounded in time. Returns (sessions, error)."""
    fut = _pending.get(p.name)
    if fut is None or fut.done():
        pool = _pools.get(p.name)
        if pool is None:
            pool = _pools[p.name] = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=f"live-{p.name}")
        fut = _pending[p.name] = pool.submit(p.live)
    try:
        got = fut.result(timeout=LIVE_BUDGET)
    except concurrent.futures.TimeoutError:
        # Left pending: the next round asks the same call again rather than
        # piling a second one behind it.
        return None, f"no answer in {LIVE_BUDGET:g}s"
    except Exception as exc:                # a provider's bug is its own
        _pending.pop(p.name, None)
        return None, f"{type(exc).__name__}: {exc}"[:200]
    _pending.pop(p.name, None)
    if not isinstance(got, list):
        return None, "live() did not return a list"
    return got, None


def sessions(providers=None):
    """Every live session from every provider, normalised into rows.

    A provider that fails or stalls is reported in `ROUND["failed"]` and the
    page goes on without it; the ones that answered are in `ROUND["answered"]`.
    """
    with POLL:
        shelves = config()
        assigned = config_value("assign", {})
        marks = seen.load()
        remembered = finished.load()
        thresholds = {
            "after": config_value("stuck_after_minutes", 5),
            "tool_after": config_value("long_tool_minutes", 20),
            "waiting_after": config_value("waiting_after_seconds", 20) / 60,
            # How long a busy session may go without a sign of life before
            # it counts as not moving.
            "hung_after": positive_value("hung_after_minutes", 10),
        }
        now = time.time()
        out, failed, answered = [], {}, set()
        for p in (providers if providers is not None else _providers()):
            got, err = _ask(p)
            if err:
                failed[p.name] = err
                continue
            answered.add(p.name)
            for raw in got:
                row = normalize(p, raw, shelves, assigned, marks, thresholds, now, remembered)
                if row:
                    out.append(row)
        ROUND["failed"], ROUND["answered"] = failed, answered
        return out


def _providers():
    return providers.all()


def find(key):
    """The provider and live session behind a `provider:id` key, or None."""
    if not isinstance(key, str) or ":" not in key:
        return None
    name, _, sid = key.partition(":")
    for p in _providers():
        if p.name == name:
            with POLL:
                try:
                    got = p.find(sid)
                except Exception:
                    return None
            return (p, got) if isinstance(got, dict) and got.get("id") == sid else None
    return None


def look(key, shown=None):
    """You looked at this session. Looking is looking, whether or not its
    terminal comes to the front -- or exists: the chime hears of it.

    The handover is read only when the overview's tile put it in front of you,
    and then only the stop that tile showed (`shown`): a look with no stop
    reads nothing, and a session that stopped again since the page's last poll
    has a handover nobody has shown you.
    """
    hit = find(key)
    if not hit:
        return None
    stamp = _int(hit[1].get("updatedAt"))
    mark_seen(key, hit[1], read=bool(stamp) and shown == stamp)
    return hit


def mark_seen(key, s, read=True):
    """Note that you have seen this session as it is now: for the chime, and --
    unless `read` is off -- as a handover read in the overview (`finished.py`
    says why those are two). A terminal that came to the front shows the
    session as it is now, so a jump reads it."""
    stamp = _int(s.get("updatedAt"))
    seen.mark(key, stamp)
    if read:
        finished.mark_read(key, stamp)


def jump_to(p, s):
    """Put a session's terminal in front of you, the provider's way or the
    core's. The pane search -- WezTerm, tmux, Konsole -- stays here, so the
    fourth provider does not have to get it right again."""
    if "jump" not in p.capabilities:
        return {"ok": False, "reason": f"{p.name} sessions have no terminal to jump to"}
    done = p.jump(s)
    if isinstance(done, dict):
        return done
    pid = s.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return {"ok": False, "reason": "no pid is known for this session"}
    return jump.jump(pid, _text(s.get("tmux")))


# ------------------------------------------------------- normalisation

# Every field the page reads off a row, with what it means when a provider
# has nothing to say about it. A conforming session can leave any of these
# out and the row is still whole.
DEFAULTS = {
    "name": "", "kind": "interactive", "tmux": "", "startedAt": 0, "routine": "",
    "waitingFor": "", "boss": False, "bg": False, "title": "", "prompt": "",
    "branch": "", "track": "", "attach": "", "noJump": "",
}

MAX_EXTRAS = 8
EXTRA_LEN = 40


# The largest whole number a float holds exactly, and so the largest a page or
# a clock sum can take: a provider's number beyond it is not a count or a time.
MAX_COUNT = 2 ** 53


def _int(value):
    """A provider's number as a whole number; 0 when it is not one (a bool, text,
    nan, infinity, or beyond what a float holds exactly)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    try:
        got = int(value)
    except (OverflowError, ValueError):
        return 0
    return got if abs(got) <= MAX_COUNT else 0


def _minutes(value):
    """A provider's number as minutes; None when it is not one, as for `_int`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        got = float(value)
    except OverflowError:
        return None
    return got if math.isfinite(got) else None


def _age(value):
    """Minutes ago as a provider says it: a number that is not less than nothing, or None."""
    got = _minutes(value)
    return got if got is not None and got >= 0 else None


def _text(value):
    return value if isinstance(value, str) else ""


def extras_of(value):
    """Badges the page shows without knowing what they mean.

    Bounded, so a provider that sends a thousand of them can neither slow a
    poll nor break the layout: eight keys, forty characters, alphabetical.
    """
    if not isinstance(value, dict):
        return {}
    kept = {}
    for k in sorted(str(k) for k in value if isinstance(k, str)):
        v = value[k]
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            v = str(v)
        if not isinstance(v, str) or not v.strip():
            continue
        kept[k[:EXTRA_LEN]] = " ".join(v.split())[:EXTRA_LEN]
        if len(kept) == MAX_EXTRAS:
            break
    return kept


def normalize(p, raw, shelves, assigned, marks, thresholds, now, remembered):
    """One provider's facts, made into the row the page draws. None if the
    session is not even minimally conforming. `remembered` is what the overview
    keeps (`finished.load()`): the handovers you read and the sessions you pinned."""
    if not isinstance(raw, dict):
        return None
    sid = raw.get("id")
    if not isinstance(sid, str) or not sid:
        return None
    caps = set(p.capabilities) & CAPABILITIES
    key = f"{p.name}:{sid}"
    cwd = _text(raw.get("cwd"))
    status = raw.get("status") if raw.get("status") in STATUSES else "idle"
    updated = _int(raw.get("updatedAt"))
    pid = raw.get("pid") if isinstance(raw.get("pid"), int) and not isinstance(raw.get("pid"), bool) else None
    routine = _text(raw.get("routine"))
    quiet = _minutes(raw.get("quietFor"))
    in_flight = _minutes(raw.get("toolFor"))
    waiting_for = _text(raw.get("waitingFor"))
    said = _text(raw.get("said"))
    handover = last_words(said)
    paths = [x for x in (raw.get("paths") or []) if isinstance(x, str)]
    # Keyed to the moment it stopped, so a session that works and stops
    # again is ready once more without anything having to clear it.
    unseen = seen.ready(key, updated, marks)
    project = projects.landed(assigned, assigned.get(key)) or resolve_project(cwd, shelves)
    # Only guess for the ones that have nothing better -- the guess costs a
    # vote over every path touched, and a session with a real cwd does not
    # need it. A routine is never guessed for.
    guess = (suggest_project(paths, shelves)
             if not project and paths and not routine else None)
    if "jump" not in caps:
        can_jump = False
    elif "canJump" in raw:
        can_jump = bool(raw["canJump"])
    else:
        can_jump = pid is not None and on_a_terminal(pid)
    # A provider that cannot tell waiting from busy may still say `waiting`;
    # without the capability behind it, that is not an alarm.
    if status == "waiting" and "waiting" not in caps:
        flag = None
    else:
        flag = classify(
            status, quiet, thresholds["after"],
            in_flight=in_flight, tool_after=thresholds["tool_after"],
            waiting_for=(now * 1000 - updated) / 60000,
            waiting_after=thresholds["waiting_after"],
            named=bool(waiting_for), unseen=unseen)
    sub_quiet = _minutes(raw.get("subQuiet"))
    tasks = tasks_of(raw.get("bgTasks"))
    sign, moving, silent = movement_of(
        status=status, quiet=quiet, sub_quiet=sub_quiet, in_flight=in_flight,
        doing=_text(raw.get("doing")), cpu=bool(raw.get("shellCpu")), tasks=tasks,
        status_for=(now * 1000 - updated) / 60000 if updated else None,
        hung_after=thresholds.get("hung_after", 10), cpu_ago=_age(raw.get("shellCpuAgo")),
        turn_over=raw.get("turnOver") is True)
    moves = {"writes": writes_of(raw.get("writes")), "subQuiet": sub_quiet,
             "bgTasks": tasks, "shellCpu": bool(raw.get("shellCpu")),
             "movement": sign, "moving": moving,
             # Minutes with no sign of life, for a busy session; and whether
             # /proc could not say what runs under it. Only a provider saying
             # so is believed: Hung is a claim, and it waits for a look that can tell.
             "silentFor": None if silent is None else round(silent, 1),
             "procsUnknown": raw.get("procsUnknown") is True}
    row = {}
    for k, default in DEFAULTS.items():
        got = raw.get(k)
        if isinstance(default, bool):
            row[k] = bool(got)
        elif isinstance(default, int):
            row[k] = _int(got)
        else:
            row[k] = _text(got) or default
    row.update({
        "key": key, "provider": p.name, "id": sid,
        "status": status, "cwd": cwd, "pid": pid,
        "updatedAt": updated, "startedAt": _int(raw.get("startedAt")),
        "project": project, "routine": routine,
        "assigned": key in assigned,
        "suggestion": guess,
        # Only the round needs them, for the guess; `roster()` drops them
        # before the rows go anywhere.
        "paths": paths,
        "quietFor": round(quiet, 1) if quiet is not None else None,
        "toolFor": round(in_flight, 1) if in_flight is not None else None,
        "waitingFor": waiting_for,
        # What it left you with, and the ask read out of it. The provider
        # hands over the raw text; the sentence is made here.
        "said": handover,
        "boss": bool(raw.get("boss")),
        "team": [x for x in (raw.get("team") or []) if isinstance(x, str)],
        "bg": bool(raw.get("bg")),
        "flag": flag,
        **moves,
        "canJump": can_jump,
        # What the overview needs to tell a finished session from an idle one.
        "idleFor": idle_for(status, updated, quiet, moves["writes"], now),
        # Stopped, and what it told you is not read in the overview -- whether or not
        # it said anything: a session with no words still wants a look before it
        # is forgotten, since "no words" may be a transcript that could not be read.
        "unread": status == "idle" and bool(updated) and not finished.is_read(key, updated, remembered),
        # Held open by you (a session pin: `finished.py`). `pinned` on a column is the project's.
        "pinned": key in remembered["pinned"],
        "asking": asking_of(raw.get("asking")),
        # How it stopped, if an API error is its last word; and the last call
        # it made (what a hung session was doing).
        "failure": failure_of(raw.get("failure"), now),
        "lastTool": tool_of(raw.get("lastTool"), now),
        # A provider that cannot jump has no terminal to attach to: the field is emptied.
        "attach": row["attach"] if "jump" in caps else "",
        "extras": extras_of(raw.get("extras")),
        # What it is doing while it works, and what it left you with when it
        # stopped. Never both: a busy session has no line of its own.
        **own_line(sid, status, ask_from(said), said=said,
                   doing=_text(raw.get("doing"))),
    })
    return row


def idle_for(status, updated, quiet, writes, now):
    """Minutes an idle session has shown no sign of life, or None when that
    cannot be told: it is not idle, or it has no stop to count from.

    The registry's stop is one clock; the newest write to the transcript is
    another, and a write after the stop is a sign of life the status has not
    caught up with, so the session has been idle only since the latest of them.
    A provider's strip of writes (one slot per minute, this minute last) says
    the same for the last half hour.
    """
    if status != "idle" or not updated:
        return None
    since = max(0.0, (now * 1000 - updated) / 60000)
    if quiet is not None:
        since = min(since, max(0.0, quiet))
    for ago, count in enumerate(reversed(writes or ())):
        if count:
            return min(since, float(ago))
    return since


# ---------------------------------------------------------------- roster

ROUTINES = "Routines"
NO_PROJECT = projects.NO_PROJECT


def sessions_in(groups):
    """Every session across every group, flattened."""
    return [s for members in groups.values() for s in members]


def members(providers=None):
    """Every session on the machine, routines and finished ones included, in
    the order the overview is made from. Each is the raw row the round made:
    its flag, its silence, the paths it touched.

    Project-first: the question is what is happening, and who is on it.

    Routines are the exception: they are grouped by being routines rather
    than by where they run. A routine runs from `~`, which is no project, so
    it used to land in `No project` -- the pile that means "assign me", which
    is the one thing a routine never needs. They are kept apart from the
    projects, so a real project of the same name cannot be swallowed into
    them, and they come last.

    The order is the one the old blocks gave: projects with something wanting
    you first, then the finished, then the busy, then the latest. A tie
    between two sessions in one column is settled by it, so it is kept.
    """
    groups = {}
    listed = {}
    for s in sessions(providers):
        # A session is one `provider:id`. A provider that lists it twice has
        # still only one session to show, and one to count for the chime --
        # and if only one of the records knows it leads a track, that one.
        first = listed.get(s["key"])
        if first is None or (s["boss"] and not first["boss"]):
            listed[s["key"]] = s
    for s in listed.values():
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
    for group in groups.values():
        order_members(group)
        # A boss leads its own project whatever the activity, and the team it
        # dispatches to follows underneath.
        leads = {s["name"] for s in group if s["boss"]}
        group.sort(key=lambda s: (not s["boss"],
                                  bosses.get(s["name"], "") not in leads))
    own = config_value("lines", {})
    for s in everyone:
        lay_own_line(s, own)
    pinned = config_value("pinned", [])
    rank = {name: i for i, name in enumerate(pinned)}
    ordered = sorted(groups.items(), key=lambda item: _project_order(item[0], item[1], rank))
    return [s for _, group in ordered for s in group]


def _project_order(key, group, rank):
    """Where a project's sessions sit in `members`: the routines last, then
    `No project`, then your pins in your order, then whatever wants you most."""
    routines, project = key
    return (routines,
            not project,
            rank.get(project or "No project", len(rank)),
            -sum(1 for s in group if s["flag"] in ("waiting", "stuck") or s["blocked"]),
            -sum(1 for s in group if s["flag"] == "ready"),
            -sum(1 for s in group if s["status"] == "busy"),
            -max(s["updatedAt"] for s in group))


def roster(providers=None):
    """The page's data: `columns` (the overview, one per project), the
    header's `counts`, the `banners`, and `flags`.

    `flags` is for what rings and what is forgotten: one row per session on
    the machine, routines and finished sessions too, with the raw flag the
    chime has always read. A tile may say less than its flag does; the chime
    does not.
    """
    everyone = members(providers)
    columns = columns_of(everyone)
    for s in everyone:
        s.pop("paths", None)
    return {"columns": columns, "counts": counts_of(columns),
            "banners": banners_of(), "flags": flags_of(everyone)}


def flags_of(everyone):
    """What the chime and the server read of each session: who it is, the
    flag the transcript gave it, and whether it wrote down what blocks it."""
    return [{"key": s["key"], "id": s["id"], "name": s["name"],
             "flag": s["flag"], "blocked": s["blocked"]}
            for s in everyone]


# A session idle this long, with nothing pending, is finished.
FINISHED_AFTER = 120


def columns_of(everyone):
    """What the overview page draws: one column per project, in display order.

    The grouping is the overview's own (`projects.place`): a project is what
    the person thinks of, not the folder a session runs in. The page reads
    these and decides nothing of its own. Routines are not on the page; their
    sessions stay in `flags`, which the chime reads.
    """
    folder_rule = functools.partial(resolve_project, shelves=config())
    names = config_value("names", {})
    own_lines = config_value("project_lines", {})
    pinned = config_value("pinned", [])
    members = [m for m in everyone if not m["routine"]]
    by_key, follow = projects.place(members, folder_rule, config_value("assign", {}))
    grouped = {}
    for m in members:
        grouped.setdefault(by_key[m["key"]]["id"], []).append(m)
    merged = projects.merged_into(config_value("assign", {}))
    finished_after = positive_value("finished_after_minutes", FINISHED_AFTER)
    columns = [(_column(rows, by_key[rows[0]["key"]], folder_rule, follow, names, pinned, merged, own_lines,
                        finished_after),
                _column_order(rows, by_key[rows[0]["key"]], names, pinned))
               for rows in grouped.values()]
    return [column for column, _ in sorted(columns, key=lambda pair: pair[1])]


# The header's three counts: what needs the person, what else is stuck (Error,
# Hung or Limit), what is moving. `otherStuck` and not `stuck`, which in
# the glossary includes Needs you.
COUNT_KINDS = ("needs", "otherStuck", "moving")


def counted_in(stuck, moving):
    """Which of the header's counts a session is in, or None, from its tile's
    `stuck` kind and whether it is moving. Stuck wins over moving, as it does
    in the card's mix: a session that needs you needs you with a job running.
    An idle session is in none."""
    if stuck:
        return "needs" if stuck["kind"] == "needs" else "otherStuck"
    return "moving" if moving else None


def counts_of(columns):
    """The header's counts, over every tile on the page. Routines are not in
    `columns`, so they are not in these."""
    counts = dict.fromkeys(COUNT_KINDS, 0)
    for column in columns:
        for tile in column["sessions"]:
            if tile["counted"]:
                counts[tile["counted"]] += 1
    return counts


# Under this much free space the disk is full, as far as a session writing a
# transcript is concerned: a write that large may fail. `disk_full_mb` in the
# config says another number.
DISK_FULL_MB = 500
MB = 1024 * 1024

# Under a name of its own, so that a test can answer for the disk.
disk_usage = shutil.disk_usage


def banners_of():
    """What is wrong with the whole machine, said once across the top of the
    page: each a `kind` and the `text` to print. Never a kind of stuck on a
    tile -- every session on the machine is held by it alike. The page prints
    these and looks for nothing of its own."""
    banners = []
    try:
        free = disk_usage(claude.claude_dir()).free
    except OSError:
        free = None          # a disk that cannot be read is not known to be full
    if free is not None and free < positive_value("disk_full_mb", DISK_FULL_MB) * MB:
        banners.append({"kind": "disk",
                        "text": f"Disk full: {size_text(free)} left where sessions write"})
    return banners


def size_text(size):
    """A number of bytes the way a person reads free space: '212 MB', '1.5 GB'."""
    mb = size / MB
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{int(mb)} MB"


# The kinds of stuck, most urgent first. The tile says the first that holds for
# its session, and the card the first that holds for any of its sessions.
STUCK_ORDER = ("needs", "error", "hung", "limit")


def state_of(tiles):
    """The card's one word, from its sessions: the most urgent decides. Needs
    you, Error, Hung, Limit, then moving, then all idle."""
    kinds = {t["stuck"]["kind"] for t in tiles if t["stuck"]}
    for kind in STUCK_ORDER:
        if kind in kinds:
            return kind
    return "moving" if any(t["moving"] for t in tiles) else "idle"


def _column_name(project, names):
    return (projects.display_name(project, names) if project["raw"]
            else names.get("No project") or "No project")


def _column(rows, project, folder_rule, follow, names, pinned, merged, own_lines, finished_after):
    # A boss leads its column, whatever the activity: who leads before who
    # works. The rest go by `order_members`; a tie keeps the order `members` gave.
    rows = order_members(list(rows))
    rows.sort(key=lambda s: not s["boss"])
    name = _column_name(project, names)
    about, track = context.card(project, rows, own_lines)
    # The column of no project has no name to repeat.
    column_says = working.repeats(None if project is NO_PROJECT else name, about)
    made = [(m, tile_of(m, _suggestion(m, project, folder_rule, follow, names), column_says))
            for m in rows]
    # Finished sessions leave the tiles for the foot of the column, and with
    # them everything the tiles are counted in: the card's state, its summary,
    # the header. A column of pills alone has no tiles, so it reads all idle.
    shrinks = [is_finished(m, t, finished_after) for m, t in made]
    tiles = [t for (m, t), shrunk in zip(made, shrinks) if not shrunk]
    pills = sorted((pill_of(m, t) for (m, t), shrunk in zip(made, shrinks) if shrunk),
                   key=lambda p: (p["idle"]["since"], p["key"]))
    return {
        "project": project["id"], "raw": project["raw"], "kind": project["kind"],
        "name": name,
        "pinned": _pin_rank(project, pinned) is not None,
        # What you moved into this project, which the page can take back.
        "merged": [{"project": ident, "name": projects.display_name(projects.from_identity(ident), names)}
                   for ident in merged.get(project["id"], [])],
        "context": about, "track": track,
        # What the card's notes link asks the brain, once someone clicks it.
        "notes": None if about is None else {"query": context.notes_query(name, about)},
        # What the tiles wrote; a project of pills alone has the strip they have.
        "strip": strip_of([m for (m, _), shrunk in zip(made, shrinks) if not shrunk] or rows),
        "summary": mix_of(tiles),
        "state": state_of(tiles), "sessions": tiles, "pills": pills,
    }


def _pin_rank(project, pinned):
    """Where you pinned a project -- never No project, which is not one."""
    return None if project is NO_PROJECT else projects.pin_rank(project, pinned)


def _column_order(rows, project, names, pinned):
    """Your pins lead, in your order; then the tracks, the repositories and
    the folders; No project last whatever. Inside a kind they go by name and
    stay put: a column that jumps sideways because a session woke up is the
    reshuffling this page exists to stop."""
    pin = _pin_rank(project, pinned)
    return (project is NO_PROJECT,
            len(pinned) if pin is None else pin,
            projects.COLUMN_RANK[project["kind"]],
            _column_name(project, names).casefold(), project["id"])


def _suggestion(m, project, folder_rule, follow, names):
    """Where a session with no project probably belongs, as the one click
    that puts it there -- or None. A project you moved away is not offered:
    the guess goes where the project went, as a session assigned to it would."""
    guessed = projects.guess(m.get("paths") or [], folder_rule) if project is NO_PROJECT else None
    if not guessed:
        return None
    guessed = follow(guessed)
    return {"project": guessed["id"], "name": projects.display_name(guessed, names)}


def is_finished(m, tile, after):
    """Idle for `after` minutes and not held open, its handover read, and nothing
    left for you. Any sign of life -- a prompt, a write, a job -- or any kind of
    stuck is a tile again, and a session with things left for you (`n`) is wanted
    however old it is. Unread, it stays a tile: a pill is also a way of not looking."""
    return (m["idleFor"] is not None and m["idleFor"] >= after
            and not m["unread"] and not m["pinned"] and m["n"] <= 0
            and not m["moving"] and not tile["stuck"])


def pill_of(m, tile):
    """A finished session as the one line at the foot of its column."""
    since = round(m["idleFor"], 1)
    return {"key": m["key"], "name": m["name"], "provider": m["provider"], "tags": tile["tags"],
            # In none of the header's counts, so the page lights it up as it does any tile.
            "counted": None,
            "idle": {"since": since, "text": span_text(since)},
            "line": tile["line"], "jump": tile["jump"],
            # What the filter box looks through, as it does for a tile.
            "find": tile["find"]}


def tile_of(m, suggestion=None, column_says=frozenset()):
    """One session as a tile: today's data, finished for the page to print.

    The page never has to decide which of the session's words to show.
    """
    line, source = working.line_of(m, column_says)
    # The chime keeps reading the flag. The tile says it another way where
    # that is the better word: a long call is a wait (the movement sign), and
    # a busy session nothing proves is moving is Hung (its kind).
    flag = None if m["flag"] in ("tool", "stuck") else m["flag"]
    stuck = stuck_of(m)
    # The chime's `ready` is another question and is not touched.
    return {
        "key": m["key"], "name": m["name"], "provider": m["provider"],
        "status": m["status"], "suggestion": suggestion,
        "unread": m["unread"], "handover": m["said"] if m["unread"] else "",
        # The stop that handover belongs to: what a click on the tile reads.
        "stop": m["updatedAt"],
        # Held open as a full tile by you, until you unpin it or it closes.
        "pinned": m["pinned"],
        # Put where it is by hand: the page offers the way back.
        "assigned": bool(m.get("assigned")),
        "tags": [t for t, on in (("boss", m["boss"]), ("codex", m["provider"] == "codex")) if on],
        "line": line, "lineSource": source,
        "jump": jump_of(m),
        "flag": flag, "flagNote": flag_note(m) if flag else "",
        "movement": m["movement"], "moving": m["moving"],
        "stuck": stuck,
        # The header count the tile is in, for the page to light it up when
        # that count is clicked.
        "counted": counted_in(stuck, m["moving"]),
        # The chime rings for a blocked session whatever its flag says, so the
        # tile carries what it is asking, the way the old row did.
        "blocked": m["blocked"], "need": need_of(m),
        # What the filter box looks through, so the page does not have to know
        # which of a session's words are searchable. Claude Code's own title
        # too when your line is laid over it: the tile shows it when yours
        # only repeats the project.
        "find": "\n".join([m[k] for k in ("name", "title", "did", "ask", "prompt",
                                          "cwd", "branch")]
                          + ([m["generated"]] if m["overridden"] else [])).lower(),
    }


def stuck_of(m):
    """Why a session is stopped, as a kind with a reason and its context, or
    None. The flags the chime reads are not touched: this is for the page.

    One session may be several things; the tile says the most urgent, in the
    order the card does (`STUCK_ORDER`): Needs you, Error, Hung, Limit.
    """
    needs = needs_of(m)
    if needs:
        return needs
    failure = m["failure"]
    if failure and failure["kind"] == "error":
        return {"kind": "error", "source": "api",
                "reason": error_words(failure["type"], failure["status"]),
                "context": {"type": failure["type"], "text": failure["text"],
                            "ago": failure["held"]}}
    if is_hung(m):
        tool = m["lastTool"]
        return {"kind": "hung", "source": "silence",
                "reason": f"Not moving for {span_text(m['silentFor'])}",
                "context": {"tool": tool["text"] if tool else "",
                            "ago": tool["ago"] if tool else None}}
    if failure:
        return {"kind": "limit", "source": "api", "reason": "Rate limit",
                "context": {"resetsAt": failure["resetsAt"], "held": failure["held"],
                            "text": failure["text"]}}
    asking = m["asking"]
    if asking and asking["kind"] == "pause":
        # "Session paused" for usage credits, with no error in the transcript
        # to say so: the dialog's own words are all there is. The error, when
        # it is there, is read above and tells the reset time as well.
        return {"kind": "limit", "source": "dialog", "reason": "Session paused",
                "context": {"resetsAt": None, "held": None, "text": asking["what"]}}
    return None


def is_hung(m):
    """Busy, and nothing shows it moving: no write of its own or a subagent's
    inside `hung_after_minutes`, no command using CPU, no open background job.
    That is `moving` turned round, plus two cases where it must not be said: a
    /proc that could not answer (a restart, a race, an unreadable folder), and
    a provider that cannot see the session's writes (no transcript to read), so
    that silence is not known to be silence."""
    return (m["status"] == "busy" and not m["moving"] and not m["procsUnknown"]
            and m["silentFor"] is not None)


def error_words(error_type, status):
    """The error's type, said short: overloaded, auth, server, or its own name."""
    if status == 529 or "overloaded" in error_type:
        return "Overloaded"
    if error_type == "authentication_failed" or status in (401, 403):
        return "Auth error"
    if error_type == "server_error" or (status or 0) >= 500:
        return "Server error"
    if error_type in ("", "error"):
        return "API error"
    return _sentence(error_type.replace("_", " ").strip())


def _sentence(words):
    """The words with a capital to begin: how a reason is said."""
    return words[:1].upper() + words[1:]


def needs_of(m):
    """Needs you, or None.

    Needs you has four sources at one level -- an open question, an open
    permission prompt, another request waiting on the person (a sandbox, a
    worker, a goal proposal), a session line with things left -- and the
    dialog that is open now is the one shown over a line written a turn ago.
    """
    asking = m["asking"]
    if asking and asking["kind"] == "question":
        return {"kind": "needs", "source": "question", "reason": "Question",
                "context": {"questions": asking["questions"]}}
    if asking and asking["kind"] == "permission":
        return {"kind": "needs", "source": "permission", "reason": "Permission prompt",
                "context": {"tool": asking["tool"], "command": asking["command"],
                            "target": asking["target"],
                            # Half a command pasted into a terminal is worse
                            # than none.
                            "copy": bool(asking["command"].strip()) and not asking["cut"]}}
    if asking and asking["kind"] == "request":
        return {"kind": "needs", "source": "request", "reason": _sentence(asking["what"]),
                "context": {"what": asking["what"]}}
    if m["blocked"]:
        # The session's own line only: one read out of its last words is a
        # guess, and the chime does not believe it either.
        n = m["n"]
        return {"kind": "needs", "source": "line",
                "reason": f"{n} {'thing' if n == 1 else 'things'} left for you",
                "context": {"text": m["ask"] if n == 1 else ""}}
    return None


def jump_of(m):
    """How the tile reaches its session: a pane that already shows it, a new
    tab that attaches to it, or nothing -- and then why, so the tile can say
    so before anyone clicks."""
    if m["canJump"]:
        return {"via": "pane"}
    if m.get("attach"):
        return {"via": "attach"}
    return {"via": "none", "reason": m.get("noJump") or "no terminal"}


def need_of(m):
    """What a session wants from you: its own words when it asks one thing,
    a count when it asks several -- quoting the first of four misrepresents
    the size of the job."""
    if m["n"] <= 0:
        return ""
    return m["ask"] if m["n"] == 1 and m["ask"] else f"{m['n']} answers needed"


def flag_note(m):
    """What a flag adds to its word: what a waiting session is blocked on, or
    the minutes a stuck session has been quiet and a tool call has run."""
    if m["flag"] == "waiting":
        return m["waitingFor"]
    if m["flag"] == "stuck":
        return f"{int(m['quietFor'] + 0.5)}m"
    if m["flag"] == "tool":
        minutes = m["toolFor"] if m["toolFor"] is not None else m["quietFor"]
        return f"{int(minutes + 0.5)}m"
    return ""


MIN_VOTES = projects.MIN_VOTES
LEAD = projects.LEAD


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


# --------------------------------------------------------------- movement

STRIP_SLOTS = 30

# Open background jobs kept per session. More than this is a runaway, not a list.
MAX_JOBS = 8

# A write this recent is "writing"; older and still moving, it says how long.
WRITING_SECS = 60

# A command, or a background job, is evidence of movement for this long and
# no longer. Past it the sign is still shown, the evidence is not: a session
# whose last tool never came back, with something left running under it, is
# not made to look alive for as long as that something runs.
WAIT_MAX_MINUTES = 360


def writes_of(value):
    """A provider's strip, if it is one: 30 counts, each a whole number or
    None for a minute it could not see. Anything else is not believed."""
    if (isinstance(value, list) and len(value) == STRIP_SLOTS
            and all(v is None or (isinstance(v, int) and not isinstance(v, bool) and v >= 0)
                    for v in value)):
        return list(value)
    return None


def tasks_of(value):
    """Open background jobs a provider reports: a label and minutes running."""
    out = []
    for t in value if isinstance(value, list) else ():
        since = _minutes(t.get("since")) if isinstance(t, dict) else None
        if since is not None:
            out.append({"label": " ".join(_text(t.get("label")).split())[:80]
                        or "a background job", "since": round(since, 1)})
    return out[:MAX_JOBS]


MAX_QUESTIONS, MAX_OPTIONS = base.MAX_QUESTIONS, base.MAX_OPTIONS
QUESTION_LEN, LABEL_LEN, HINT_LEN = base.QUESTION_LEN, base.LABEL_LEN, base.HINT_LEN
COMMAND_LIMIT = base.COMMAND_LIMIT


def _clip(value, limit):
    """Words a session wrote, trimmed to a bound and otherwise left alone: the
    page prints them as text, so there is nothing to escape or strip here."""
    return _text(value).strip()[:limit]


def asking_of(value):
    """What a provider says a session is stopped on, as the page may print it:
    an open question with its options, or None. Anything not believable is
    None -- a dialog that cannot be read is no reason to mark a session. The
    one exception is a provider saying so itself: `questions: []` is a dialog
    that is open whose text is not written yet (Claude Code writes it late)."""
    if not isinstance(value, dict):
        return None
    if value.get("kind") == "question":
        questions = []
        listed = value.get("questions")
        for q in (listed if isinstance(listed, list) else ())[:MAX_QUESTIONS]:
            if not isinstance(q, dict) or not _clip(q.get("question"), QUESTION_LEN):
                continue
            options = [{"label": " ".join(_text(o.get("label")).split())[:LABEL_LEN],
                        "description": " ".join(_text(o.get("description")).split())[:HINT_LEN]}
                       for o in (q.get("options") if isinstance(q.get("options"), list) else ())
                       if isinstance(o, dict) and _text(o.get("label")).strip()][:MAX_OPTIONS]
            questions.append({"question": _clip(q.get("question"), QUESTION_LEN),
                              "header": " ".join(_text(q.get("header")).split())[:LABEL_LEN],
                              "multi": bool(q.get("multi")),
                              "options": options})
        return {"kind": "question", "questions": questions} if questions or listed == [] else None
    if value.get("kind") in ("request", "pause"):
        # A dialog that waits on the person and is neither: told by its name.
        # A `pause` is one that is open on usage credits, which is a limit.
        what = " ".join(_text(value.get("what")).split())[:LABEL_LEN]
        return {"kind": value["kind"], "what": what} if what else None
    if value.get("kind") == "permission":
        # A provider hands over a command only when it is one, and one longer
        # than the limit arrives with a character to spare: that is how a cut
        # one is told from one that just fits.
        command = _text(value.get("command"))
        return {"kind": "permission",
                "tool": " ".join(_text(value.get("tool")).split())[:LABEL_LEN],
                "command": command[:COMMAND_LIMIT],
                "cut": len(command) > COMMAND_LIMIT,
                "target": " ".join(_text(value.get("target")).split())[:HINT_LEN]}
    return None


FAILURE_LEN = base.FAILURE_LEN


def failure_of(value, now):
    """What a provider says stopped a session -- an API error that is the last
    thing it said -- as the page may print it, or None. `kind` is the
    provider's call (`limit` or `error`); `held` is minutes since it happened,
    and never less than nothing for a clock that is ahead of ours."""
    if not isinstance(value, dict) or value.get("kind") not in ("limit", "error"):
        return None
    at = base.milliseconds(value.get("at"))
    return {"kind": value["kind"],
            "type": " ".join(_text(value.get("type")).split())[:LABEL_LEN],
            "status": base.whole_number(value.get("status")),
            "text": " ".join(_text(value.get("text")).split())[:FAILURE_LEN],
            "held": None if at is None else max(0.0, round((now * 1000 - at) / 60000, 1)),
            "resetsAt": base.milliseconds(value.get("resetsAt"))}


def tool_of(value, now):
    """The last call a session made, in words, and how many minutes ago; or None."""
    if not isinstance(value, dict):
        return None
    words, at = " ".join(_text(value.get("text")).split())[:HINT_LEN], base.milliseconds(value.get("at"))
    if not words or at is None:
        return None
    return {"text": words, "ago": max(0.0, round((now * 1000 - at) / 60000, 1))}


def ago_text(minutes):
    """'8s', '3 min', '2 h', '3 d': the way a short time is said."""
    if minutes * 60 < 60:
        return f"{int(round(minutes * 60))}s"
    if minutes < 60:
        return f"{int(minutes)} min"
    if minutes < 48 * 60:
        return f"{int(minutes // 60)} h"
    return f"{int(minutes // 1440)} d"


def span_text(minutes):
    return "<1 min" if minutes < 1 else ago_text(minutes)


def movement_of(status, quiet, sub_quiet, in_flight, doing, cpu, tasks, status_for, hung_after,
                cpu_ago=None, turn_over=False):
    """What shows that a session is alive: (the sign for its tile, moving, and
    for a busy session the minutes since its last sign of life, else None).

    Moving is any of: it or a subagent wrote recently; a command it is
    waiting on has CPU under its shell; a background job it started is open
    with a shell behind it (the provider only reports those); a busy session
    that wrote within `hung_after` minutes. The peer `status` alone is never
    evidence, and CPU with no call in flight is a shell left behind.

    The sign is for the person: writing, waiting on something and since
    when, or idle since when. A session that wrote nothing it can show and
    waits on nothing has none.

    A busy session that is not moving is Hung (`is_hung`), and the third value
    is how long: since its last sign of life of any kind, which is the
    youngest of its newest write, the last time CPU moved under a command it
    is waiting on, and the moment each job or command stopped counting at
    `WAIT_MAX_MINUTES`. A provider that cannot see its writes (no transcript
    to read) gives None, and the session is not called Hung. `cpu_ago` is how
    many minutes ago a provider last saw that CPU move, if it knows.

    A busy session whose last word ended its turn (`turn_over`: a turn end, or an
    API error as the reply) has nothing running of its own: its own writes are
    not signs of life, and it has no clock to be Hung by. It is moving only while a subagent writes, the way a
    lead waits on its team. The status may go on saying busy for hours, as it
    does for a lead with teammates, and that is not a hang.
    """
    # An idle session's last records ended its turn, and a subagent that wrote
    # before that is history: both say the session stopped. A session waiting
    # on a dialog last wrote its question. Only a busy session's own writes
    # are the session working.
    if status == "idle":
        sub_quiet = None
    own = quiet if status == "busy" and not turn_over else None
    latest = min((m for m in (own, sub_quiet) if m is not None), default=None)
    call = in_flight is not None
    jobs = sorted(tasks, key=lambda t: -t["since"])
    subagent = sub_quiet is not None and sub_quiet < hung_after
    evidence = ((call and cpu and in_flight <= WAIT_MAX_MINUTES)
                or any(t["since"] <= WAIT_MAX_MINUTES for t in jobs)
                or subagent)
    # A provider that says nothing about a busy session has only the moment
    # the status changed to go on: that counts for `hung_after` minutes, like
    # a write would, and no longer. The status has no heartbeat.
    unknown = (status == "busy" and quiet is None and sub_quiet is None
               and status_for is not None and status_for < hung_after)
    # Only a write the provider could see says how long it has been quiet. The
    # moment the status changed does not: it is not a heartbeat either way.
    # Writes are not the only sign: a command whose CPU moved a minute ago, or a
    # job that stopped counting a minute ago, is a session that was moving a
    # minute ago, so the quiet is counted from the youngest of them.
    silent = None
    if status == "busy" and latest is not None and not turn_over:
        signs = [latest]
        cpu_age = 0.0 if cpu else cpu_ago
        if call and cpu_age is not None:
            signs.append(max(cpu_age, in_flight - WAIT_MAX_MINUTES))
        signs.extend(max(0.0, t["since"] - WAIT_MAX_MINUTES) for t in jobs)
        silent = min(signs)
    recent = silent is not None and silent < hung_after
    moving = bool(evidence or unknown or recent)

    def writing(minutes):
        return {"kind": "writing", "ago": int(round(minutes * 60)),
                "text": f"writing · {ago_text(minutes)} ago"}

    if latest is not None and latest * 60 <= WRITING_SECS:
        return writing(latest), moving, silent
    if call or jobs or subagent:
        if call:
            on, since = doing or "a command", in_flight
        elif jobs:
            on = jobs[0]["label"] if len(jobs) == 1 else f"{len(jobs)} background jobs"
            since = jobs[0]["since"]
        else:
            on, since = "a subagent", quiet if quiet is not None else sub_quiet
        return {"kind": "waiting", "on": on, "since": round(since, 1),
                "text": f"waiting on: {on}, {span_text(since)}"}, moving, silent
    if recent:
        return writing(latest), moving, silent
    if status == "idle":
        return {"kind": "idle", "since": round(status_for, 1) if status_for is not None else None,
                "text": "idle" if status_for is None else f"idle {span_text(status_for)}"}, moving, silent
    return None, moving, silent


def strip_of(members):
    """The project's strip: the writes of every session in it, minute by
    minute, oldest first. A minute any of them could not see is unknown for
    the project too. A session whose provider does not count writes is left
    out rather than counted as quiet."""
    counted = [m["writes"] for m in members if m.get("writes") is not None]
    if not counted:
        return [None] * STRIP_SLOTS
    return [None if any(w[i] is None for w in counted) else sum(w[i] for w in counted)
            for i in range(STRIP_SLOTS)]


def mix_of(tiles):
    """'2 moving · 1 stuck · 0 idle' as counts. Stuck is a kind on the tile, the
    same word the card's state is made of: a session counted here has one,
    and one without (a menu the person opened, a busy session /proc could not
    vouch for) is not. Stuck wins over moving: a session that needs you needs
    you even with a job running."""
    mix = {"moving": 0, "stuck": 0, "idle": 0}
    for t in tiles:
        if t["stuck"]:
            mix["stuck"] += 1
        elif t["moving"]:
            mix["moving"] += 1
        else:
            mix["idle"] += 1
    return mix


def classify(status, quiet, after, in_flight=None, tool_after=20,
             waiting_for=None, waiting_after=0, named=False, unseen=False):
    """Is this session stuck, waiting on you, ready, running long, or working?

    - `ready` -- it finished its turn and you have not looked since. This is
      the common case the page used to say nothing about: `idle` covered
      both "your move" and "abandoned on Tuesday" with the same grey dot.
    - `waiting` -- the agent has asked something and nobody replied. It
      needs *you*, and there is no grace period.
    - a tool call in flight -- the transcript is silent for the whole of a
      tool call, so silence proves nothing while one is running. Only when it
      has run absurdly long is it worth saying, and even then it is news, not
      an alarm.
    - `busy`, silent, nothing running -- it thinks it is working and it is
      not. The transcript's mtime is the only honest heartbeat: `updatedAt`
      in the peer file does not move while a session works.

    A signal the provider does not have arrives as None and is simply not
    consulted: no transcript means no `stuck`, no tool tracking means no
    `tool`. Idle is not stuck. A session idle for two days is finished or
    abandoned, and flashing it forever would only teach you to ignore the
    flashing.
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
        # `shell` was Claude Code's word for idle with a background job still
        # running -- the turn is over either way, which is what ready is about.
        return "ready" if unseen else None
    if status != "busy":
        return None
    if in_flight is not None:
        return "tool" if in_flight >= tool_after else None
    if quiet is not None and quiet >= after:
        return "stuck"
    return None


def lay_own_line(m, own):
    """Lay your own line over the generated one, where you wrote one.

    `own` is `lines` in config.json: session key to words.
    """
    mine = own.get(m.get("key"))
    # Only words are a line: a hand-edited number or blank is not one.
    mine = mine if isinstance(mine, str) and mine.strip() else ""
    m["overridden"] = bool(mine)
    m["own"], m["generated"] = mine, m["title"]
    if mine:
        m["title"] = mine
