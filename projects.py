"""Which project each session belongs to.

The person thinks in projects; the machine knows folders, repositories and
bosses. This turns the second into the first, once per round, for the
overview's columns.

A project here is a small dict: `id` is its *identity*, namespaced by what it
is (`track:x`, `repo:host/owner/name`, `client:…`, `folder:x`) so a track, a
repository, a client folder and a folder that share a name are never one
project; `kind` is the column it makes (track, repository, folder, none);
`raw` is its name before the person renames it.

A session's project is the first of these that answers: the person's own
setting, the boss's track, the repository, the folder rule, and otherwise
none -- with a guess from the files it touched offered as a suggestion.
"""
import collections
import os
import re
from pathlib import Path

from providers import claude

# What an identity starts with, and the kind of column it makes.
KINDS = {"track": "track", "repo": "repository", "client": "folder", "folder": "folder"}
# Column order when nothing else decides: tracks, repositories, folders, nowhere.
COLUMN_RANK = {"track": 0, "repository": 1, "folder": 2, "none": 3}
NO_PROJECT = {"id": "", "kind": "none", "raw": ""}


def pm_dir():
    """Where claude-boss keeps its trackers. A function so a test can move it."""
    return claude.claude_dir() / "pm"


def _project(prefix, key, raw):
    return {"id": f"{prefix}:{key}", "kind": KINDS[prefix], "raw": raw}


def _last(path):
    return path.rstrip("/").rsplit("/", 1)[-1]


def from_identity(ident):
    """The project an identity names, whether or not anyone is in it, or None."""
    prefix, _, key = ident.partition(":")
    if prefix not in KINDS or not key:
        return None
    return _project(prefix, key, _last(key) if prefix in ("repo", "client") else key)


def display_name(project, names):
    """What the card says: your name for the project, else the raw one. Your
    names are keyed by the project's identity, or -- as they were before
    projects had one -- by its raw name."""
    return names.get(project["id"]) or names.get(project["raw"]) or project["raw"]


def is_pin_of(pin, project):
    """Does this pin name this project? A pin names the identity; one written
    before projects had identities names the raw name, which a project of any
    kind may carry."""
    return isinstance(pin, str) and bool(pin) and (
        pin == project["id"] or (from_identity(pin) is None and pin == project["raw"]))


def pin_rank(project, pinned):
    """Where the person pinned this project, or None."""
    return next((i for i, pin in enumerate(pinned) if is_pin_of(pin, project)), None)


# ------------------------------------------------------- the repository

def _repository(cwd):
    """The repository a folder is in, worktrees folded onto their parent:
    (the shared `.git` folder, the folder's path inside its checkout), or None.

    The walk stops at home: a repository there is a dotfiles repository, and
    would otherwise be the project of every plain folder under it.
    """
    here, home = Path(cwd), Path.home()
    for d in (here, *here.parents):
        if d == home:
            return None
        git = d / ".git"
        if git.is_dir():
            return git.resolve(), here.relative_to(d)
        if git.is_file():
            try:
                admin = d / git.read_text(encoding="utf-8").split(":", 1)[1].strip()
            except (OSError, IndexError):
                return None
            # A worktree names its parent's `.git`; a submodule's own folder
            # is the repository.
            try:
                common = (admin / (admin / "commondir").read_text(encoding="utf-8").strip()).resolve()
            except OSError:
                common = admin.resolve()
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


def _subfolders(path):
    try:
        with os.scandir(path) as entries:
            return [e.path for e in entries
                    if not e.name.startswith(".") and e.is_dir(follow_symlinks=False)]
    except OSError:
        return []


def holds_repositories(path):
    """Is this folder only a shelf: several repositories in it, or in the
    folders directly below it (`~/Projects/tiroir/{o,v,biz}`)?"""
    found = 0
    for child in _subfolders(path):
        if os.path.exists(os.path.join(child, ".git")):
            found += 1
        else:
            found += sum(os.path.exists(os.path.join(g, ".git")) for g in _subfolders(child))
        if found >= 2:
            return True
    return False


def project_of(cwd, folder_rule):
    """The project of the folder a session was launched in: its repository,
    or a client folder in it, else what the folder rule says, else None.

    A folder that only holds repositories is nobody's project -- sessions
    there are looking for one -- so the folder rule's answer is dropped.
    """
    # A launch folder that is not a full path would be read against wherever
    # the server happens to run.
    if not cwd or not os.path.isabs(cwd):
        return None
    found = _repository(cwd)
    if not found:
        label = folder_rule(cwd)
        if label and holds_repositories(cwd):
            label = None
        return _project("folder", label, label) if label else None
    common, inside = found
    # Known by its remote, so a second clone is the same project. With none,
    # by where its main checkout is.
    key = _remote(common) or str(common.parent)
    # Each `clients/<client>/` is a project of its own: the work of one
    # client is not the work of the one beside it, or of the repository.
    below = inside.parts[1:] if inside.parts[:1] == ("clients",) else (
        inside.parts if common.parent.name == "clients" else ())
    if below:
        return _project("client", f"{key}/{below[0]}", below[0])
    return _project("repo", key, _last(key))


# ----------------------------------------------------------- the guess

MIN_VOTES = 3          # below this it is noise, not a habit
LEAD = 1.5             # the winner has to be clearly ahead of the runner-up


