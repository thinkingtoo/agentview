"""Which project each session belongs to.

The person thinks in projects; the machine knows folders, repositories and
bosses. This turns the second into the first, once per round, for the
overview's columns.
"""
import collections
import os
import re
from pathlib import Path

from providers import claude


def pm_dir():
    """Where claude-boss keeps its trackers. A function so a test can move it."""
    return claude.claude_dir() / "pm"


def _repository(cwd):
    """The repository a folder is in, worktrees folded onto their parent:
    (the shared `.git` folder, the folder's path inside its checkout), or None.
    """
    here = Path(cwd)
    for d in (here, *here.parents):
        git = d / ".git"
        if git.is_dir():
            return git, here.relative_to(d)
        if git.is_file():
            try:
                admin = Path(git.read_text(encoding="utf-8").split(":", 1)[1].strip())
                common = (admin / (admin / "commondir").read_text(encoding="utf-8").strip()).resolve()
            except (OSError, IndexError):
                return None
            return common, here.relative_to(d)
    return None


SECTION = re.compile(r'^\s*\[\s*remote\s+"([^"]+)"\s*\]\s*$')
URL = re.compile(r"^\s*url\s*=\s*(\S+)\s*$")
SCP_LIKE = re.compile(r"^(?:[\w.-]+@)?([\w.-]+):(?!//)(.+)$")
URL_LIKE = re.compile(r"^[a-z+]+://(?:[^@/]*@)?([^/:]+)(?::\d+)?/(.+)$")


def _remote(common):
    """The repository's address as `host/owner/name` -- the same whether it
    was cloned over ssh or https, with or without `.git` -- or None."""
    try:
        text = (common / "config").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    urls, remote = {}, None
    for line in text.splitlines():
        section = SECTION.match(line)
        if section:
            remote = section.group(1)
        elif line.lstrip().startswith("["):
            remote = None
        elif remote is not None and (url := URL.match(line)):
            urls.setdefault(remote, url.group(1))
    url = urls.get("origin") or next(iter(urls.values()), None)
    if not url:
        return None
    got = URL_LIKE.match(url) or SCP_LIKE.match(url)
    if not got:
        return url.rstrip("/").removesuffix(".git")
    host, path = got.groups()
    return f"{host.lower()}/{path.strip('/').removesuffix('.git')}"


def display_name(place, names):
    """What the card says: your name for the project, else the raw one. Your
    names are keyed by the project's identity, or -- as they were before
    projects had one -- by its raw name."""
    return names.get(place["id"]) or names.get(place["raw"]) or place["raw"]


def holds_repositories(path):
    """Is this folder only a shelf for several repositories?"""
    found = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False) and os.path.exists(
                        os.path.join(entry.path, ".git")):
                    found += 1
                    if found == 2:
                        return True
    except OSError:
        pass
    return False


def place_of(cwd, folder_rule):
    """Rules 3 and 4 for the folder a session was launched in: its
    repository's project, else the folder rule's, else None.

    A folder that only holds several repositories is nobody's project --
    sessions there are looking for one -- so the folder rule is not asked.
    """
    if not cwd:
        return None
    found = _repository(cwd)
    if not found:
        label = None if holds_repositories(cwd) else folder_rule(cwd)
        return {"id": f"folder:{label}", "kind": "folder", "raw": label} if label else None
    common, inside = found
    # Known by its remote, so a second clone is the same project. With none,
    # by where its main checkout is.
    key = _remote(common) or str(common.parent)
    # Each `clients/<client>/` is a project of its own: the work of one
    # client is not the work of the one beside it, or of the repository.
    if len(inside.parts) >= 2 and inside.parts[0] == "clients":
        return {"id": f"client:{key}/{inside.parts[1]}", "kind": "folder",
                "raw": inside.parts[1]}
    return {"id": f"repo:{key}", "kind": "repository",
            "raw": key.rstrip("/").rsplit("/", 1)[-1]}


MIN_VOTES = 3          # below this it is noise, not a habit
LEAD = 1.5             # the winner has to be clearly ahead of the runner-up


def guess(paths, folder_rule):
    """Rule 5: the project a session keeps touching files in, or None.

    Only ever a suggestion. It is right when a session works in one place and
    silent when it does not -- being confidently wrong is the one outcome that
    matters here, because you would never know to look.
    """
    folders = collections.Counter(
        os.path.dirname(p) if os.path.splitext(p)[1] else p
        for p in paths if os.path.isabs(p))
    votes, seen = collections.Counter(), {}
    for folder, n in folders.items():
        place = place_of(folder, folder_rule)
        if place:
            votes[place["id"]] += n
            seen[place["id"]] = place
    ranked = votes.most_common(2)
    if not ranked or ranked[0][1] < MIN_VOTES:
        return None
    if len(ranked) > 1 and ranked[0][1] < ranked[1][1] * LEAD:
        return None
    return seen[ranked[0][0]]


NO_PROJECT = {"id": "", "kind": "none", "raw": ""}

# What a project's identity starts with, and the kind of column it makes. The
# prefix is what keeps a track, a repository, a client folder and a folder
# that share a name from ever being one project.
KINDS = {"track": "track", "repo": "repository", "client": "folder", "folder": "folder"}
KIND_RANK = {"track": 0, "repository": 1, "folder": 2}


def from_identity(ident):
    """The project an identity names, whether or not anyone is in it, or None."""
    kind, _, rest = ident.partition(":")
    if kind not in KINDS or not rest:
        return None
    raw = rest.rstrip("/").rsplit("/", 1)[-1] if kind in ("repo", "client") else rest
    return {"id": ident, "kind": KINDS[kind], "raw": raw}


