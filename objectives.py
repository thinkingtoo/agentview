"""A track's rows: one per Done when line of its goal, each with its state and
the tickets it names (ticket boss-track/01).

A row is done when its box is ticked, and only then: the rows agree with the
card's "N of M". An open row is worked on when a live worker of the track's
roster has one of its tickets in its task, or when all its tickets are done
and the box waits for the boss's tick; waiting when one of its open tickets
is blocked by a ticket still open; planned otherwise.
"""
import os
import re

import context
import projects

# The order rows are shown in: what moves first, what is finished last.
IDLE_TASKS = ("", "-", "—", "–", "idle", "free", "none")   # what a roster task says of a worker on nothing
ORDER = ("worked", "waiting", "planned", "done")
# What a ticket's Status says when nothing is left to do on it.
CLOSED = ("done", "resolved", "wontfix")
# `paste/12`, `overview-build/23`, and a range: `paste/23 to 26`, `paste/23-26`.
# Not a path (`agentview-wt/Mei`, `src/12/x`) nor a date: a feature starts with a letter.
REF = re.compile(r"(?<![\w/.-])([a-z][a-z0-9-]*)/(\d{1,3})(?:(?:\s*(?:to|-|–|\.\.)\s*)(\d{1,3}))?(?![\w/])")
RANGE_MAX = 20           # a range wider than this is a typo, read as its first ticket
TICKETS_MAX = 40         # tickets read per card, per poll
TICKET_READ = 20_000     # a ticket is read this far: its title, Status and Blocked by sit at the top
TICKET_FILE = re.compile(r"^(\d{1,4})-[^/]*\.md$")
TITLE = re.compile(r"^#\s+(.*?)\s*#*\s*$")
STATUS = re.compile(r"^\s*[_*]*status:[_*\s]*([\w-]+)", re.IGNORECASE)
BLOCKED_BY = re.compile(r"^\s*[_*]*blocked by:[_*\s]*(.*?)[_*\s]*$", re.IGNORECASE)
# A ticket of the same feature in a Blocked by: `02`, `01: one marks store`,
# `02, 03`, `#4 and 5`. Only at the start or after a list mark: a number in
# the words that follow (`02: search 3 folders`) is no ticket.
SAME_FEATURE = re.compile(r"(?:^|[,;&]|\band\b)\s*#?0*(\d{1,3})\b")


def refs_in(text):
    """The ticket references a line names, `(feature, number)`, in its order, once each."""
    out = []
    for m in REF.finditer(text):
        first = int(m.group(2))
        last = int(m.group(3)) if m.group(3) else first
        if not first < last <= first + RANGE_MAX:
            last = first
        for n in range(first, last + 1):
            if (m.group(1), n) not in out:
                out.append((m.group(1), n))
    return out


def in_scratch(end, base):
    """Whether an opened ticket lies in the checkout's `.scratch`, in no `.git`
    folder, and is markdown: a cloned repository may link a ticket anywhere."""
    target = context.within(end, base)
    return target is not None and target.parts[:1] == (".scratch",) and target.suffix == ".md"


def _find(root, feature, number):
    """`(the number as its file writes it, the text)` of ticket
    `<feature>/<number>` in a checkout, or None."""
    folder = root / ".scratch" / feature / "issues"
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    for name in names:
        m = TICKET_FILE.match(name)
        if m and int(m.group(1)) == number:
            text = context.read(folder / name, TICKET_READ, base=root, judge=in_scratch)
            return (m.group(1), text) if text else None
    return None


def _ticket(ref, text):
    """What a row shows of a ticket: its first heading, Status and Blocked by,
    as the top of the file says them. `workers` is filled in by `rows`."""
    lines = text.splitlines()
    title = next((m.group(1) for m in map(TITLE.match, lines) if m), "")
    status = next((m.group(1).casefold() for m in map(STATUS.match, lines) if m), "")
    blocked = next((m.group(1) for m in map(BLOCKED_BY.match, lines) if m), "")
    return {"ref": ref, "title": context.squash(title), "status": status,
            "blocked_by": context.squash(blocked), "workers": []}


class Tickets:
    """The tickets of one card, each looked up once, in the main checkout of
    every repository the track's sessions work in, at most TICKETS_MAX."""

    def __init__(self, sessions):
        roots = []
        for m in sessions:
            found = projects.checkouts(m.get("cwd") or "")
            if found and found[0] not in roots:
                roots.append(found[0])
        self.roots, self.seen = roots, {}

    def get(self, feature, number):
        key = (feature, number)
        if key not in self.seen:
            if len(self.seen) >= TICKETS_MAX:
                return None
            found = next((f for f in (_find(r, feature, number) for r in self.roots) if f), None)
            self.seen[key] = _ticket(f"{feature}/{found[0]}", found[1]) if found else None
        return self.seen[key]


