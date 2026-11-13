"""What ships: whether merging a pull request into its base branch releases something, and what.

`read(repo, base, pinned, run)` answers with the lines of a "What ships" sub-list, or `[]` when the
merge ships nothing (the item stays a Merge item). A Deploy item carries what this returns under its
`What ships:` line, and the watcher reads it again just before the merge: a different answer refuses
the press.

Classification reads workflow files only. The base branch's `.github/workflows` are fetched through
the GitHub API into a folder of their own and `~/.claude/routines/branch_deploys.py` (which parses
YAML and runs nothing) is pointed at that folder: no checkout, and nothing from the pull request's
head is ever read or run. Exit 0 with deploy, publish, upload or secret lines is a Deploy; "tests
only" or exit 1 is a Merge. An answer that cannot be had is not "nothing ships": a classifier that is
missing or breaks makes the item a Deploy that says it could not tell; GitHub that cannot be asked
raises `Unreadable`.

`run(*gh_args) -> (exit code, output)` is `gh`; the caller passes its own.
"""
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

import desk

CLASSIFIER = Path.home() / ".claude" / "routines" / "branch_deploys.py"
OUTSIDE = "- Outside GitHub: "
COMMITS = "- Commits that go out"
SHOWN = 30                  # commits listed; the rest are counted
LINE = 140
WORKFLOW = re.compile(r"[A-Za-z0-9_.-]+\.ya?ml")
HINT = re.compile(r"^\s+(\d+): (.*)$")


def _line(prefix, text, limit=LINE):
    """A sub-list line: `prefix` is the dash and its indent, `text` one flattened line that cannot open a box or a comment."""
    return prefix + desk.flatten(text, limit)


class Unreadable(Exception):
    """GitHub could not be asked, or answered something unreadable: what ships is not known."""


def _gh(run, *args):
    code, out = run(*args)
    if code:
        if "HTTP 404" in out:
            return None
        raise Unreadable(desk.flatten(out or f"gh exited {code}", 160))
    return out


def _workflows(repo, base, run):
    """{file name: text} of the base branch's workflows; {} when it has none."""
    ref = urllib.parse.quote(base, safe="")
    listing = _gh(run, "api", f"repos/{repo}/contents/.github/workflows?ref={ref}")
    if listing is None:
        return {}
    try:
        names = [e["name"] for e in json.loads(listing) if e.get("type") == "file"]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise Unreadable("GitHub's list of workflows could not be read") from None
    found = {}
    for name in names:
        if not isinstance(name, str) or not WORKFLOW.fullmatch(name):
            continue
        text = _gh(run, "api", "-H", "Accept: application/vnd.github.raw",
                   f"repos/{repo}/contents/.github/workflows/{name}?ref={ref}")
        if text is None:
            raise Unreadable(f"{name} could not be read")
        found[name] = text
    return found


def _classify(files, base):
    """(deploy lines, why it could not be told). Lines: `- Fires on push to <base>: a.yml` + one nested line per hint."""
    if not files:
        return [], ""
    if not CLASSIFIER.is_file():
        return [], f"the classifier {CLASSIFIER} is missing"
    with tempfile.TemporaryDirectory(prefix="desk-ships-") as tmp:
        root = Path(tmp)
        (root / ".git").mkdir()
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        for name, text in files.items():
            (wf / name).write_text(text, encoding="utf-8")
        try:
            got = subprocess.run([sys.executable, str(CLASSIFIER), str(root), base], capture_output=True, text=True,
                                 stdin=subprocess.DEVNULL, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as err:
            return [], f"the classifier did not run: {err}"
    if got.returncode == 1:
        return [], ""
    if got.returncode != 0 or got.stderr.strip():
        return [], desk.flatten(got.stderr or got.stdout or f"the classifier exited {got.returncode}", 160)
    hits, current = {}, None
    for raw in got.stdout.splitlines():
        if raw and not raw[0].isspace():
            current = hits.setdefault(raw.strip(), [])
        elif current is not None and (hint := HINT.match(raw)):
            current.append((hint.group(1), hint.group(2)))
    deploying = {name: hs for name, hs in hits.items() if hs}
    if not deploying:
        return [], ""
    out = [_line("- ", f"Fires on push to {base}: " + ", ".join(deploying), 300)]
    out += [_line("  - ", f"{name}:{n}: {text}", LINE + 40) for name, hs in deploying.items() for n, text in hs]
    return out, ""


def _commits(repo, base, pinned, run):
    ref = urllib.parse.quote(base, safe="/")
    out = _gh(run, "api", f"repos/{repo}/compare/{ref}...{pinned}")
    if out is None:
        raise Unreadable("GitHub has no comparison of the base and the pinned commit")
    try:
        data = json.loads(out)
        total = int(data["total_commits"])
        shown = [(c["sha"][:7], c["commit"]["message"].split("\n")[0]) for c in data["commits"]]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise Unreadable("GitHub's list of commits could not be read") from None
    lines = [f"{COMMITS} ({total}):"]
    lines += [_line("  - ", f"{sha} {msg}") for sha, msg in shown[:SHOWN]]
    if total > min(SHOWN, len(shown)):
        lines.append(f"  - and {total - min(SHOWN, len(shown))} more")
    return lines


def read(repo, base, pinned, run, outside="", commits=None):
    """The "What ships" lines for merging `pinned` into `base`; `[]` when nothing ships and
    nothing was stated. `outside` is the person's own line for a repo run from outside GitHub;
    `commits=True` lists the commits even when the workflows ship nothing (the re-check of an item that already shows them)."""
    deploy, cannot = _classify(_workflows(repo, base, run), base)
    if not (deploy or cannot or outside or commits):
        return []
    head = []
    if outside:
        head.append(_line(OUTSIDE, outside, 300))
    if cannot:
        head.append(_line("- ", f"Could not tell what ships: {cannot}", 300))
    return head + deploy + _commits(repo, base, pinned, run)


def compared(lines):
    return [l for l in lines if not l.startswith(OUTSIDE)]


def changed(old, new):
    """"" when the two answers agree (the person's own Outside line is not compared); else what differs."""
    old, new = compared(old), compared(new)
    if old == new:
        return ""
    gone = [l.strip(" -") for l in old if l not in new]
    came = [l.strip(" -") for l in new if l not in old]
    parts = (["now: " + "; ".join(came)] if came else []) + (["no longer: " + "; ".join(gone)] if gone else [])
    return desk.flatten("; ".join(parts) or "its lines were reordered", 240)
