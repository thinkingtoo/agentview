"""Correcting projects by hand: move, rename, merge and pin.

Each function edits a config dict in place and writes nothing: the server runs
it inside `fleet.update_config`, which reads the file, calls it and replaces
the file under one lock. That is what lets a rename, a move and a pin made at
the same moment all land. A request that makes no sense raises `Refused`
before anything is changed, so nothing is written for it.

A project is named by its identity (`track:x`, `repo:host/owner/name`,
`client:…`, `folder:x`), the same string `columns` carries and `projects.py`
keys everything by. A session is named by its key (`provider:id`). The two
cannot be mistaken for each other: only a project starts with one of those four.
"""
import projects


class Refused(ValueError):
    """The request cannot mean anything; the route answers 400 with the reason."""


class Stale(Refused):
    """The request is about a card as the page drew it, and another tab has
    changed it since; the route answers 409 and nothing is written. The page
    reads the roster again and the person clicks on what is there now."""


def _named(ident, what="project"):
    got = projects.from_identity(ident) if isinstance(ident, str) else None
    if got is None:
        raise Refused(f"{what} must name a project: track:x, repo:x, client:x or folder:x")
    return got


def _table(config, field):
    got = config.get(field)
    return dict(got) if isinstance(got, dict) else {}


def _pins(config):
    got = config.get("pinned")
    return list(got) if isinstance(got, list) else []


def _shown(shown):
    """What the page says it shows -- project identities or plain names -- or
    nothing, for a caller that does not say."""
    if shown is None:
        return []
    if not isinstance(shown, list) or not all(isinstance(s, str) for s in shown):
        raise Refused("shown must be a list of names")
    return shown


def _spread(pinned, shown, touched):
    """A pin written by plain name, from before projects had identities (an old
    config.json may still hold them), pins every project that carries the name --
    a track and a folder can share one. Where the page shows more than one of
    them and one is the project being corrected (`touched`), the pin is written
    out as one pin each, in the order the page shows them, so that each can be
    moved, unpinned or merged on its own. Any other plain pin is left as it is:
    a project with no session yet still reads the name.

    A card the plain pin held keeps its place when it is also pinned by identity
    further on: the page shows it at the first of its pins."""
    shown = [(ident, got) for ident in shown if (got := projects.from_identity(ident))]
    touched = [got for ident in touched if isinstance(ident, str) and (got := projects.from_identity(ident))]
    out, spread = [], False
    for pin in pinned:
        mine = []
        if isinstance(pin, str) and projects.from_identity(pin) is None:
            mine = list(dict.fromkeys(ident for ident, got in shown if projects.is_pin_of(pin, got)))
        if len(mine) > 1 and any(projects.is_pin_of(pin, got) for got in touched):
            out.extend(mine)
            spread = True
        else:
            out.append(pin)
    if not spread:
        return pinned
    seen, once = set(), []
    for pin in out:
        if isinstance(pin, str) and projects.from_identity(pin):
            if pin in seen:
                continue
            seen.add(pin)
        once.append(pin)
    return once


def put(config, field, key, value):
    """Set `config[field][key]`, or take it out when the value is empty."""
    table = _table(config, field)
    table.pop(key, None) if not value else table.update({key: value})
    config[field] = table


def rename(config, project, label):
    """Your name for a project. An empty label takes the rename back -- to the
    raw name, even when a rename from before projects had identities (keyed by
    the plain name) would otherwise show through again."""
    label = label.strip()
    _current(config, project)
    put(config, "names", project, label)
    named = projects.from_identity(project)
    if not label and named and named["raw"] in _table(config, "names"):
        config["names"][project] = named["raw"]


def line(config, project, text):
    """Your own context line for a project, kept under its identity. An empty
    one takes it back, and the source the roster finds takes its place."""
    _named(project)
    _current(config, project)
    put(config, "project_lines", project, text)


def _moved_to(config, project):
    """The project this one was moved into -- merged into, or moved as a whole --
    or None when it is its own card. What the page writes is one step deep: a
    project that took others is itself never moved without them going with it."""
    value = _table(config, "assign").get(project)
    value = value.strip() if isinstance(value, str) else ""
    return value if value != project and projects.from_identity(value) else None


def _current(config, *named):
    """Every project a request names must still be a card. One that was moved
    away since the page was drawn (another tab merged it) is not: whatever the
    request would do to it lands on a project with no card, or on nothing, or
    -- an arrow, a pin -- against what the click said. All of it is refused,
    here, once, for every route. A name that is not a project's identity (a
    session's key, a plain name from an old config) is not looked at. What the
    page says it shows (`shown`) is a list of names like any other: one that has
    gone means the view is old, and the click that came with it cannot be
    trusted."""
    for ident in named:
        if isinstance(ident, str) and projects.from_identity(ident) and _moved_to(config, ident):
            raise Stale("changed in another tab")


