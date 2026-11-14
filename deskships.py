"""What ships: whether merging a pull request into its base branch releases something, and what.

`read(repo, base, pinned, run)` answers with the lines of a "What ships" sub-list, or `[]` when the
merge ships nothing (the item stays a Merge item). A Deploy item carries what this returns under its
`What ships:` line, and the watcher reads it again just before the merge: a different answer refuses
the press.

A merge also ships what its own commits add: the push after the merge runs the workflow files of the
merged commit, so a pull request that changes `.github/workflows/` is a Deploy item whatever the base
says (the file names come from the compare call, no content of the head is read).

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
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

import desk

PYTHON = "/usr/bin/python3" if shutil.which("python3", path="/usr/bin") else sys.executable   # one interpreter for hand-over and press
FILES_CUT = 300             # GitHub's compare lists at most this many files
CLASSIFIER = Path.home() / ".claude" / "routines" / "branch_deploys.py"
OUTSIDE = "- Outside GitHub: "
COMMITS = "- Commits that go out"
SHOWN = 100                 # commits listed; the rest are counted
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
        if not isinstance(name, str):
            continue
        if not WORKFLOW.fullmatch(name):
            if name.lower().endswith((".yml", ".yaml")):
                raise Unreadable(f"the workflow file name {desk.flatten(name, 60)!r} cannot be fetched safely")
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
    try:
        with tempfile.TemporaryDirectory(prefix="desk-ships-") as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            wf = root / ".github" / "workflows"
            wf.mkdir(parents=True)
            for name, text in files.items():
                (wf / name).write_text(text, encoding="utf-8")
            got = subprocess.run([PYTHON, "-W", "ignore", str(CLASSIFIER), str(root), base], capture_output=True,
                                 text=True, stdin=subprocess.DEVNULL, timeout=30)
    except (OSError, ValueError, subprocess.TimeoutExpired) as err:
        return [], f"the classifier did not run: {type(err).__name__}"       # no path or text in it: it must read the same twice
    # Python exits 1 on any traceback, so exit 1 means "nothing fires" only when it said nothing at all.
    if got.stderr.strip() or got.returncode not in (0, 1) or (got.returncode == 1 and got.stdout.strip()):
        return [], desk.flatten(got.stderr or got.stdout or f"the classifier exited {got.returncode}", 160)
    if got.returncode == 1:
        return [], ""
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


def _compare(repo, base, pinned, run):
    """(the "Commits that go out" lines, the workflow files the pull request changes, whether the file list is cut)."""
    ref = urllib.parse.quote(base, safe="/")
    out = _gh(run, "api", f"repos/{repo}/compare/{ref}...{pinned}")
    if out is None:
        raise Unreadable("GitHub has no comparison of the base and the pinned commit")
    try:
        data = json.loads(out)
        total = int(data["total_commits"])
        shown = [(c["sha"][:7], c["commit"]["message"].split("\n")[0]) for c in data["commits"]]
        files = [f for entry in data["files"] for f in (entry["filename"], entry.get("previous_filename"))
                 if isinstance(f, str)]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise Unreadable("GitHub's list of commits could not be read") from None
    lines = [f"{COMMITS} ({total}):"]
    lines += [_line("  - ", f"{sha} {msg}") for sha, msg in shown[:SHOWN]]
    if total > min(SHOWN, len(shown)):
        lines.append(f"  - and {total - min(SHOWN, len(shown))} more")
    flows = sorted({f for f in files if f.startswith(".github/workflows/")})
    return lines, flows, len(data["files"]) >= FILES_CUT


def read(repo, base, pinned, run, outside="", commits=None):
    """The "What ships" lines for merging `pinned` into `base`; `[]` when nothing ships and
    nothing was stated. `outside` is the person's own line for a repo run from outside GitHub;
    `commits=True` lists the commits even when the workflows ship nothing (the re-check of an item that already shows them)."""
    deploy, cannot = _classify(_workflows(repo, base, run), base)
    commit_lines, flows, cut = _compare(repo, base, pinned, run)
    if flows:
        deploy = deploy + [FLOWS] + [_line("  - ", f, 300) for f in flows]
    if cut and not cannot:
        cannot = f"GitHub lists only {FILES_CUT} changed files, so a changed workflow could be missed"
    if not (deploy or cannot or outside or commits):
        return []
    head = []
    if outside:
        head.append(_line(OUTSIDE, outside, 300))
    if cannot:
        head.append(_line("- ", f"Could not tell what ships: {cannot}", 300))
    return head + deploy + commit_lines


FLOWS = "- This pull request changes workflow files:"
UNKNOWN = "- Could not tell what ships"


def _split(lines):
    """(lines compared as they are, commit shas, changed workflow files, whether commits were hidden behind "and N more")."""
    rest, shas, flows, cut, inside, in_flows = [], [], set(), False, False, False
    for l in lines:
        if l.startswith(OUTSIDE):
            continue
        in_files = in_flows and l.startswith("  - ")
        if in_files:
            flows.add(l[4:])
            continue
        in_flows = l == FLOWS
        if in_flows:
            continue
        if l.startswith(COMMITS):
            inside = True
        elif inside and l.startswith("  - "):
            cut = cut or l.startswith("  - and ")
            shas.append((l[4:].split(" ", 1)[0], l.strip(" -")))
        else:
            inside = False
            rest.append(l)
    return rest, shas, flows, cut


def changed(old, new):
    """Both sides are raw `read` output, compared character for character: nothing is stripped or folded, because
    what the page makes of a line is no business of this check. "" when what ships is the same; else what differs. Not compared: the person's Outside line, and the
    commits and changed workflow files that left the range (once the PR this one stacks on is merged they do);
    only a new one counts, and no commit counts when the stored range was cut."""
    old_rest, old_shas, old_flows, old_cut = _split(old)
    new_rest, new_shas, new_flows, _ = _split(new)
    old_set = set(old_rest)
    new_set = set(new_rest)
    gone = [l.strip(" -") for l in old_rest if l not in new_set]
    came = [l.strip(" -") for l in new_rest if l not in old_set]
    came += [f"workflow file {f}" for f in sorted(new_flows - old_flows)]
    if not old_cut:
        came += [f"commit {text}" for sha, text in new_shas if sha not in {s for s, _ in old_shas}]
    came += [l.strip(" -") for l in new_rest if l.startswith(UNKNOWN)]
    parts = (["now: " + "; ".join(dict.fromkeys(came))] if came else []) + (["no longer: " + "; ".join(gone)] if gone else [])
    return desk.flatten("; ".join(parts), 240)