def _named(value, carried):
    """Rule 1 for a session you assigned: the identity you gave, or else the
    project that carries the name you gave -- the way it worked before
    projects had identities -- or else a new folder project of that name."""
    by_identity = from_identity(value)
    if by_identity:
        return by_identity
    same = carried.get(value)
    if same:
        return min(same, key=lambda p: (KIND_RANK[p["kind"]], p["id"]))
    return {"id": f"folder:{value}", "kind": "folder", "raw": value}


# Only claude-boss makes bosses and tracks, and it does so for Claude Code.
# Codex sessions reach the repository, the folder and the guess, nothing above.
TRACKED = ("claude",)
TRACK_NAME = re.compile(r"^\w[\w.-]{0,79}$")
BOSS_PANE = "boss-"


def _tmux_track(tmux):
    """The track a pane's tmux session is named for -- claude-boss calls the
    session `boss-<track>` -- or ""."""
    name = tmux.split(":", 1)[0]
    return name[len(BOSS_PANE):] if name.startswith(BOSS_PANE) else ""


def _track_place(track):
    return {"id": f"track:{track}", "kind": "track", "raw": track}


def _boss_tracks(members):
    """`{session key: track}` for each boss that has one. A boss's marker
    names it; the tmux session it runs in is only the fallback, because a
    renamed track keeps its old pane."""
    out = {}
    for m in members:
        if m["boss"] and m["provider"] in TRACKED:
            track = m.get("track") or ""
            if not TRACK_NAME.match(track):
                track = _tmux_track(m.get("tmux") or "")
            if TRACK_NAME.match(track):
                out[m["key"]] = track
    return out


HEADING = re.compile(r"^#{1,6}\s*(.*?)\s*#*\s*$")
FIRST_WORD = re.compile(r"[^\s(,/|]+")
TRACKER_READ = 1_000_000


def _named_in(track):
    """The workers a running track's tracker lists in a `Roster` table, as
    lowercase names. A struck-through row is a worker who was retired; a name
    anywhere else in the file is a mention, not a roster."""
    if not TRACK_NAME.match(track):
        return set()
    try:
        with open(pm_dir() / f"{track}.md", encoding="utf-8", errors="replace") as fh:
            text = fh.read(TRACKER_READ)
    except OSError:
        return set()
    names, in_roster = set(), False
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            in_roster = heading.group(1).strip("*_` ").casefold() == "roster"
            continue
        if not in_roster or not line.lstrip().startswith("|"):
            continue
        cell = line.strip().strip("|").split("|", 1)[0].strip()
        cell = re.sub(r"[*_`]", "", cell) if not cell.startswith("~~") else ""
        word = FIRST_WORD.match(cell)
        if word and word.group().strip("-:"):
            names.add(word.group().casefold())
    return names


class Trackers:
    """The running tracks' trackers, each read once and only if asked."""

    def __init__(self, live):
        self.live, self._read = live, {}

    def naming(self, name):
        """The running tracks whose roster lists this worker."""
        name = name.casefold()
        return {t for t in sorted(self.live)
                if name in self._read.setdefault(t, _named_in(t))}


def _teams(members, held):
    """`{worker name: the tracks of the running bosses that messaged it}`."""
    out = {}
    for m in members:
        if m["key"] in held:
            for name in m.get("team") or []:
                out.setdefault(name, set()).add(held[m["key"]])
    return out


def _worker_track(m, live, teams, trackers):
    """The track a worker belongs to, from what points at a boss that is
    running -- or "". A pointer at a track nobody leads any more is stale and
    files nobody, and so does one that points two ways.

    The order, when they disagree: the pane the worker was launched into,
    then the boss that messaged it, then the one tracker that lists it. A
    message is the weaker word: a worker handed from one boss to another
    stays in the first boss's team. A tracker is the weakest: it is written
    by hand, and nobody takes a retired worker off it in time.
    """
    if m["provider"] not in TRACKED or m["boss"]:
        return ""
    tmux = _tmux_track(m.get("tmux") or "")
    if tmux in live:
        return tmux
    messaged = teams.get(m["name"], ())
    if len(messaged) == 1:
        return next(iter(messaged))
    listed = trackers.naming(m["name"])
    return next(iter(listed)) if len(listed) == 1 else ""


def place_all(members, folder_rule, assigned):
    """Every session's project: `{session key: place}`.

    First match wins, in the order the person thinks of it: their own setting,
    then the boss's track, then the repository, then the folder, then nowhere.
    """
    held = _boss_tracks(members)
    live = set(held.values())
    teams = _teams(members, held)
    trackers = Trackers(live)
    places = {}
    for m in members:
        if _own(assigned, m["key"]):
            continue
        track = held.get(m["key"]) or _worker_track(m, live, teams, trackers)
        places[m["key"]] = (_track_place(track) if track
                            else place_of(m["cwd"], folder_rule) or NO_PROJECT)
    carried = {}
    for place in places.values():
        if place is not NO_PROJECT:
            carried.setdefault(place["raw"], []).append(place)
    for m in members:
        if _own(assigned, m["key"]):
            places[m["key"]] = _named(assigned[m["key"]].strip(), carried)
    return places


def _own(assigned, key):
    return isinstance(assigned.get(key), str) and bool(assigned[key].strip())


COLUMN_RANK = {"track": 0, "repository": 1, "folder": 2, "none": 3}


def pin_rank(place, pinned):
    """Where the person pinned this project, or None. A pin names the
    identity; one written before projects had identities names the raw name,
    which a project of any kind may carry."""
    for i, pin in enumerate(pinned):
        if isinstance(pin, str) and pin and (
                pin == place["id"] or (from_identity(pin) is None and pin == place["raw"])):
            return i
    return None
