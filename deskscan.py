"""The merge desk's daily scan and tidy.

Once a day (`run_if_due`, called by the watcher's loop) AgentView does two things to the desk page.

**The scan** lists the open PRs of the repos of its projects (`project_repos`: the `repo:github.com/owner/name`
projects of the overview) and puts on the desk each one that is green, mergeable, not a draft, more than a day
old, and that no session ever handed over. Such an item says "found by the scan, no recommendation yet" on the
line where a handed-over item carries its recommendation, and carries no other: the person who hands a PR over
holds the reviews, the scan holds none. Green means at least one check and every check finished well (success,
neutral or skipped); no checks at all is not green. A PR whose key is on the page or anywhere in the desk log
(handed over, withdrawn, refused, merged) is never found: what a session once decided about it stays decided.

The scan is bounded: at most `MAX_REPOS` repos, `PER_REPO` PRs read from each and `TOTAL` read in all, whatever
`gh` returns. One repo's `gh` failure (or an answer that cannot be read) is logged and the next repo goes on.

**The tidy** removes an item from the page when its story is over and a day has passed since the log said so:
`merged` with its "Merged as" line on the page, `installed` with its "Installed as" line and the tool's receipt
at the pinned commit, or `withdrawn`. It never removes
  - an item that waits, is refused, is being pressed or was handed over again (its last log record decides);
  - an item with a comment thread that is not resolved, in any shape sheaf stores one (`open_thread`);
  - an Install item whose tool is not at the commit the item pinned (still behind, gone, or unreadable);
  - an item whose last log time cannot be read, or that has no record at all.

Each tidy is a line `tidied` in the log, which `desk status` skips: it still says what became of the item.

The day is kept in `desk-scan.json` beside the desk file, under `$XDG_STATE_HOME`, and is spent when the run
starts, so a restart, or a run that dies, does not run it again. Nothing here runs `gh` under the desk lock:
the lock is taken for each item written or dropped.
"""
import datetime
import json
import re
import time

import desk
import deskfile
import deskinstall
import deskwatch
import lines

DAY = 24 * 3600
PER_REPO = 20       # PRs read from one repo
TOTAL = 60          # PRs read in all
MAX_REPOS = 12
STAMP = "desk-scan.json"
FOUND = "found by the scan, no recommendation yet."
BY = "AgentView's scan"
GOOD_CHECK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
HEAD = re.compile(r"[0-9a-f]{40}")
CREATED = "%Y-%m-%dT%H:%M:%SZ"
JSON_FIELDS = "number,title,headRefOid,baseRefName,createdAt,mergeable,isDraft,statusCheckRollup"


class Failed(Exception):
    """One repo could not be listed; the text says why."""


# ------------------------------------------------------------------ the day

def stamp_path():
    return deskfile.path().parent / STAMP


