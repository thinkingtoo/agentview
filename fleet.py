"""Who is on what, right now: every provider's live sessions, made into rows.

A provider (`providers/`) hands over facts about its sessions. This module
turns them into what the page draws: the project each one belongs to, the
flag it deserves, the two lines under its name, and the order they come in.
The provider gives the facts; the core gives the voice.
"""
import collections
import concurrent.futures
import json
import os
import re
import threading
import time
from pathlib import Path

import jump
import lines
import providers
import seen
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
    the only thing that knows where the work stands. A line belongs to that
    turn: the next prompt forgets it, and one that survives that is caught by
    its turn rather than by its age. Comparing ages could not do it. A moment
    only proves a line was written somewhere inside a working stretch, and a
    session can go idle, busy and idle again between two polls of this page.

    Everything else here is what to show until the session has written one:
    the ask read out of the last thing it said. That fills the words and does
    not raise the count. A provider without a hook lives on this fallback --
    it shows the right words and never rings.
    """
    # Between calls there is nothing in flight and the model is writing. The
    # page used to print your own last prompt back at you there -- words you
    # wrote and already know.
    working = {"doing": (doing or last_words(said)) if status == "busy" else ""}
    got = lines.fresh(session_id, root)
    if got:
        return {**_shown(got), **working}
    ask, n = asked
    return {"did": "", "ask": ask, "n": n, "blocked": False, **working}


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
        thresholds = {
            "after": config_value("stuck_after_minutes", 5),
            "tool_after": config_value("long_tool_minutes", 20),
            "waiting_after": config_value("waiting_after_seconds", 20) / 60,
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
                row = normalize(p, raw, shelves, assigned, marks, thresholds, now)
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


def look(key):
    """You looked at this session. Looking is looking, whether or not its
    terminal comes to the front -- or exists."""
    hit = find(key)
    if not hit:
        return None
    p, s = hit
    seen.mark(key, _int(s.get("updatedAt")))
    return hit


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
    "branch": "",
}

MAX_EXTRAS = 8
EXTRA_LEN = 40


def _int(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _minutes(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


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


def normalize(p, raw, shelves, assigned, marks, thresholds, now):
    """One provider's facts, made into the row the page draws. None if the
    session is not even minimally conforming."""
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
    paths = [x for x in (raw.get("paths") or []) if isinstance(x, str)]
    # Keyed to the moment it stopped, so a session that works and stops
    # again is ready once more without anything having to clear it.
    unseen = seen.ready(key, updated, marks)
    project = assigned.get(key) or resolve_project(cwd, shelves)
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
        "quietFor": round(quiet, 1) if quiet is not None else None,
        "toolFor": round(in_flight, 1) if in_flight is not None else None,
        "waitingFor": waiting_for,
        # What it left you with, and the ask read out of it. The provider
        # hands over the raw text; the sentence is made here.
        "said": last_words(said),
        "boss": bool(raw.get("boss")),
        "team": [x for x in (raw.get("team") or []) if isinstance(x, str)],
        "bg": bool(raw.get("bg")),
        "flag": flag,
        "canJump": can_jump,
        "extras": extras_of(raw.get("extras")),
        # What it is doing while it works, and what it left you with when it
        # stopped. Never both: a busy session has no line of its own.
        **own_line(sid, status, ask_from(said), said=said,
                   doing=_text(raw.get("doing"))),
    })
    return row


# ---------------------------------------------------------------- roster

ROUTINES = "Routines"


def sessions_in(groups):
    """Every session across every group, flattened."""
    return [s for members in groups.values() for s in members]


def roster(providers=None):
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
    for s in sessions(providers):
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


def apply_overrides(block, names, lines):
    """Lay your own labels over the generated ones.

    `project` stays the key everything else is stored against -- pins, names,
    the lot -- so renaming a project never orphans its own pin. `label` is the
    only thing the page reads.
    """
    block["label"] = names.get(block["project"], block["project"])
    block["renamed"] = block["project"] in names
    for m in block["members"]:
        own = lines.get(m.get("key"))
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
