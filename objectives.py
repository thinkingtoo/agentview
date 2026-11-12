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
from pathlib import Path

import context
import projects

# The order rows are shown in: what moves first, what is finished last.
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
    try:
        target = Path(end.removesuffix(" (deleted)")).relative_to(base)
    except ValueError:
        return False
    return (target.parts[:1] == (".scratch",) and target.suffix == ".md"
            and ".git" not in {part.casefold() for part in target.parts})


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


def blockers(ticket):
    """`(feature, number)` of each ticket a ticket's Blocked by names."""
    said = ticket["blocked_by"]
    feature = ticket["ref"].split("/", 1)[0]
    named = refs_in(said)
    for m in SAME_FEATURE.finditer(REF.sub("", said)):
        if (feature, int(m.group(1))) not in named:
            named.append((feature, int(m.group(1))))
    return named


def is_open(ticket):
    return ticket["status"] not in CLOSED


def _tasks(track):
    """`{lowercase worker name: its task}` from every Roster table of a
    track's tracker. The task is the column headed with "task", else the last.
    A struck-through row is a worker who was retired."""
    if not projects.TRACK_NAME.match(track):
        return {}
    text = context.read(projects.pm_dir() / f"{track}.md", projects.TRACKER_READ)
    out, in_roster, column = {}, False, None
    for line in text.splitlines():
        heading = projects.HEADING.match(line)
        if heading:
            in_roster = bool(projects.ROSTER.match(heading.group(1).strip("*_` ").casefold()))
            column = None
            continue
        if not in_roster or not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if column is None:                      # the header row
            column = next((i for i, c in enumerate(cells) if "task" in c.casefold()), len(cells) - 1)
            continue
        if cells[0].startswith("~~") or column >= len(cells):
            continue
        word = projects.FIRST_WORD.match(re.sub(r"[*_`]", "", cells[0]))
        if word and word.group().strip("-:"):
            out[word.group().casefold()] = cells[column]
    return out


def _state(done, tickets, tickets_of):
    """A row's state and whether it awaits its tick."""
    if done:
        return "done", False
    if any(t["workers"] for t in tickets):
        return "worked", False
    if tickets and not any(map(is_open, tickets)):
        return "worked", True
    for t in filter(is_open, tickets):
        if any(b and is_open(b) for b in (tickets_of.get(f, n) for f, n in blockers(t))):
            return "waiting", False
    return "planned", False


def rows(track, boxes, sessions, met=False):
    """The rows of a track's card, in ORDER, each state in the goal file's order.
    A track whose goal says MET has every row done, as its progress says."""
    tickets = Tickets(sessions)
    live = {(m.get("name") or "").casefold(): m.get("name") for m in sessions if m.get("name")}
    tasks = {live[name]: refs_in(task) for name, task in _tasks(track).items() if name in live}
    made = []
    for box in boxes:
        named = [t for t in (tickets.get(f, n) for f, n in refs_in(box["text"])) if t]
        for t in named:
            key = tuple(t["ref"].split("/"))
            key = (key[0], int(key[1]))
            t["workers"] = sorted(name for name, refs in tasks.items() if key in refs)
        state, awaiting = _state(box["done"] or met, named, tickets)
        made.append({"text": box["text"], "state": state, "awaiting_tick": awaiting, "tickets": named})
    return sorted(made, key=lambda r: ORDER.index(r["state"]))
