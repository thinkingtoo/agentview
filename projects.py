"""Which project each session belongs to.

The person thinks in projects; the machine knows folders, repositories and
bosses. This turns the second into the first, once per round, for the
overview's columns.
"""
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