def due(now):
    """True when a day has passed since the last run. A stamp that cannot be read, or that lies in the future,
    is no reason never to scan."""
    try:
        at = float(json.loads(stamp_path().read_text(encoding="utf-8"))["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return True
    return not 0 <= now - at < DAY


def spend(now):
    p = stamp_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    return lines.write_atomic(p, json.dumps({"at": now}))


def run_if_due(now=None, repos=None):
    """Scan and tidy once a day. Whether it ran. `repos` is a callable giving the repos to scan; it defaults
    to those of the overview's projects."""
    now = time.time() if now is None else now
    if not due(now):
        return False
    if not spend(now):                  # a day that cannot be kept would be spent again at every tick
        deskwatch.log.error("desk-scan", OSError(f"could not write {stamp_path()}"))
        return False
    try:
        scan((repos or project_repos)(), now)
    finally:
        tidy(now)
    return True


def scan_if_due():
    """The watcher's call. It holds nothing across `gh`: presses go on while it reads GitHub."""
    return run_if_due()


# ----------------------------------------------------------------- the repos

def _default_roster():
    import fleet
    with fleet.POLL:
        return fleet.roster()


def project_repos(roster=None):
    """The `owner/name` of each GitHub repository that is a project on the overview, in page order, once each.
    Projects of another kind (a track, a folder) and repos on another host are not asked of GitHub."""
    try:
        columns = (roster or _default_roster)()["columns"]
    except Exception as err:              # providers down, no roster yet: nothing to scan today
        deskwatch.log.error("desk-scan", err)
        return []
    out = []
    for column in columns if isinstance(columns, list) else []:
        ident = column.get("project") if isinstance(column, dict) else None
        if not isinstance(ident, str) or not ident.startswith("repo:github.com/"):
            continue
        repo = ident[len("repo:github.com/"):]
        try:
            desk.check_repo(repo)
        except desk.Refused:
            continue
        if repo not in out:
            out.append(repo)
    return out


def clean(repos):
    out = []
    for repo in repos if isinstance(repos, (list, tuple)) else []:
        try:
            desk.check_repo(repo)
        except desk.Refused:
            continue
        if repo not in out:
            out.append(repo)
    return out[:MAX_REPOS]


# ------------------------------------------------------------------ the scan

def list_prs(repo):
    code, out = deskwatch.gh("pr", "list", "-R", repo, "--state", "open", "--limit", str(PER_REPO),
                             "--json", JSON_FIELDS)
    if code:
        raise Failed(f"GitHub could not be asked about {repo}: {desk.flatten(out, 160)}")
    try:
        got = json.loads(out)
    except ValueError:
        got = None
    if not isinstance(got, list):
        raise Failed(f"GitHub's list of {repo}'s PRs could not be read")
    return got[:PER_REPO]


def green(rollup):
    """At least one check, every one of them finished and good. Nothing ran is not green."""
    if not isinstance(rollup, list) or not rollup:
        return False
    for c in rollup:
        if not isinstance(c, dict):
            return False
        if "conclusion" in c or "status" in c:
            ok = c.get("status") == "COMPLETED" and c.get("conclusion") in GOOD_CHECK
        else:
            ok = c.get("state") == "SUCCESS"
        if not ok:
            return False
    return True


def age(created, now):
    try:
        return now - datetime.datetime.strptime(created, CREATED).replace(tzinfo=datetime.timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None


def candidate(p, now):
    """(number, title, head, base) of a PR that is green, mergeable, not a draft and over a day old, else None."""
    if not isinstance(p, dict) or isinstance(p.get("number"), bool) or not isinstance(p.get("number"), int):
        return None
    old = age(p.get("createdAt"), now)
    if (p["number"] < 1 or p.get("isDraft") is not False or p.get("mergeable") != "MERGEABLE"
            or old is None or old <= DAY or not green(p.get("statusCheckRollup"))
            or not isinstance(p.get("headRefOid"), str) or not HEAD.fullmatch(p["headRefOid"])):
        return None
    base = p.get("baseRefName")
    return p["number"], p.get("title"), p["headRefOid"], base if isinstance(base, str) else ""


def item_block(repo, n, title, head, base):
    return "\n".join([
        f"- [ ] Merge {desk.key(repo, n)}: {desk.flatten(title if isinstance(title, str) else '') or '(no title)'}",
        f"  - Recommendation: {FOUND}",
        f"  - Pinned commit: {head}" + (f", into {desk.flatten(base, 80)}" if desk.flatten(base, 80) else ""),
        f"  - Handed over by {BY}, {time.strftime('%Y-%m-%d %H:%M')}.",
    ]) + "\n"


def add(repo, n, title, head, base):
    """Put the found PR on the desk, unless the desk has anything to do with it already. Whether it did."""
    k = desk.key(repo, n)
    with deskfile.locked():
        if any(i.key == k for i in deskfile.items()) or desk.history(k):
            return False
        deskfile.put_item(k, item_block(repo, n, title, head, base))
        desk.log("ready", k, pinned=head, by=BY)
    return True


def scan(repos, now=None):
    """The keys of the PRs put on the desk."""
    now = time.time() if now is None else now
    found, budget = [], TOTAL
    for repo in clean(repos):
        if budget <= 0:
            break
        try:
            prs = list_prs(repo)
            for p in prs[:budget]:
                budget -= 1
                got = candidate(p, now)
                if got and add(repo, *got):
                    found.append(desk.key(repo, got[0]))
        except (Failed, OSError) as why:
            deskwatch.log.error("desk-scan", why, key=repo)
    return found


# ------------------------------------------------------------------ the tidy

COMMENT = re.compile(r"<!--\s*(?:sheaf|rd)-comment\b")
MARKER = re.compile(r"(?:sheaf|rd)-comment(?=\s|$)")
FIELD = re.compile(r'\s*([a-z]+)=("([^"]*)"|\S+)')


def open_thread(block):
    """True when the block holds a comment thread that is not known to be resolved. Sheaf stores a thread
    inline, `<!-- sheaf-comment id=c3 by="Ada" at=... status=open quote="..." <lines of text and replies> -->`
    (the older marker is `rd-comment`), after text or on a line of its own, on one line with `<br>` or on
    several (`sheafmd/comments.py`, `_parse_one`). Only a comment whose head reads as sheaf reads it, with an
    id, no key twice and `status=resolved`, is closed. Everything else, a head that does not parse, an unknown
    status, a comment never closed in the block, is taken as open: a thread is lost for good when its item goes."""
    for m in COMMENT.finditer(block):
        end = block.find("-->", m.end())
        if end < 0:
            return True
        inner = block[m.start() + 4:end]
        head = re.split(r"\n|<br>", inner)[0].strip()
        marker = MARKER.match(head)
        if not marker:
            return True
        fields = {}
        for f in FIELD.finditer(head[marker.end():]):
            if f.group(1) in fields:
                return True
            fields[f.group(1)] = f.group(3) if f.group(3) is not None else f.group(2)
        if not fields.get("id") or fields.get("status", "open") != "resolved":
            return True
    return False


def settled_at(rec):
    try:
        return datetime.datetime.strptime(rec["at"], "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except (KeyError, ValueError, TypeError):
        return None


def results(block):
    return [l for l in block.split("\n") if deskfile.RESULT.match(l)]


def over(it, rec, now):
    """Is the item's story over, by its last log record, and a day ago?"""
    at = settled_at(rec)
    if at is None or now - at < DAY or open_thread(it.block):
        return False
    ev = rec["event"]
    if ev == "withdrawn":
        return True
    said = results(it.block)
    if ev == "merged":
        return not it.key.startswith("install:") and any(l.startswith(("  - Merged", "  - Already merged")) for l in said)
    if ev == "installed":
        tool = deskinstall.tool_named(it.key.removeprefix("install:")) if it.key.startswith("install:") else None
        return (bool(tool) and bool(it.pinned) and tool.rev == it.pinned
                and any(l.startswith(("  - Installed", "  - Already installed")) for l in said))
    return False


def tidy(now=None):
    """Take the items whose story is over off the page. The keys taken."""
    now = time.time() if now is None else now
    gone = []
    with deskfile.locked():
        every = [i.key for i in deskfile.items()]
        last = {}
        for rec in desk.history():
            if rec["event"] in ("ready", "pressing", "merged", "installed", "refused", "withdrawn"):
                last[rec["key"]] = rec
        for it in deskfile.items():
            if every.count(it.key) == 1 and it.key in last and over(it, last[it.key], now):
                deskfile.drop_item(it.key)
                desk.log("tidied", it.key, was=last[it.key]["event"])
                gone.append(it.key)
    return gone
