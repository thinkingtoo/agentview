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


def _project(ident, what="project"):
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
    put(config, "names", project, label)
    named = projects.from_identity(project)
    if not label and named and named["raw"] in _table(config, "names"):
        config["names"][project] = named["raw"]


def move(config, key, target):
    """Move a session (its key) or a whole track or repository (its identity)
    into a project. An empty target puts it back where it belongs. A move of a
    project holds for the sessions it will have: it is what the person wanted
    of the project, not of the sessions it has today."""
    if not isinstance(key, str) or not key:
        raise Refused("expected the key of a session or the identity of a project")
    target = target.strip()
    if target == key:
        raise Refused("a project cannot be moved into itself")
    put(config, "assign", key, target)


def pin(config, project, action, other=None):
    """`pin` puts a project last among the pinned, `unpin` takes it out, `swap`
    changes places with another pinned project -- the one beside it on the
    page, which is not the one beside it in the list when a pin names a
    project nobody is working in."""
    mine = _project(project)
    pinned = _pins(config)
    at = projects.pin_rank(mine, pinned)
    if action == "pin":
        if at is None:
            pinned.append(project)
    elif action == "unpin":
        pinned = [p for p in pinned if projects.pin_rank(mine, [p]) is None]
    elif action == "swap":
        theirs = _project(other, "the project to swap with")
        if other == project:
            raise Refused("a project cannot swap places with itself")
        to = projects.pin_rank(theirs, pinned)
        if at is not None and to is not None and at != to:
            pinned[at], pinned[to] = pinned[to], pinned[at]
    else:
        raise Refused("action must be pin, unpin or swap")
    config["pinned"] = pinned


def merge(config, source, target):
    """Put everything of one project into another, and carry with it all that
    was said about the first: the sessions it will have (a move of the whole
    project, so it holds), whatever was moved into it, its place among the
    pinned, its context line. Its name goes: the target keeps its own.

    Nothing is left pointing at `source`, so a project absorbed twice over,
    or one that was itself the target of an earlier merge, ends in one place.
    """
    gone, kept = _project(source, "source"), _project(target, "target")
    if source == target:
        raise Refused("a project cannot be merged into itself")
    assign = _table(config, "assign")
    for key, value in assign.items():
        if isinstance(value, str) and value.strip() == source:
            assign[key] = target
    assign[source] = target
    config["assign"] = {k: v for k, v in assign.items() if k != v}

    pinned, out = _pins(config), []
    had = projects.pin_rank(kept, pinned) is not None
    for p in pinned:
        if projects.pin_rank(gone, [p]) is not None and projects.pin_rank(kept, [p]) is None:
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