def blockers(feature, ticket):
    """`(feature, number)` of each ticket a ticket's Blocked by names; a bare
    number is a ticket of its own feature."""
    said = ticket["blocked_by"]
    named = refs_in(said)
    for m in SAME_FEATURE.finditer(REF.sub("", said)):
        if (feature, int(m.group(1))) not in named:
            named.append((feature, int(m.group(1))))
    return named


def is_open(ticket):
    """Whether something is left to do on a ticket."""
    return ticket["status"] not in CLOSED


def _state(done, named, tickets):
    """A row's state, and whether it awaits its tick, from its `(key, ticket)` pairs."""
    if done:
        return "done", False
    if named and not any(is_open(t) for _, t in named):
        return "worked", True                   # a worker still on the roster changes nothing: the tick is the boss's
    if any(t["workers"] for _, t in named):
        return "worked", False
    for (feature, _), t in named:
        if is_open(t) and any(b and is_open(b) for b in (tickets.get(*k) for k in blockers(feature, t))):
            return "waiting", False
    return "planned", False


def working(m):
    """Whether a session is on a turn now: busy or waiting on a dialog, and not
    only waiting on a job whose turn is over. Idle never is, and `shell` is idle
    with a job: the status flips to busy when a turn starts (ticket boss-track/06)."""
    return m.get("status") in ("busy", "waiting") and not m.get("waits")


def _said(m):
    """What a working session's row says of its task when neither the table nor
    its own line does: its card title, else the first line of its last prompt,
    else "working" (ticket boss-track/11). Never read from a transcript."""
    prompt = next((l.strip() for l in str(m.get("prompt") or "").splitlines() if l.strip()), "")
    return str(m.get("title") or "").strip() or prompt or "working"


def workers(track, sessions, is_concierge, owner_of, boss_panes):
    """`{name: task}` of each session working on a track now: a worker the
    tracker's Roster table names, with its task, or a worker whose tmux pane
    claude-boss stamped with one of the track's boss panes (`owner_of(m)`), with
    the line it last wrote when the table has no task for it, else the best text
    its row already carries (`_said`). A working worker is always listed. The
    boss and a concierge, by the pane's mark or a roster task of "concierge",
    are never one."""
    table = projects.roster_tasks(track)
    out = {}
    for m in sessions:
        name = m.get("name")
        if not name or m.get("boss") or is_concierge(m) or not working(m):
            continue
        task = table.get(name.casefold())
        if task is None and owner_of(m) in boss_panes:
            task = m.get("did") or _said(m)
        if task is not None and task.strip().casefold() != "concierge":
            out[name] = task
    return out


def elsewhere(made, crew):
    """`[{name, task}]` of each working session whose task no row's ticket
    carries, by name. Idle (an empty or "idle" task) is not read as work.
    Hammers stay tied to `feature/NN` refs; this only says what the rest are on."""
    placed = {w for r in made for t in r["tickets"] for w in t["workers"]}
    return [{"name": name, "task": context.squash(task)}
            for name, task in sorted(crew.items(), key=lambda kv: kv[0].casefold())
            if name not in placed and task.strip().casefold() not in IDLE_TASKS]


def rows(boxes, sessions, crew, met=False):
    """The rows of a track's card, in ORDER, each state in the goal file's order.
    `crew` is `workers`: who is working on the track now, with their tasks.
    A track whose goal says MET has every row done, as its progress says.
    Every row's own tickets are looked up before any blocker is: on a card that
    reaches TICKETS_MAX, what a blocker costs comes out of "waiting", never out
    of a row's own tickets."""
    tickets = Tickets(sessions)
    tasks = {name: refs_in(task) for name, task in crew.items()}
    named = []
    for box in boxes:
        pairs = [(k, t) for k, t in ((k, tickets.get(*k)) for k in refs_in(box["text"])) if t]
        for key, t in pairs:
            t["workers"] = sorted(name for name, refs in tasks.items() if key in refs)
        named.append(pairs)
    made = []
    for box, pairs in zip(boxes, named):
        state, awaiting = _state(box["done"] or met, pairs, tickets)
        made.append({"text": box["text"], "state": state, "awaiting_tick": awaiting,
                     "tickets": [t for _, t in pairs]})
    return sorted(made, key=lambda r: ORDER.index(r["state"]))