def guess(paths, folder_rule):
    """The project a session keeps touching files in, or None.

    Only ever a suggestion. It is right when a session works in one place and
    silent when it does not -- being confidently wrong is the one outcome that
    matters here, because you would never know to look.
    """
    folders = collections.Counter(
        os.path.dirname(p) if os.path.splitext(p)[1] else p
        for p in paths if os.path.isabs(p))
    votes, known = collections.Counter(), {}
    for folder, n in folders.items():
        project = project_of(folder, folder_rule)
        if project:
            votes[project["id"]] += n
            known[project["id"]] = project
    ranked = votes.most_common(2)
    if not ranked or ranked[0][1] < MIN_VOTES:
        return None
    if len(ranked) > 1 and ranked[0][1] < ranked[1][1] * LEAD:
        return None
    return known[ranked[0][0]]


# ------------------------------------------------------ the boss's track

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


def _boss_tracks(members):
    """`{session key: track}` for each boss that has one. A boss's marker
    names it; the tmux session it runs in is only the fallback, because a
    renamed track keeps its old pane.

    `track` and `tmux` are read with `.get`: a row made by hand, as some
    tests do, may not carry them.
    """
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
# `Roster`, `Roster (current, max 2)`, `Worker roster` -- not `Roster correction`.
ROSTER = re.compile(r"^(?:worker )?roster(?: *\(.*\))?:?$")
FIRST_WORD = re.compile(r"[^\s(,/|]+")
TRACKER_READ = 1_000_000


def _roster_names(track):
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
            in_roster = bool(ROSTER.match(heading.group(1).strip("*_` ").casefold()))
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
        for track in self.live - self._read.keys():
            self._read[track] = _roster_names(track)
        return {t for t in sorted(self.live) if name in self._read[t]}


def _teams(members, boss_tracks):
    """`{worker name: the tracks of the running bosses that messaged it}`."""
    out = {}
    for m in members:
        if m["key"] in boss_tracks:
            for name in m.get("team") or []:
                out.setdefault(name, set()).add(boss_tracks[m["key"]])
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


# --------------------------------------------------------- the assignment

def merged_into(assigned):
    """`{project identity: [identities you moved into it]}`, by name: what the
    page offers to take back."""
    out = {}
    for key, value in assigned.items():
        if isinstance(value, str) and from_identity(key) and from_identity(value.strip()) and key != value.strip():
            out.setdefault(value.strip(), []).append(key)
    return {into: sorted(keys) for into, keys in out.items()}


def _is_assigned(assigned, key):
    return isinstance(assigned.get(key), str) and bool(assigned[key].strip())


def _assigned_project(value, known_as):
    """The project a session you assigned goes to: the identity you gave, or
    else the project that carries the name you gave -- the way it worked
    before projects had identities -- or else a new folder project."""
    by_identity = from_identity(value)
    if by_identity:
        return by_identity
    same = known_as.get(value)
    if same:
        return min(same, key=lambda p: (COLUMN_RANK[p["kind"]], p["id"]))
    return _project("folder", value, value)


def _follow_moves(project, assigned, known_as):
    """Where you moved this whole project to, or the project itself.

    `assigned` is keyed by a session (`provider:id`) or, since you can move a
    track or a repository, by the identity of the project the session would
    have been in. The two never meet: a session key starts with a provider,
    an identity with one of the four prefixes `KINDS` names.

    A project you moved away is gone, and whatever is put into it goes where
    it went -- a session assigned to it, another project moved into it. The
    walk never visits a project twice, so two projects moved into each other
    swap places instead of looping.
    """
    seen = {project["id"]}
    while project is not NO_PROJECT:
        value = assigned.get(project["id"])
        if not isinstance(value, str) or not value.strip():
            break
        target = _assigned_project(value.strip(), known_as)
        if target["id"] in seen:
            break
        seen.add(target["id"])
        project = target
    return project


def assign_all(members, folder_rule, assigned):
    """Every session's project: `{session key: project}`.

    First match wins, in the order the person thinks of it: their own setting
    for the session, then their move of its whole project, then the boss's
    track, then the repository, then the folder, then none.
    """
    boss_tracks = _boss_tracks(members)
    live = set(boss_tracks.values())
    teams = _teams(members, boss_tracks)
    trackers = Trackers(live)
    by_folder = {}      # sessions often share a launch folder; look it up once
    by_key = {}
    for m in members:
        if _is_assigned(assigned, m["key"]):
            continue
        track = boss_tracks.get(m["key"]) or _worker_track(m, live, teams, trackers)
        if track:
            by_key[m["key"]] = _project("track", track, track)
            continue
        if m["cwd"] not in by_folder:
            by_folder[m["cwd"]] = project_of(m["cwd"], folder_rule) or NO_PROJECT
        by_key[m["key"]] = by_folder[m["cwd"]]
    # What a plain name can mean: the name a project carries now, or the label
    # the folder rule gave the folders its sessions are in -- assignments were
    # made against those labels, `client › project`, before projects had names.
    known_as = {}
    for m in members:
        project = by_key.get(m["key"])
        if project is not None and project is not NO_PROJECT:
            for name in (project["raw"], folder_rule(m["cwd"])):
                if name and project not in known_as.setdefault(name, []):
                    known_as[name].append(project)
    for m in members:
        start = (_assigned_project(assigned[m["key"]].strip(), known_as)
                 if _is_assigned(assigned, m["key"]) else by_key[m["key"]])
        by_key[m["key"]] = _follow_moves(start, assigned, known_as)
    return by_key