def move(config, key, target, was=None):
    """Move a session (its key) or a whole track or repository (its identity)
    into a project. An empty target puts it back where it belongs. A move of a
    project holds for the sessions it will have: it is what the person wanted
    of the project, not of the sessions it has today.

    `was` is where the page saw `key` moved to, for the way back from a card
    (`includes X . undo`): if X is not there any more, it is not that move the
    person is taking back."""
    if not isinstance(key, str) or not key:
        raise Refused("expected the key of a session or the identity of a project")
    if was is not None and not isinstance(was, str):
        raise Refused("was must name the project it was moved into")
    target = target.strip()
    if target == key:
        raise Refused("a project cannot be moved into itself")
    if was is not None and _moved_to(config, key) != was.strip():
        raise Stale("changed in another tab")
    if target:
        _current(config, key, target)
    put(config, "assign", key, target)


def _beside(pinned, shown, project, other, side):
    """Whether `project` and `other` are still in the order the arrow was drawn
    for: `side` is where the click puts `project`, after `other` or before it,
    so it has to be on the other side of it now. And no card the page showed has
    come between them since: the page's neighbours are the cards it shows, so
    those it showed between the two (a filter hides some) may still be there and
    no others. A pin the page did not show -- a project nobody is working in --
    is not a card, and the swap goes past it."""
    rank = lambda got: projects.pin_rank(got, pinned)
    at, to = rank(project), rank(other)
    if at is None or to is None or (at < to) != (side == "after"):
        return False
    cards = [(ident, got) for ident in shown if (got := projects.from_identity(ident))]
    order = [got for _, got in cards]
    if project not in order or other not in order:
        return True
    first, last = sorted((order.index(project), order.index(other)))
    saw = [ident for ident, _ in cards[first + 1:last]]
    lo, hi = sorted((at, to))
    now = sorted(((ident, rank(got)) for ident, got in cards if rank(got) is not None and lo < rank(got) < hi),
                 key=lambda pair: pair[1])
    return saw == [ident for ident, _ in now]


def pin(config, project, action, other=None, shown=None, side=None):
    """`pin` puts a project last among the pinned, `unpin` takes it out, `swap`
    changes places with another pinned project -- the one beside it on the
    page, which is not the one beside it in the list when a pin names a
    project nobody is working in. `shown` is the pinned projects the page
    shows, in order: it is what tells apart two that share a pin by plain name.

    A swap says which way it goes (`side`, the arrow's own word: before or
    after `other`). A tab that is behind sends the same arrow again after
    another has made the move, and a swap alone would undo it: it is refused
    unless the two are still in the order the arrow was drawn for."""
    mine = _named(project)
    shown = _shown(shown)
    if action not in ("pin", "unpin", "swap"):
        raise Refused("action must be pin, unpin or swap")
    theirs = None
    if action == "swap":
        theirs = _named(other, "the project to swap with")
        if other == project:
            raise Refused("a project cannot swap places with itself")
        if side not in (None, "before", "after"):
            raise Refused("side must be before or after")
    _current(config, project, other if action == "swap" else None, *shown)
    pinned = _spread(_pins(config), shown, [project, other])
    at = projects.pin_rank(mine, pinned)
    if action == "pin":
        if at is None:
            pinned.append(project)
    elif action == "unpin":
        pinned = [p for p in pinned if not projects.is_pin_of(p, mine)]
    else:
        if side and not _beside(pinned, shown, mine, theirs, side):
            raise Stale("changed in another tab")
        to = projects.pin_rank(theirs, pinned)
        if at is not None and to is not None and at != to:
            pinned[at], pinned[to] = pinned[to], pinned[at]
    config["pinned"] = pinned


def merge(config, source, target, shown=None):
    """Put everything of one project into another, and carry with it all that
    was said about the first: the sessions it will have (a move of the whole
    project, so it holds), the projects moved into it, its place among the
    pinned, its context line. Its name goes: the target keeps its own.

    No project is left moved into `source`, so one absorbed twice over, or one
    that was itself the target of an earlier merge, ends in one place. Neither
    project may have been merged away since the page was drawn (another tab):
    that is refused, so no ring of moves can be closed from a tab that is behind.
    A session you moved there is left as you moved it: it follows the project,
    and taking the merge back puts it where you had put it.
    """
    gone, kept = _named(source, "source"), _named(target, "target")
    if source == target:
        raise Refused("a project cannot be merged into itself")
    shown = _shown(shown)
    _current(config, source, target, *shown)
    assign = _table(config, "assign")
    for key, value in assign.items():
        if isinstance(value, str) and value.strip() == source and projects.from_identity(key):
            assign[key] = target
    assign[source] = target
    config["assign"] = {k: v for k, v in assign.items() if k != v}

    pinned, out = _spread(_pins(config), shown, [source, target]), []
    had = projects.pin_rank(kept, pinned) is not None
    for p in pinned:
        if projects.is_pin_of(p, gone) and not projects.is_pin_of(p, kept):
            if not had:                       # the target steps into the first place the source had
                out.append(target)
                had = True
            continue
        out.append(p)
    if "pinned" in config or out:
        config["pinned"] = out

    names = _table(config, "names")
    if names.pop(source, None) is not None:
        config["names"] = names
    own = _table(config, "project_lines")
    line = own.pop(source, None)
    if line is not None:
        if not own.get(target):
            own[target] = line
        config["project_lines"] = own
