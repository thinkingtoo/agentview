#!/usr/bin/env python3
"""Drive the real page in a browser. Run by hand; not part of `unittest discover`.

    python3 tests/ui_smoke.py BASE_URL CONFIG_PATH SERVER_PID

All three are required and none has a default. BASE_URL is a throwaway server
you started yourself (`http://127.0.0.1:PORT/`, never the one the owner's
terminal tabs depend on: 8765 is refused), CONFIG_PATH the config.json that
server reads, SERVER_PID the process that must be listening on that port.
Start it from the worktree with its own config and `XDG_STATE_HOME`, on a port
chosen by binding port 0.

Nothing here reaches a real session, and nothing here can launch anything:

  * Most passes are *routed*. The page's HTML, the roster, the search and every
    POST are answered by `page.route` from fixtures built below, so a jump, a
    reopen, a revival, a rename, a snapshot never leave the browser, and no
    request carries a real session key. A request the routes do not know is
    aborted and fails the run.
  * One pass is not routed (R21): it loads the page from the server given, lets
    the page poll the server's own `/api/roster` and asserts that real columns
    render. It clicks nothing, writes nothing, saves no screenshot (it shows
    real sessions), and any request that is not a GET is aborted and fails.
  * One pass starts a server of its own (`e2e_pass`): `tests/hand_server.py`,
    with invented sessions, a config in a new temp dir, state under the temp
    dir, a port the system picks (8765 refused) and its pid proven with `ss`.
    It clicks the by-hand controls and reads that config back, then restarts
    the server on it. Only that temp dir is written, and it is removed; the
    page may reach nothing but that server.
  * `stale_pass` starts a server of the same kind and holds some of its own tabs
    back, to click on cards another tab has since merged away or moved.
  * The config file given is only read: its hash is taken before and after.

Playwright is needed (`pip install playwright`); the chromium it drives must
already be installed.
"""
import copy
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
PAGE = (HERE.parent / "index.html").read_text(encoding="utf-8") \
    .replace("{{ZOOM}}", "1").replace("{{HOME}}", "/home/alice")
failures = []
errors = []        # page errors, console errors and dialogs, from every page
posted = []        # every body the routed pages POSTed, from every pass
BOMB = "<img src=x onerror=alert(1)>"
ATTR = '"><img src=x onerror=alert(1)> x="'        # breaks out of a quoted attribute, if one is not escaped


def check(label, ok, detail=""):
    print(f"{label:<58} {'OK' if ok else 'FAILED ' + str(detail)}")
    if not ok:
        failures.append(label)


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def head_line(page):
    """The header's counts as a person reads them: one line, plain spaces."""
    return re.sub(r"\s+", " ", page.locator("#count").inner_text().replace("\xa0", " ")).strip()


def head_counts(page):
    """The overview header's last three parts: the roster's counts, as said."""
    return head_line(page).split(" · ")[-3:]


# --- fixtures -----------------------------------------------------------------
# One description of a session produces the row the block view reads (`blocks`,
# which the chime and the counts also read) and the tile the overview prints
# (`columns`), so the two never disagree about who is waiting.

def S(key, name, status="idle", flag=None, *, note="", line="", tags=(), can=True, need="",
      mv=None, moving=None, stuck=None, via=None, why="", **extra):
    """`mv` is the movement sign's text, `moving` whether the server counts the
    session as moving (by default: busy and not stuck). `stuck` is the kind the
    server gives the tile; a session with a line that wants something gets the
    line's kind, as the server does."""
    if moving is None:
        moving = status == "busy" and flag != "stuck"
    if stuck is None and need:
        stuck = needs("line", "1 thing left for you", {"text": need})
    if stuck is None and flag == "stuck":
        stuck = hung_kind(int(note.rstrip("m")))
    return {"key": key, "name": name, "status": status, "flag": flag, "note": note,
            "line": line, "tags": list(tags), "can": can, "need": need, "mv": mv,
            "moving": moving, "stuck": stuck, "extra": extra, "via": via, "why": why}


def needs(source, reason, context):
    """What the server says of a session that waits on you."""
    return {"kind": "needs", "source": source, "reason": reason, "context": context}


def hung_kind(minutes, tool="", ago=None):
    """What the server says of a busy session nothing proves is moving."""
    return {"kind": "hung", "source": "silence", "reason": f"Not moving for {minutes} min",
            "context": {"tool": tool, "ago": ago}}


def limit_kind(resets=None, held=22.0, text=""):
    return {"kind": "limit", "source": "api", "reason": "Rate limit",
            "context": {"resetsAt": resets, "held": held, "text": text}}


def error_kind(reason, text="", ago=3.0, type_="server_error"):
    return {"kind": "error", "source": "api", "reason": reason,
            "context": {"type": type_, "text": text, "ago": ago}}


def request_kind(what):
    """A dialog that waits on an approval and is neither a question nor a permission prompt."""
    return needs("request", what[:1].upper() + what[1:], {"what": what})


def asks(question, options, header="Publish", multi=False):
    return needs("question", "Question", {"questions": [
        {"question": question, "header": header, "multi": multi,
         "options": [{"label": l, "description": d} for l, d in options]}]})


def prompts(tool, command="", target="", copy=None):
    return needs("permission", "Permission prompt", {
        "tool": tool, "command": command, "target": target,
        "copy": bool(command) if copy is None else copy})


def state_of(sessions):
    kinds = {s["stuck"]["kind"] for s in sessions if s["stuck"]}
    for kind in ("needs", "error", "hung", "limit"):
        if kind in kinds:
            return kind
    return "moving" if any(s["moving"] for s in sessions) else "idle"


def member(s, project):
    m = {"name": s["name"], "status": s["status"], "kind": "interactive", "provider": "claude",
         "cwd": f"/home/alice/Projects/{project}", "tmux": "", "pid": 111, "key": s["key"],
         "updatedAt": 1787830000000, "project": project, "title": s["line"] or f"{s['name']} at work",
         "prompt": "carry on", "branch": "main", "canJump": s["can"], "assigned": False,
         "suggestion": None, "quietFor": 0.2, "toolFor": None, "flag": s["flag"],
         "startedAt": 1787830000000,
         "ask": s["need"], "n": 1 if s["need"] else 0, "blocked": bool(s["need"])}
    if s["flag"] == "waiting":
        m["waitingFor"] = s["note"]
    if s["flag"] in ("stuck", "tool"):
        m["quietFor"] = float(s["note"].rstrip("m"))
        m["toolFor"] = m["quietFor"] if s["flag"] == "tool" else None
    return {**m, **s["extra"]}


def jump_field(s):
    """What the server says of the jump: pane, attach, or none and why."""
    via = s["via"] or ("pane" if s["can"] else "none")
    return {"via": via} if via != "none" else {"via": "none", "reason": s["why"] or "no terminal"}


def counted(s):
    """The header count the server puts a session in: stuck wins over moving, and
    an idle session is in none."""
    if s["stuck"]:
        return "needs" if s["stuck"]["kind"] == "needs" else "otherStuck"
    return "moving" if s["moving"] else None


def tile(s):
    # The overview never gets the `tool` flag (the movement sign says it) nor
    # `stuck` (it is the kind Hung).
    flag = None if s["flag"] in ("tool", "stuck") else s["flag"]
    sign = s["mv"] or (f"waiting on: Running the full suite, {s['note'][:-1]} min"
                       if s["flag"] == "tool" else None)
    return {"key": s["key"], "name": s["name"], "provider": "claude", "status": s["status"],
            "tags": s["tags"], "line": s["line"], "flag": flag,
            "flagNote": "" if flag is None else s["note"],
            "movement": sign and {"kind": "waiting", "text": sign}, "moving": s["moving"],
            "blocked": bool(s["need"]), "need": s["need"], "stuck": s["stuck"],
            "counted": counted(s), "jump": jump_field(s),
            "find": f"{s['name']}\n{s['line']}".lower()}


# 30 per-minute counts, oldest first; None is a minute the server did not see.
STRIPS = {"maple": [None] * 6 + [0, 0, 1, 3, 2, 0, 0, 0, 4, 9, 6, 2, 0, 0, 1, 1, 5, 7, 8, 3, 2, 4, 6, 1]}


def mix(sessions):
    out = {"moving": 0, "stuck": 0, "idle": 0}
    for s in sessions:
        out["stuck" if s["stuck"] else "moving" if s["moving"] else "idle"] += 1
    return out


def roster(projects, **top):
    """projects: [(key, display name, [S, ...])], key "" for No project."""
    blocks, columns = [], []
    for key, name, sessions in projects:
        orphan = key == ""
        members = [member(s, key or "none") for s in sessions]
        blocks.append({
            "project": key or "No project", "label": name, "orphan": orphan, "routines": False,
            "renamed": False, "pinned": False, "branches": ["main"], "updatedAt": 1787830000000,
            "busy": sum(s["status"] == "busy" for s in sessions),
            "alarms": sum(s["flag"] in ("waiting", "stuck") for s in sessions),
            "ready": sum(s["flag"] == "ready" for s in sessions), "members": members})
        columns.append({"project": key, "name": name, "raw": key,
                        "kind": "none" if orphan else "folder",
                        "strip": STRIPS.get(key, [0] * 29 + [2]), "summary": mix(sessions),
                        "state": state_of(sessions), "sessions": [tile(s) for s in sessions]})
    counts = {k: sum(counted(s) == k for _, _, sessions in projects for s in sessions)
              for k in ("needs", "otherStuck", "moving")}
    return {"blocks": blocks, "columns": columns, "counts": counts, "banners": [],
            "hold": False, "chime": True, "providers": {},
            "restore": None, "closed": [], "saved": None, **top}


def routine_block():
    ms = [member(S(k, n, "busy"), "Routines") | {"routine": r, "canJump": False, "project": None}
          for k, n, r in (("r1", "Ansgar", "nightly-report"), ("r2", "Bruno", "disk-check"))]
    return {"project": "Routines", "label": "Routines", "orphan": False, "routines": True,
            "renamed": False, "pinned": False, "branches": [], "busy": 2, "alarms": 0, "ready": 0,
            "updatedAt": 1787830000000, "members": ms}


MAPLE = ("maple", "maple", [
    S("m1", "Vera", "waiting", "waiting", note="input needed", line="Port the importer", tags=["boss"],
      stuck=asks("Publish the notes page under /docs?", [("Yes, under /docs", ""), ("No", "")])),
    S("m2", "Mei", "busy", "stuck", note="17m", line="Rewrite the parser"),
    S("m3", "Nour", "idle", "ready", line="Two had no composer — guess or skip?",
      need="Which table should I drop?"),
    S("m4", "Aziz", "busy", "tool", note="34m", line="Running the full suite"),
    S("m5", "Dmitri", "idle", can=False, moving=True, mv="waiting on: Run the tests, 5 min")])
PMD = ("pmd", "pmd", [S("p1", "Lennart", "idle", tags=["boss", "codex"], line="Plan the cutover"),
                      S("p2", "Kasper", "busy", line="Schema migration", mv="writing · 8s ago")])
LOOSE = ("", "No project", [S("o1", "Rosalie", "idle", line="a loose end")])


def overview_fixture():
    """Columns in an order no browser rule would produce (not alphabetical, the
    waiting session not first), blocks the other way round with a routine block
    the columns leave out: whatever the page shows came from `columns`."""
    got = roster([PMD, MAPLE, LOOSE])
    got["blocks"] = [routine_block()] + list(reversed(got["blocks"]))
    return got


def many(n):
    return roster([(f"proj{i:02d}", f"proj{i:02d}", [S(f"x{i}", f"S{i}", "idle", line="working on it")])
                   for i in range(n)])


def waiting(*names, ready=()):
    sessions = [S("c1", "ALPHA", "busy")]
    sessions += [S(n, n.upper(), "waiting", "waiting", note="input needed") for n in names]
    sessions += [S(n, n.upper(), "idle", "ready") for n in ready]
    return roster([("alpha", "alpha", sessions)])


CLOSED = [{"id": "gone-1", "name": "Zora", "title": "Fix the importer", "cwd": "/home/alice/Projects/maple",
           "at": 1787830000}]


def hit(id, name, live=False):
    return {"id": id, "name": name, "title": "Fix the importer", "cwd": "/home/alice/Projects/maple",
            "live": live, "project": "maple", "active": "2026-10-18T10:00:00",
            "passage": {"prompt": "the importer drops rows", "reply": "found it in parse()"}}


FOUND = {"query": "importer", "index": {"conversations": 2, "last_run": None}, "meaning": {"state": "on"},
         "results": [hit("old-1", "Ilse"), hit("run-1", "Tamsin", live=True)]}


# --- the fake server ------------------------------------------------------------
class Fake:
    """Answers the page's whole conversation with the server, from fixtures.

    Stateful just enough that a click shows its effect (a name, a pin, the hold,
    the chime), so the page is checked end to end without a server behind it.
    """

    def __init__(self, body):
        self.body = copy.deepcopy(body)
        self.found = FOUND
        self.posts = []        # (path, body) for every POST the page made
        self.stray = []        # anything the routes do not know
        self.answer = {}       # path -> the reply to give instead of {"ok": true}
        self.status = {}       # path -> the HTTP status to give instead of 200 (nothing is applied then)
        self.polls = 0         # how many times the page read /api/roster
        self.hold = False      # keep /api/jump unanswered, in `held`, until the test answers it
        self.held = []

    def of(self, path):
        return [b for p, b in self.posts if p == path]

    def block(self, project):
        return next(b for b in self.body["blocks"] if b["project"] == project)

    def apply(self, path, b):
        if path == "/api/hold":
            self.body["hold"] = b["hold"]
        elif path == "/api/chime":
            self.body["chime"] = b["chime"]
        elif path == "/api/name":
            blk = self.block(b["project"])
            blk["label"], blk["renamed"] = b["label"], bool(b["label"])
        elif path == "/api/line":
            for blk in self.body["blocks"]:
                for m in blk["members"]:
                    if m["key"] == b["key"]:
                        m["title"], m["overridden"] = b["text"], bool(b["text"])
        elif path == "/api/assign":
            for blk in self.body["blocks"]:
                for m in blk["members"]:
                    if m["key"] == b["key"]:
                        m["assigned"] = bool(b["project"])
            self.move_tile(b["key"], b["project"])
            for c in self.body["columns"]:
                c["merged"] = [m for m in c.get("merged", []) if m["project"] != b["key"]]
        elif path == "/api/pin":
            self.pin_column(b)
        elif path == "/api/keep":
            self.keep(b["key"], b["pinned"])
        elif path == "/api/merge":
            cols = self.body["columns"]
            source = next(c for c in cols if c["project"] == b["source"])
            target = next(c for c in cols if c["project"] == b["target"])
            target["sessions"].extend(source["sessions"])
            target.setdefault("merged", []).append({"project": source["project"], "name": source["name"]})
            cols.remove(source)
        elif path == "/api/order":
            pins = b["pinned"]
            for blk in self.body["blocks"]:
                blk["pinned"] = blk["project"] in pins
            self.body["blocks"].sort(key=lambda blk: pins.index(blk["project"])
                                     if blk["project"] in pins else len(pins))

    def keep(self, key, pinned):
        """The server's pin, as far as the page can tell: a pinned pill is a full
        tile that says it is pinned, and an unpinned tile that was one shrinks."""
        for c in self.body["columns"]:
            if pinned:
                for p in c.get("pills", []):
                    if p["key"] == key:
                        c["pills"].remove(p)
                        c["sessions"].append({**tile(S(key, p["name"], "idle", line=p["line"], tags=p["tags"])),
                                              "pinned": True})
                        return
            else:
                for t in c["sessions"]:
                    if t["key"] == key and t.get("pinned"):
                        c["sessions"].remove(t)
                        c.setdefault("pills", []).append(P(key, t["name"], 180, line=t["line"]))
                        return

    def pin_column(self, b):
        """The server's pin, as far as the page can tell: pinned first in pin order."""
        cols = self.body["columns"]
        pins = [c["project"] for c in cols if c.get("pinned")]
        if b["action"] == "pin":
            pins.append(b["project"])
        elif b["action"] == "unpin":
            pins.remove(b["project"])
        else:
            i, j = pins.index(b["project"]), pins.index(b["with"])
            pins[i], pins[j] = pins[j], pins[i]
        for c in cols:
            c["pinned"] = c["project"] in pins
        cols.sort(key=lambda c: (c["kind"] == "none", pins.index(c["project"]) if c["project"] in pins else len(pins)))

    def move_tile(self, key, project):
        """A hand-moved tile goes to the column asked for; the way back (an empty
        project) leaves it where it is, which is enough for the page."""
        cols = self.body["columns"]
        for c in cols:
            for t in c["sessions"]:
                if t["key"] == key:
                    t["assigned"] = bool(project)
                    target = next((x for x in cols if x["project"] == project), None)
                    if target is not None and target is not c:
                        c["sessions"].remove(t)
                        target["sessions"].append(t)
                    return

    def handle(self, route):
        req = route.request
        url = urllib.parse.urlsplit(req.url)
        json_ = lambda data, status=200: route.fulfill(status=status, content_type="application/json", body=json.dumps(data))
        if req.method == "GET" and url.path in ("/", "/index.html"):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=PAGE)
        elif req.method == "GET" and url.path == "/api/roster":
            self.polls += 1
            json_(self.body)
        elif req.method == "GET" and url.path == "/api/search":
            json_(self.found)
        elif req.method == "GET" and url.path == "/favicon.ico":
            route.fulfill(status=204)
        elif req.method == "POST" and url.path.startswith("/api/"):
            body = json.loads(req.post_data or "{}")
            self.posts.append((url.path, body))
            posted.append(body)
            status = self.status.get(url.path, 200)
            if status == 200:
                self.apply(url.path, body)
            if self.hold and url.path == "/api/jump":
                self.held.append(route)
                return
            json_(self.answer.get(url.path, {"ok": True, "did": "opened", "changed": False}), status)
        else:
            self.stray.append(f"{req.method} {req.url}")
            route.abort()


def new_page(browser, fake, width=1700, clipboard=False):
    """A routed page. `clipboard` grants the page the clipboard, which the
    browser gives only to a secure origin: open it at `http://localhost/`."""
    if clipboard:
        page = browser.new_context(viewport={"width": width, "height": 2400},
                                   permissions=["clipboard-read", "clipboard-write"]).new_page()
    else:
        page = browser.new_page(viewport={"width": width, "height": 2400})
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
    page.on("dialog", lambda d: (errors.append(f"dialog: {d.message}"), d.dismiss()))
    page.route("**/*", fake.handle)
    return page


def open_at(page, path="/"):
    page.goto(f"http://smoke.invalid{path}", wait_until="load")


def poll_now(page):
    """The page's own `load()`, instead of waiting three seconds for the timer."""
    page.evaluate("load()")
    page.wait_for_timeout(150)


def open_editor(page, locator):
    page.wait_for_function("() => !document.querySelector('input.inline')")
    locator.click()
    page.wait_for_selector("input.inline", timeout=5000)


# --- passes ---------------------------------------------------------------------
def real_pass(browser, url, pid):
    """R21. The server's own roster, unrouted and read-only: columns render."""
    port = urllib.parse.urlsplit(url).port
    held = subprocess.run(["ss", "-ltnp", f"sport = :{port}"], capture_output=True, text=True).stdout
    check("the listener on the test port is the server given", f"pid={pid}," in held, held.strip())
    if f"pid={pid}," not in held:
        return set()
    page = browser.new_page(viewport={"width": 1700, "height": 2400})
    seen, aborted = [], []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
    page.on("dialog", lambda d: (errors.append(f"dialog: {d.message}"), d.dismiss()))

    def read_only(route):
        req = route.request
        host = urllib.parse.urlsplit(req.url)
        if req.method == "GET" and host.netloc == urllib.parse.urlsplit(url).netloc \
                and (host.path in ("/", "/index.html", "/api/roster") or host.path == "/favicon.ico"):
            seen.append(host.path)
            route.continue_()
        else:
            aborted.append(f"{req.method} {req.url}")
            route.abort()
    page.route("**/*", read_only)
    page.goto(url, wait_until="load")
    page.wait_for_function("() => document.getElementById('stamp').textContent.startsWith('updated')", timeout=15000)
    # Taken together in one evaluation, so a poll cannot land between the two.
    got = page.evaluate("""() => ({
      columns: COLUMNS.length, tiles: COLUMNS.reduce((a, c) => a + c.sessions.length, 0),
      dom: document.querySelectorAll('.ov-col').length, domTiles: document.querySelectorAll('.tile').length,
      keys: COLUMNS.flatMap(c => c.sessions.map(t => t.key)),
      empty: !!document.querySelector('.empty') })""")
    check("unrouted: the page draws one column per column the server sent",
          got["columns"] == got["dom"] and got["tiles"] == got["domTiles"]
          and (got["columns"] > 0 or got["empty"]), got | {"keys": len(got["keys"])})
    # Read in one evaluation: the counts the header shows, the counts the roster
    # sent, and the tiles that name each, from the same poll.
    head = page.evaluate("""() => { const named = {};
      for (const c of COLUMNS) for (const t of c.sessions) named[t.counted] = (named[t.counted] || 0) + 1;
      const shown = [...document.querySelectorAll('button.hc')].map(b => b.textContent.trim());
      return { sent: COUNTS, named, shown }; }""")
    sent = head["sent"]
    want = [f"{sent['needs']} {'needs you' if sent['needs'] == 1 else 'need you'}",
            f"{sent['otherStuck']} other stuck", f"{sent['moving']} moving"]
    check("unrouted: the header shows the roster's counts, and they are the tiles that name them",
          head["shown"] == want and all(head["named"].get(k, 0) == sent[k] for k in ("needs", "otherStuck", "moving")), head)
    page.wait_for_timeout(3500)       # one more poll, still no clicks
    check("unrouted: read-only (only GET page and roster)", not aborted and set(seen) <= {"/", "/api/roster", "/favicon.ico"},
          aborted or sorted(set(seen)))
    print(f"   (real roster: {got['columns']} columns, {got['tiles']} tiles; {len(seen)} GETs; nothing saved)")
    page.close()
    return set(got["keys"])


def overview_pass(browser):
    fake = Fake(overview_fixture())
    page = new_page(browser, fake)
    open_at(page)
    page.wait_for_selector(".ov-col")
    cols = lambda: page.locator(".ov-col").count()
    names = lambda: [t.strip() for t in page.locator(".ov-name").all_inner_texts()]

    check("one column per project", cols() == 3, cols())
    check("columns in the order the server sent, not the blocks' or a sort",
          names() == ["pmd", "maple", "No project"], names())
    check("the routine block is not a column", "Routines" not in names())
    check("sessions in the order the server sent",
          page.locator('.ov-col[data-project="maple"] .tile').evaluate_all("els => els.map(e => e.dataset.sid)")
          == ["m1", "m2", "m3", "m4", "m5"])
    check("the project card is its name, its state, then its movement strip and mix",
          page.locator('.ov-col[data-project="maple"] .ov-head > *')
          .evaluate_all("els => els.map(e => e.className)") == ["ov-top", "ov-state", "ov-mv"])
    check("one tile per session", page.locator(".tile").count() == 8, page.locator(".tile").count())

    t = lambda sid: page.locator(f'.tile[data-sid="{sid}"]')
    check("a waiting tile that needs you says so, once, and keeps its waiting tint",
          t("m1").locator(".flag.needs").count() == 1 and t("m1").locator(".flag.waiting").count() == 0
          and "waiting" in t("m1").get_attribute("class") and "needs" in t("m1").get_attribute("class"))
    check("a busy session nothing proves is moving is Hung, and says for how long",
          t("m2").locator(".flag.hung").inner_text().lower() == "hung"
          and t("m2").locator(".stuck-box .reason").inner_text() == "Not moving for 17 min"
          and t("m2").locator(".flag.stuck").count() == 0)
    check("a long tool call is a movement sign now, not a flag, and no alarm tint",
          t("m4").locator(".mv").inner_text() == "waiting on: Running the full suite, 34 min"
          and t("m4").locator(".flag").count() == 0
          and not any(c in t("m4").get_attribute("class") for c in ("waiting", "stuck")))
    check("a writing session says so", t("p2").locator(".mv").inner_text() == "writing · 8s ago")
    check("a session with no sign has no sign line", t("m5").locator(".mv").count() == 1
          and t("m3").locator(".mv").count() == 0)
    check("an idle session with a job running has the moving dot, not the idle one",
          t("m5").locator(".dot.busy").count() == 1 and t("m5").locator(".dot.idle").count() == 0)
    maple = page.locator('.ov-col[data-project="maple"]')
    bars = maple.locator(".strip i")
    check("the card draws 30 bars", bars.count() == 30, bars.count())
    check("minutes the server did not see are dotted stubs, not empty bars",
          maple.locator(".strip i.u").count() == 6 and maple.locator(".strip i.z").count() == 7,
          (maple.locator(".strip i.u").count(), maple.locator(".strip i.z").count()))
    heights = bars.evaluate_all("els => els.map(e => e.offsetHeight)")
    check("the busiest minute is the tallest bar, within the strip's height",
          max(heights) == heights[bars.evaluate_all("els => els.map(e => e.title)").index("9 writes")]
          and 20 <= max(heights) <= 28, heights)
    check("the card counts moving, stuck and idle",
          maple.locator(".mix").inner_text() == "2 moving · 3 stuck · 0 idle", maple.locator(".mix").inner_text())
    check("a project that counts nothing still draws a strip of 30",
          page.locator('.ov-col[data-project=""] .strip i').count() == 30)
    check("finished and unread is a tick, not a dot",
          t("m3").locator(".tick").count() == 1 and t("m3").locator(".dot").count() == 0)
    check("a busy session has the breathing dot", t("m2").locator(".dot.busy").count() == 1
          and t("p2").locator(".dot.busy").count() == 1)
    check("tags print", [x.lower() for x in t("p1").locator(".bg-tag").all_inner_texts()] == ["boss", "codex"]
          and t("m1").locator(".bg-tag.boss").count() == 1)
    check("the line sits under the name", t("m2").locator(".tline").inner_text() == "Rewrite the parser"
          and t("m5").locator(".tline").count() == 0)
    check("open ↗ only where there is a pane to go to",
          t("m1").locator(".go:not(.none)").inner_text() == "open ↗"
          and t("m5").locator(".go:not(.none)").count() == 0)
    check("a session that wrote down what it is blocked on shows it, whatever its flag",
          t("m3").locator(".stuck-box .say").inner_text() == "Which table should I drop?"
          and t("m5").locator(".stuck-box").count() == 0)

    # Geometry: box 3.
    widths = page.locator(".ov-col").evaluate_all("els => els.map(e => e.offsetWidth)")
    check("every column is at least 230 px", min(widths) >= 230, widths)
    check("the page does not scroll sideways with three projects",
          page.evaluate("() => document.getElementById('main').scrollWidth <= document.getElementById('main').clientWidth"))
    short = lambda: page.locator('.ov-col[data-project="pmd"]').evaluate("e => e.offsetHeight")
    tall = lambda: page.locator('.ov-col[data-project="maple"]').evaluate("e => e.offsetHeight")
    before = (short(), tall())
    fake.body = roster([PMD, ("maple", "maple", MAPLE[2] + [S(f"z{i}", f"Z{i}", line="more and more") for i in range(12)]), LOOSE])
    poll_now(page)
    check("a tall column does not change a short one's height",
          short() == before[0] and tall() > before[1], (before, short(), tall()))
    heights = page.locator(".ov-col").evaluate_all("els => els.map(e => e.offsetHeight)")
    check("columns end where their own sessions end (not stretched)", len(set(heights)) == 3, heights)

    # Sideways scrolling, with more projects than fit.
    fake.body = many(10)
    poll_now(page)
    wide = page.evaluate("""() => { const m = document.getElementById('main'), d = document.documentElement;
      return { main: m.scrollWidth > m.clientWidth, page: d.scrollWidth > d.clientWidth,
               overflow: getComputedStyle(m).overflowX } }""")
    check("with ten projects the row scrolls sideways", wide["main"] and wide["overflow"] == "auto", wide)
    check("and the page itself does not", not wide["page"], wide)
    check("columns keep 230 px when they no longer fit",
          min(page.locator(".ov-col").evaluate_all("els => els.map(e => e.offsetWidth)")) >= 230)
    page.evaluate("document.getElementById('main').scrollLeft = 400")
    poll_now(page)
    check("a repaint keeps your place in the row",
          page.evaluate("document.getElementById('main').scrollLeft") == 400,
          page.evaluate("document.getElementById('main').scrollLeft"))

    # The filter box.
    fake.body = overview_fixture()
    poll_now(page)
    box = page.locator("#q")
    box.fill("ve")
    page.wait_for_timeout(400)
    check("two letters do not filter", page.locator(".tile").count() == 8)
    box.fill("parser")
    page.wait_for_timeout(500)
    check("a session's words filter its tile", page.locator(".tile").count() == 1
          and page.locator(".ov-col").count() == 1 and page.locator(".tile .nm").inner_text() == "Mei")
    box.fill("maple")
    page.wait_for_timeout(500)
    check("a project that matches keeps every tile", page.locator(".tile").count() == 5
          and page.locator(".ov-col").count() == 1)
    box.fill("zzzznothing")
    page.wait_for_timeout(500)
    check("it says when nothing matches", "Nothing matches" in page.locator(".empty").inner_text())
    box.press("Escape")
    page.wait_for_timeout(500)
    check("Escape clears it", box.input_value() == "" and page.locator(".ov-col").count() == 3)
    page.keyboard.press("/")
    check("“/” goes to the filter", page.evaluate("document.activeElement.id") == "q")
    box.fill("")

    # Jumping. Every POST is the route's, so nothing is raised anywhere.
    t("m1").click()
    page.wait_for_timeout(300)
    check("a tile with a pane posts /api/jump with its key", fake.of("/api/jump") == [{"key": "m1"}], fake.posts)
    fake.answer["/api/jump"] = {"ok": False, "reason": "no pane for this one"}
    t("m2").click()
    page.wait_for_function("document.getElementById('stamp').textContent.includes('no pane')", timeout=3000)
    check("a jump that fails says why", "no pane for this one" in page.locator("#stamp").inner_text())
    n = len(fake.of("/api/jump"))
    t("m5").click()
    page.wait_for_timeout(300)
    check("a tile with nowhere to go is marked seen, not jumped",
          fake.of("/api/seen") == [{"key": "m5"}] and len(fake.of("/api/jump")) == n, fake.posts)

    # Closed and reopen (the closed list revives; a search result reopens).
    fake.body = overview_fixture() | {"closed": CLOSED}
    poll_now(page)
    check("the closed button counts them", page.locator("#closed").inner_text() == "⟲ closed 1"
          and not page.locator("#closed").is_hidden())
    page.locator("#closed").click()
    check("and opens the list", "Zora" in page.locator("#closedlist").inner_text())
    page.locator("#closedlist .back").click()
    page.wait_for_timeout(300)
    check("clicking one posts /api/revive with its id", fake.of("/api/revive") == [{"id": "gone-1"}], fake.posts)
    page.mouse.click(5, 700)
    find = page.locator("#find")
    find.fill("importer")
    page.wait_for_selector("#found .hit")
    check("search lists what it found", page.locator("#found .hit").count() == 2
          and "running" in page.locator('#found .hit[data-id="run-1"]').inner_text().lower())
    page.locator('#found .hit[data-id="old-1"]').click()
    page.wait_for_function("document.querySelector('#found .hit[data-id=\"old-1\"]').innerText.includes('opened in a new tab')")
    check("a result reopens through /api/reopen", fake.of("/api/reopen") == [{"id": "old-1"}], fake.posts)
    fake.answer["/api/reopen"] = {"ok": True, "did": "jumped"}
    page.locator('#found .hit[data-id="run-1"]').click()
    page.wait_for_function("document.querySelector('#found .hit[data-id=\"run-1\"]').innerText.includes('jumped to it')")
    check("a running one is jumped to", fake.of("/api/reopen")[-1] == {"id": "run-1"})
    find.press("Escape")

    # The chime and the tab title read `blocks` in both views; the overview's
    # header is the roster's counts (`header_pass`), not the chime's alarms.
    check("the overview's header counts what the roster counted, not the chime's alarms",
          head_counts(page) == ["2 need you", "1 other stuck", "3 moving"], head_line(page))
    check("the tab title counts what wants you: waiting, stuck and blocked",
          page.title().startswith("(3)"), page.title())
    check("the overview has no hold button and a way to the block view",
          page.locator("#hold").is_hidden() and page.locator("#view").get_attribute("href") == "?view=blocks")
    check("overview: nothing stray reached the routes", not fake.stray, fake.stray)
    page.close()


def P(key, name, minutes, line="", via="pane", why="", tags=()):
    """A finished session as the server sends it: one line at the foot of a column."""
    jump = {"via": via} if via != "none" else {"via": "none", "reason": why or "no terminal"}
    text = f"{minutes // 60} h" if minutes >= 60 else f"{minutes} min"
    return {"key": key, "name": name, "tags": list(tags), "idle": {"since": float(minutes), "text": text},
            "line": line, "jump": jump, "find": f"{name}\n{line}".lower()}


def with_pills(got, project, pills):
    """The column of `project` carries `pills`; the rest carry none, as the server sends them."""
    for c in got["columns"]:
        c["pills"] = pills if c["project"] == project else c.get("pills", [])
    return got


def finished_fixture():
    got = roster([
        ("maple", "maple", [
            S("m1", "Vera", "busy", mv="writing · 8s ago"),
            S("m2", "Mei", "idle", line="Release notes")]),
        ("orchard", "orchard", [S("o1", "Odile", "idle", moving=True, mv="waiting on: Run the tests, 5 min")]),
        ("delta", "delta", []),
        ("harbor", "harbor", [S("k1", "Kasper", "idle", line="Tide table review")])])
    got["columns"][0]["sessions"][1].update(
        unread=True, handover="Release notes drafted; the docs page links to it.")
    got["columns"][3]["sessions"][0].update(unread=True, handover=BOMB)
    for c in got["columns"]:
        c.setdefault("pills", [])
    got["columns"][0]["pills"] = [
        P("p1", "Femi", 180, line="Saved-card form", tags=["boss"]),
        P("p2", "Gus", 130, via="none", why="attached, but in no window that can be raised")]
    got["columns"][2]["pills"] = [P("d1", "Hanne", 600, line="Nightly rebuild"), P("d2", "Ilse", 400)]
    got["columns"][3]["pills"] = [P("h1", BOMB, 300, line=ATTR, tags=[BOMB])]
    return got


def finished_pass(browser):
    """Ticket 10: the one-line pills at the foot of a column. The page prints the
    roster's `pills` and decides nothing: a pill counts toward nothing, its hover
    is the working-on line, a click jumps (and a pill with nowhere to go says so
    and posts nothing), and the pin is the server's."""
    fake = Fake(finished_fixture())
    page = new_page(browser, fake)
    open_at(page)
    page.wait_for_selector(".ov-col")
    col = lambda p: page.locator(f'.ov-col[data-project="{p}"]')
    pill = lambda sid: page.locator(f'.pill[data-sid="{sid}"]')
    tile_ = lambda sid: page.locator(f'.tile[data-sid="{sid}"]')

    check("a pill shows its name and how long it has been idle",
          pill("p1").locator(".nm").inner_text() == "Femi" and pill("p1").locator(".for").inner_text() == "3 h")
    check("the pills are at the foot of their column, after the tiles",
          col("maple").evaluate("e => e.lastElementChild.classList.contains('pills')")
          and col("maple").evaluate("e => [...e.children].map(c => c.className.split(' ')[0]).join()")
          == "ov-head,tile,tile,pills")
    check("a pill is one line", pill("p1").bounding_box()["height"] < 34, pill("p1").bounding_box())
    check("its working-on line is its hover", pill("p1").get_attribute("title") == "Saved-card form")
    check("and a boss pill still says it led", pill("p1").locator(".bg-tag.boss").count() == 1)
    check("a project with only pills is its card, ALL IDLE, with nothing counted",
          col("delta").locator(".tile").count() == 0 and col("delta").locator(".pill").count() == 2
          and col("delta").locator(".ov-state").inner_text() == "ALL IDLE"
          and col("delta").locator(".mix").inner_text().strip() == "0 moving · 0 stuck · 0 idle",
          col("delta").inner_text())
    check("the header counts the tiles and none of the pills",
          head_line(page).split(" · ")[:2] == ["4 sessions", "4 projects"] and head_counts(page)
          == ["0 need you", "0 other stuck", "2 moving"], head_line(page))
    check("a tile with an unread handover quotes it and says unread",
          tile_("m2").locator(".said").inner_text() == "“Release notes drafted; the docs page links to it.”"
          and tile_("m2").locator(".flag.unread").inner_text().lower() == "unread")

    pill("p1").click()
    page.wait_for_timeout(300)
    check("a pill posts /api/jump with its key and nothing else", fake.posts == [("/api/jump", {"key": "p1"})], fake.posts)
    check("and a jump that worked shows no reason", pill("p1").locator(".why").count() == 0)

    fake.answer["/api/jump"] = {"ok": False, "reason": "wezterm cli spawn failed"}
    pill("p1").click()
    pill("p1").locator(".why").wait_for(timeout=3000)
    check("a failed jump leaves its reason on the pill",
          pill("p1").locator(".why").inner_text() == "wezterm cli spawn failed" and "failed" in pill("p1").get_attribute("class"))
    check("and marks nothing seen", fake.of("/api/seen") == [], fake.posts)
    poll_now(page)
    page.wait_for_function("document.querySelectorAll('.pill .why').length === 0", timeout=3000)
    check("until the next poll", pill("p1").locator(".why").count() == 0 and pill("p1").count() == 1)

    n = len(fake.posts)
    check("a pill with no terminal says so, greyed, before any click",
          pill("p2").locator(".go").inner_text() == "no terminal" and "can" not in pill("p2").get_attribute("class").split()
          and pill("p2").locator(".go").get_attribute("title") == "attached, but in no window that can be raised")
    pill("p2").click()
    pill("p2").locator(".why.note").wait_for(timeout=3000)
    check("a click on it says why, and posts nothing (it marks nothing seen)",
          len(fake.posts) == n and pill("p2").locator(".why.note").inner_text()
          == "attached, but in no window that can be raised", fake.posts[n:])

    # Pin: a pill becomes a tile that says it is pinned, and back.
    fake.posts.clear()
    pill("p1").hover()
    pill("p1").locator("button.keep").click()
    tile_("p1").wait_for(timeout=3000)
    check("the pin button posts /api/keep and jumps nowhere", fake.posts == [("/api/keep", {"key": "p1", "pinned": True})], fake.posts)
    check("a pinned pill is a full tile with an unpin button, and no longer a pill",
          pill("p1").count() == 0 and tile_("p1").locator("button.keep.on").inner_text() == "unpin"
          and tile_("p1").locator("button.keep.on").get_attribute("aria-pressed") == "true")
    poll_now(page)
    check("the pin survives a poll", tile_("p1").count() == 1 and pill("p1").count() == 0)
    check("the header still counts it as nothing: an idle tile is in no count",
          head_counts(page) == ["0 need you", "0 other stuck", "2 moving"] and head_line(page).split(" · ")[0] == "5 sessions",
          head_line(page))
    fake.posts.clear()
    tile_("p1").hover()
    tile_("p1").locator("button.keep").click()
    pill("p1").wait_for(timeout=3000)
    check("unpinning posts pinned false and the tile shrinks to a pill again",
          fake.posts == [("/api/keep", {"key": "p1", "pinned": False})] and tile_("p1").count() == 0, fake.posts)

    # Lighting up a count: the pills fade with the tiles that are not in it, and
    # a column with none of those is only its card.
    page.locator('button.hc[data-count="moving"]').click()
    check("a lit count fades the pills, and a column with nothing lit is only its card",
          pill("p1").evaluate("e => e.classList.contains('dim')") and col("maple").locator(".pills").is_visible()
          and not col("delta").locator(".pills").is_visible() and not col("harbor").locator(".pills").is_visible())
    page.locator('button.hc[data-count="moving"]').click()

    # Search keeps working through pills.
    page.fill("#q", "hanne")
    page.wait_for_timeout(300)
    check("the filter finds a pill by its name and its line, and keeps the column",
          page.locator(".ov-col").count() == 1 and col("delta").locator(".pill").count() == 1
          and col("delta").locator(".pill .nm").inner_text() == "Hanne", page.locator(".ov-col").count())
    page.fill("#q", "")
    page.wait_for_timeout(300)
    check("and clearing it brings them all back", page.locator(".pill").count() == 5, page.locator(".pill").count())

    # R7: a hostile name, line, tag and handover are text, in a text position and in an attribute.
    hostile = pill("h1")
    check("R7: markup in a pill's name, line and tag is text and builds no element",
          page.locator('.ov-col[data-project="harbor"] img').count() == 0
          and hostile.locator(".nm").inner_text() == BOMB and hostile.get_attribute("title") == ATTR
          and hostile.locator(".bg-tag").inner_text().lower() == BOMB.lower()
          and hostile.evaluate("e => [...e.attributes].map(a => a.name).sort().join()") == "class,data-sid,title")
    check("R7: markup in an unread handover is text and builds no element",
          tile_("k1").locator(".said").inner_text() == f"“{BOMB}”" and tile_("k1").locator("img").count() == 0)
    check("finished: nothing stray reached the routes", not fake.stray, fake.stray)
    page.close()


def header_fixture():
    """Eight sessions in four projects: one needs you, two are otherwise stuck
    (Hung, Limit), three are moving, two are idle. `delta` has nothing to light."""
    return roster([
        ("alpha", "alpha", [
            S("v1", "Vera", "waiting", "waiting", note="input needed",
              stuck=asks("Publish the notes page?", [("Yes", ""), ("No", "")])),
            S("m1", "Mei", "busy", "stuck", note="17m"),
            S("n1", "Nour", "busy", mv="writing · 8s ago")]),
        ("beta", "beta", [
            S("o1", "Odile", "idle", stuck=limit_kind(None, 5.0)),
            S("k1", "Kasper", "idle")]),
        ("gamma", "gamma", [
            S("f1", "Femi", "busy", mv="writing · 3s ago"),
            S("g1", "Gus", "idle", moving=True, mv="waiting on: Run the tests, 5 min")]),
        ("delta", "delta", [S("h1", "Hanne", "idle")])])


def header_pass(browser):
    """Ticket 09: the header's counts, the light a click puts on them, and the
    banner. The page counts and decides nothing: it prints the roster's `counts`,
    lights the tiles whose `counted` names the count, and prints `banners`."""
    fake = Fake(header_fixture())
    page = new_page(browser, fake)
    open_at(page)
    page.wait_for_selector(".ov-col")
    btn = lambda k: page.locator(f'button.hc[data-count="{k}"]')
    lit = lambda: sorted(page.locator(".tile.lit .nm").all_inner_texts())
    dim = lambda: page.locator(".tile.dim").count()
    shrunk = lambda: sorted(page.locator(".ov-col.shrunk").evaluate_all("els => els.map(e => e.dataset.project)"))
    widths = lambda: page.locator(".ov-col").evaluate_all("els => els.map(e => e.offsetWidth)")

    check("the header counts what needs you, what else is stuck and what is moving",
          head_counts(page) == ["1 needs you", "2 other stuck", "3 moving"], head_line(page))
    check("and what is on the page: sessions and projects",
          head_line(page).split(" · ")[:2] == ["8 sessions", "4 projects"], head_line(page))
    check("each count is a button, and none is pressed", page.locator("button.hc").count() == 3
          and all(btn(k).get_attribute("aria-pressed") == "false" for k in ("needs", "otherStuck", "moving")))
    check("nothing is lit, faded or shrunk to begin with", not lit() and not dim() and not shrunk())

    before = widths()
    btn("otherStuck").click()
    check("a click lights up the sessions in that count", lit() == ["Mei", "Odile"], lit())
    check("fades the rest", dim() == 6, dim())
    check("and shrinks the columns with none to their card", shrunk() == ["delta", "gamma"], shrunk())
    check("a shrunk column keeps its card and shows none of its tiles",
          page.locator('.ov-col[data-project="gamma"] .ov-head').is_visible()
          and not page.locator('.ov-col[data-project="gamma"] .tile').first.is_visible()
          and page.locator('.ov-col[data-project="alpha"] .tile.lit').first.is_visible())
    check("columns keep their width", widths() == before, (before, widths()))
    check("the count that is lit says so", btn("otherStuck").get_attribute("aria-pressed") == "true"
          and btn("needs").get_attribute("aria-pressed") == "false")
    check("lighting up posts nothing and jumps nowhere", fake.posts == [], fake.posts)

    poll_now(page)
    check("a poll keeps the light", lit() == ["Mei", "Odile"] and shrunk() == ["delta", "gamma"], (lit(), shrunk()))

    btn("otherStuck").click()
    check("a second click clears it", not lit() and not dim() and not shrunk()
          and btn("otherStuck").get_attribute("aria-pressed") == "false", (lit(), dim(), shrunk()))

    # By keyboard: the header is rebuilt when a count lights, and the focus must
    # survive it, or the second Enter goes nowhere.
    focused = lambda: page.evaluate("document.activeElement?.closest('button.hc')?.dataset.count || ''")
    btn("needs").focus()
    page.keyboard.press("Enter")
    check("Enter on a focused count lights it, and the focus stays on it",
          lit() == ["Vera"] and focused() == "needs", (lit(), focused()))
    page.keyboard.press("Enter")
    check("a second Enter clears it, and the focus is still on it",
          not lit() and not shrunk() and focused() == "needs", (lit(), shrunk(), focused()))
    page.locator("body").click(position={"x": 2, "y": 400})

    btn("moving").click()
    check("moving lights the moving ones, including a session waiting on a job",
          lit() == ["Femi", "Gus", "Nour"] and shrunk() == ["beta", "delta"], (lit(), shrunk()))
    btn("needs").click()
    check("a click on another count moves the light",
          lit() == ["Vera"] and shrunk() == ["beta", "delta", "gamma"]
          and btn("moving").get_attribute("aria-pressed") == "false", (lit(), shrunk()))
    btn("needs").click()

    # The page lights what the roster counted, whatever the tile's other fields say.
    cols = fake.body["columns"]
    next(t for c in cols for t in c["sessions"] if t["name"] == "Kasper")["counted"] = "needs"
    poll_now(page)
    btn("needs").click()
    check("it lights the tiles the roster counted, not ones it works out itself",
          lit() == ["Kasper", "Vera"], lit())
    btn("needs").click()
    # ... and prints the roster's numbers, not a count of its own.
    fake.body["counts"] = {"needs": 7, "otherStuck": 0, "moving": 12}
    poll_now(page)
    check("the numbers are the roster's, however many tiles there are",
          head_counts(page) == ["7 need you", "0 other stuck", "12 moving"], head_line(page))
    check("a count of nothing is not a button", btn("otherStuck").is_disabled() and not btn("needs").is_disabled())
    btn("otherStuck").click(force=True)
    check("and a click on it lights nothing", not lit() and not shrunk(), (lit(), shrunk()))
    fake.body["counts"] = {"needs": 1, "otherStuck": 2, "moving": 3}
    poll_now(page)

    # A lit count that has emptied clears itself instead of hiding every session.
    btn("needs").click()
    fake.body["counts"] = {"needs": 0, "otherStuck": 2, "moving": 3}
    poll_now(page)
    check("a lit count that falls to nothing clears itself",
          not lit() and not dim() and not shrunk() and btn("needs").is_disabled(), (lit(), dim(), shrunk()))
    fake.body["counts"] = {"needs": 1, "otherStuck": 2, "moving": 3}
    poll_now(page)
    check("and does not light again when it comes back", not lit() and not shrunk()
          and btn("needs").get_attribute("aria-pressed") == "false", (lit(), shrunk()))

    # A count the page cannot read as a number shows as 0 and is off, so it
    # clears the light the same way, instead of hiding every session.
    btn("needs").click()
    fake.body["counts"] = {"needs": "3", "otherStuck": 2, "moving": 3}
    poll_now(page)
    check("a count that is not a number clears the light like a count of nothing",
          not lit() and not dim() and not shrunk() and btn("needs").is_disabled(), (lit(), dim(), shrunk()))
    fake.body["counts"] = {"needs": 1, "otherStuck": 2, "moving": 3}
    poll_now(page)

    # A repaint that changes nothing leaves the header alone, so a click that
    # is pressed before a poll lands is still a click when it is released.
    page.evaluate("window.__head = document.querySelector('button.hc.otherStuck')")
    poll_now(page)
    check("a poll that changes nothing does not rebuild the header's buttons",
          page.evaluate("window.__head === document.querySelector('button.hc.otherStuck')"))

    # The filter box narrows the page; the counts stay the roster's.
    page.locator("#q").fill("mei")
    page.wait_for_timeout(500)
    check("filtering does not change the counts",
          head_counts(page) == ["1 needs you", "2 other stuck", "3 moving"], head_line(page))
    page.locator("#q").press("Escape")
    page.wait_for_timeout(500)

    # Banners: the roster's, and nobody else's.
    box = page.locator("#banners")
    check("no banner, no band", box.evaluate("e => e.offsetHeight") == 0 and page.locator(".banner").count() == 0)
    fake.body["banners"] = [{"kind": "disk", "text": "Disk full: 212 MB left where sessions write"}]
    poll_now(page)
    check("a full disk is one banner that says how much is left",
          page.locator(".banner").count() == 1 and page.locator(".banner").inner_text()
          == "Disk full: 212 MB left where sessions write", page.locator("#banners").inner_text())
    spans = page.evaluate("""() => { const b = document.querySelector('.banner').getBoundingClientRect(),
      h = document.querySelector('header').getBoundingClientRect();
      return { across: b.width >= innerWidth - 1, inside: b.top >= h.top && b.bottom <= h.bottom + 1,
               sticky: getComputedStyle(document.querySelector('header')).position }; }""")
    check("it runs across the page, in the header that stays in view", spans["across"] and spans["inside"]
          and spans["sticky"] == "sticky", spans)
    check("it is on no tile: the tiles and their counts are as they were",
          not any("Disk full" in t for t in page.locator(".tile").all_inner_texts()) and page.locator(".tile").count() == 8
          and head_counts(page) == ["1 needs you", "2 other stuck", "3 moving"])
    fake.body["banners"] = []
    poll_now(page)
    check("when the roster has no banner any more, the band goes", page.locator(".banner").count() == 0
          and box.evaluate("e => e.offsetHeight") == 0)

    # From the roster's banners only: words that merely say so are not a banner.
    fake.body = roster([("alpha", "alpha", [
        S("x1", "Disk full", "idle", line="No space left on device"),
        S("x2", "Ilse", "idle", stuck=error_kind("API error", "Disk full: 0 MB left where sessions write", 1.0, ""))])])
    poll_now(page)
    check("a session or an error that talks about a full disk is not a banner",
          page.locator(".banner").count() == 0 and box.evaluate("e => e.offsetHeight") == 0)

    # R7: a banner's words are text, whatever they are.
    fake.body["banners"] = [{"kind": "disk", "text": BOMB},
                            {"kind": "constructor", "text": "Another condition"},
                            {"kind": "disk"}, {"kind": "disk", "text": ""}, None]
    seen = len(errors)
    poll_now(page)
    check("R7: markup in a banner is shown as text and builds no element",
          page.locator(".banner").first.inner_text() == BOMB and page.locator("#banners img").count() == 0
          and page.locator("#banners [onerror]").count() == 0 and len(errors) == seen, errors[seen:])
    check("whatever its kind is called, a banner is a banner and gets no class from it",
          page.locator(".banner").count() == 2 and page.locator(".banner").nth(1).get_attribute("class") == "banner"
          and page.locator(".banner").nth(1).inner_text() == "Another condition")
    check("a banner with no words is not one", page.locator(".banner").count() == 2)
    check("header: nothing stray reached the routes", not fake.stray, fake.stray)
    page.close()

    # The block view keeps its own header, and shows the same banner.
    fake = Fake(header_fixture() | {"banners": [{"kind": "disk", "text": "Disk full: 212 MB left where sessions write"}]})
    page = new_page(browser, fake)
    open_at(page, "/?view=blocks")
    page.wait_for_selector(".block")
    check("the block view's header is as it was: busy and the chime's alarms, no counts",
          "busy" in head_line(page) and page.locator("button.hc").count() == 0
          and "need you" not in head_line(page), head_line(page))
    check("the block view shows the banner too",
          page.locator(".banner").inner_text() == "Disk full: 212 MB left where sessions write")
    page.close()


def card_pass(browser):
    """The project card: the name with its raw form on hover, a track's status and
    progress, the context line (cut, whole on hover, edited in place), and the
    notes link, which searches on a click and not before."""
    def column(body, project, **over):
        next(c for c in body["columns"] if c["project"] == project).update(over)

    def ctx(source, line, full=None, guess=False):
        return {"source": source, "line": line, "full": full or line, "guess": guess}

    body = roster([("checkout", "Checkout rework", [S("c1", "Ilse", "idle", line="Saved cards")]),
                   ("shipped", "Shipped", [S("s1", "Femi", "idle")]),
                   ("repo:example.com/alice/loom", "Loom", [S("l1", "Odile", "idle")]),
                   ("folder:orchard", "Orchard", [S("o2", "Mateo", "idle")]),
                   (BOMB, BOMB, [S("b1", "Quill", "idle")]),
                   ("", "No project", [S("n1", "Rosalie", "idle")])])
    column(body, "checkout", kind="track", raw="checkout",
           track={"status": "OPEN", "progress": {"done": 3, "total": 7, "text": "3 of 7", "met": False}},
           context=ctx("goal", "Customers pay with a saved card.",
                       "Customers pay with a saved card. Nothing else changes."),
           notes={"query": "Checkout rework Customers pay with a saved card."})
    column(body, "shipped", kind="track", raw="shipped",
           track={"status": "MET", "progress": {"done": 4, "total": 4, "text": "done", "met": True}},
           context=ctx("goal", "A public docs site."), notes={"query": "Shipped A public docs site."})
    column(body, "repo:example.com/alice/loom", kind="repository", raw="loom", name="Loom",
           context=ctx("readme", "Prints reports for the shop."), track=None,
           notes={"query": "Loom Prints reports for the shop."})
    column(body, "folder:orchard", kind="folder", raw="orchard", name="Orchard",
           context=ctx("guess", "Card form \u00b7 Receipt export", guess=True), track=None,
           notes={"query": "Orchard Card form \u00b7 Receipt export"})
    # Texts that land in attributes (the hover, the raw name, the query) get a quote that would
    # end the attribute and start one of its own.
    BREAK = '" onfocus="alert(1)" autofocus="'
    column(body, BOMB, kind="track", raw=BOMB + BREAK, track={"status": BOMB, "progress": {
               "done": 1, "total": 2, "text": "1 of 2 " + BOMB, "met": False}},
           context=ctx("goal", "line: " + BOMB, "full: " + BOMB + BREAK), notes={"query": "q " + BOMB + BREAK})
    column(body, "", context=None, track=None, notes=None)
    fake = Fake(body)
    fake.answer["/api/notes"] = {"ok": True, "hits": [
        {"title": "Note one", "path": "Clients/one.md", "snippet": "Invented words one."},
        {"title": BOMB, "path": "Clients/two.md", "snippet": "Words " + BOMB}]}
    seen = len(errors)
    page = new_page(browser, fake)
    open_at(page)
    page.wait_for_selector(".ov-col")
    col = lambda project: page.locator(f'.ov-col[data-project="{project}"]')

    after = lambda loc: loc.evaluate("e => { const s = getComputedStyle(e, '::after'); return [s.content, s.color] }")
    name = col("checkout").locator(".ov-name")
    check("the name is printed readable, and the raw slug shows only on hover, in grey",
          name.inner_text() == "Checkout rework" and after(name)[0] == "none")
    name.hover()
    check("hovering the name adds the raw slug after it, in grey",
          after(name) == ['"checkout"', "rgb(138, 146, 158)"], after(name))
    page.mouse.move(5, 700)
    check("the raw slug is offered when the name is not it, and No project has none",
          col("repo:example.com/alice/loom").locator(".ov-name").get_attribute("data-raw") == "loom"
          and col("").locator(".ov-name").get_attribute("data-raw") is None)
    check("a track shows its status word, a repository none",
          col("checkout").locator(".ov-tag").inner_text() == "OPEN"
          and col("shipped").locator(".ov-tag.met").inner_text() == "MET"
          and col("repo:example.com/alice/loom").locator(".ov-tag").count() == 0)
    check("progress is N of M with a bar, and no percentage",
          col("checkout").locator(".ov-prog").inner_text().startswith("3 of 7")
          and "%" not in col("checkout").locator(".ov-prog").inner_text()
          and col("checkout").locator(".ov-bar i").evaluate("e => Math.round(e.offsetWidth / e.parentElement.offsetWidth * 100)") == 43)
    check("a met track says done and its bar is full",
          col("shipped").locator(".ov-prog").inner_text().startswith("done")
          and col("shipped").locator(".ov-bar i").evaluate("e => e.offsetWidth === e.parentElement.offsetWidth"))
    check("a repository has no progress bar", col("repo:example.com/alice/loom").locator(".ov-bar").count() == 0)
    check("the context line sits under the name, whole on hover",
          col("checkout").locator(".ov-ctx").inner_text() == "Customers pay with a saved card."
          and col("checkout").locator(".ov-ctx").get_attribute("title")
          == "Customers pay with a saved card. Nothing else changes.")
    check("the card is the name, its state, the line, the progress, then the strip",
          col("checkout").locator(".ov-head > *").evaluate_all("els => els.map(e => e.className.split(' ')[0])")
          == ["ov-top", "ov-state", "ov-ctx", "ov-prog", "ov-mv"])
    check("a guess is greyed and offers to add a line; a source does not",
          "add a line" in col("folder:orchard").locator(".ov-ctx.maybe").inner_text()
          and col("checkout").locator(".ov-ctx.maybe").count() == 0
          and "add a line" not in col("checkout").locator(".ov-ctx").inner_text())
    check("the No project card has no context line and no notes link",
          col("").locator(".ov-ctx").count() == 0 and col("").locator(".ov-notes").count() == 0)
    check("markup in a name, a status, a line and a count is text, and builds nothing",
          BOMB in col(BOMB).locator(".ov-name").inner_text() and BOMB in col(BOMB).locator(".ov-tag").inner_text()
          and BOMB in col(BOMB).locator(".ov-ctx").inner_text() and BOMB in col(BOMB).locator(".ov-prog").inner_text()
          and page.locator("#main img, #main [onerror]").count() == 0)
    check("a quote in a hover, a raw name or a query cannot start an attribute of its own",
          page.locator("#main [onfocus], #main [autofocus]").count() == 0
          and col(BOMB).locator(".ov-name").get_attribute("data-raw") == BOMB + BREAK
          and col(BOMB).locator(".ov-ctx").get_attribute("title") == "full: " + BOMB + BREAK
          and col(BOMB).locator(".ov-notes").get_attribute("data-query") == "q " + BOMB + BREAK)

    # The line, edited where it stands.
    check("no search has been made before any click", fake.of("/api/notes") == [])
    col("repo:example.com/alice/loom").locator(".ov-ctx").click()
    page.wait_for_selector("input.inline")
    check("editing a line of the README starts from nothing, not from the README",
          page.locator("input.inline").input_value() == "")
    page.locator("input.inline").fill("The shop's report printer")
    page.locator("input.inline").press("Enter")
    page.wait_for_timeout(300)
    check("saving posts the project identity and the text",
          fake.of("/api/context") == [{"project": "repo:example.com/alice/loom", "text": "The shop's report printer"}],
          fake.posts)
    fake.body = copy.deepcopy(body)
    column(fake.body, "repo:example.com/alice/loom", context=ctx("own", "The shop's report printer"))
    poll_now(page)
    col("repo:example.com/alice/loom").locator(".ov-ctx").click()
    page.wait_for_selector("input.inline")
    check("editing your own line starts from it", page.locator("input.inline").input_value() == "The shop's report printer")
    page.locator("input.inline").press("Escape")
    page.wait_for_timeout(200)
    check("Escape changes nothing", len(fake.of("/api/context")) == 1)

    # The notes link: nothing until the click, then one search, and it stays through polls.
    link = col("checkout").locator(".ov-notes")
    link.click()
    page.wait_for_selector('.ov-col[data-project="checkout"] .ov-hits .hit-title')
    check("a click searches once, with the name and the line",
          fake.of("/api/notes") == [{"query": "Checkout rework Customers pay with a saved card."}], fake.posts)
    check("the top hits are printed as text under the card",
          col("checkout").locator(".hit-title").all_inner_texts() == ["Note one", BOMB]
          and "Invented words one." in col("checkout").locator(".ov-hits").inner_text()
          and page.locator("#main img, #main [onerror]").count() == 0)
    poll_now(page)
    check("a poll keeps the hits and searches nothing more",
          col("checkout").locator(".ov-hits .hit-title").count() == 2 and len(fake.of("/api/notes")) == 1)
    col("checkout").locator(".ov-notes").click()
    page.wait_for_timeout(200)
    check("a second click puts them away", col("checkout").locator(".ov-hits").count() == 0
          and len(fake.of("/api/notes")) == 1)
    fake.answer["/api/notes"] = {"ok": False, "reason": "notes search is not set up here"}
    col("shipped").locator(".ov-notes").click()
    page.wait_for_selector('.ov-col[data-project="shipped"] .ov-hits')
    page.wait_for_function("() => document.querySelector('.ov-col[data-project=\"shipped\"] .ov-hits').innerText.includes('not set up')")
    check("when there is no search the card says so", "notes search is not set up here"
          in col("shipped").locator(".ov-hits").inner_text())
    # An answer that comes in while you are typing a line must not take the field away,
    # and an answer that is not the shape the server promises must not break the page.
    fake.answer["/api/notes"] = {"ok": True}
    col("repo:example.com/alice/loom").locator(".ov-ctx").click()
    page.wait_for_selector("input.inline")
    page.locator("input.inline").fill("half a sentence")
    page.evaluate("document.querySelector('.ov-col[data-project=\"folder:orchard\"] .ov-notes').click()")
    page.wait_for_timeout(500)
    check("a notes answer that arrives mid-edit leaves the field and what you typed alone",
          page.locator("input.inline").count() == 1 and page.locator("input.inline").input_value() == "half a sentence")
    page.locator("input.inline").press("Escape")
    page.wait_for_selector('.ov-col[data-project="folder:orchard"] .ov-hits')
    check("and it shows once you are done, an answer without hits as nothing found",
          col("folder:orchard").locator(".ov-hits").inner_text() == "nothing found")
    check("card: no dialog, no page error", len(errors) == seen, errors[seen:])
    check("card: nothing stray reached the routes", not fake.stray, fake.stray)
    page.close()


def needs_pass(browser):
    """Ticket 07: Needs you on the tile and the state on the card, and the copy
    button on a command and nowhere else. Fixtures are invented; so is every
    question and command in them."""
    cmd = "git push origin feature/maple-notes"
    maple = ("maple", "maple", [
        S("q1", "Vera", "waiting", "waiting", note="input needed", line="Port the importer",
          stuck=asks("Publish the notes page under /docs?",
                     [("Yes, under /docs", "Linked from the sidebar"), ("No, keep it private", "")])),
        S("q2", "Mei", "waiting", "waiting", note="permission prompt", line="Ship the notes",
          stuck=prompts("Bash", cmd)),
        S("q3", "Nour", "waiting", "waiting", note="permission prompt", line="Edit the notes",
          stuck=prompts("Edit", target="/home/alice/Projects/maple/notes.md")),
        S("q4", "Aziz", "idle", "ready", line="Notes drafted",
          stuck=needs("line", "3 things left for you", {"text": ""})),
        S("q5", "Dmitri", "idle", line="Tests green", need="Which branch should it go on?"),
        S("q6", "Elin", "busy", line="Writing the changelog"),
        S("q7", "Ines", "waiting", "waiting", note="input needed", line="Ask about the schema",
          stuck=needs("question", "Question", {"questions": []}))])
    orchard = ("orchard", "orchard", [S("o1", "Frode", "busy", line="Pruning the schema", mv="writing · 8s ago")])
    pmd = ("pmd", "pmd", [S("p1", "Lennart", "idle", line="Plan the cutover")])
    body = roster([maple, orchard, pmd])
    # Minutes the server did not see, in a card of each colour that tints the strip.
    next(c for c in body["columns"] if c["project"] == "pmd")["strip"] = [None] * 4 + [0] * 25 + [1]
    fake = Fake(body)
    page = new_page(browser, fake)
    open_at(page)
    page.wait_for_selector(".ov-col")
    t = lambda sid: page.locator(f'.tile[data-sid="{sid}"]')
    head = lambda project: page.locator(f'.ov-col[data-project="{project}"] .ov-head')
    probe = lambda v: page.evaluate("""v => { const d = document.createElement('div'); d.style.color = `var(${v})`;
      document.body.appendChild(d); const c = getComputedStyle(d).color; d.remove(); return c }""", v)

    # The three sources, each with its reason and its context.
    check("an open question: the reason, the question and every option",
          t("q1").locator(".stuck-box .reason").inner_text() == "Question"
          and "Publish the notes page under /docs?" in t("q1").locator(".qtext").inner_text()
          and t("q1").locator("li .ol").all_inner_texts() == ["Yes, under /docs", "No, keep it private"]
          and t("q1").locator("li .od").all_inner_texts() == [" — Linked from the sidebar"])
    check("an open permission prompt: the reason, the tool and the whole command",
          t("q2").locator(".stuck-box .reason").inner_text() == "Permission prompt"
          and t("q2").locator(".tool").inner_text().lower() == "bash"
          and t("q2").locator("code").inner_text() == cmd)
    check("a prompt for a tool with no command shows what it would touch",
          t("q3").locator(".tool").inner_text().lower() == "edit"
          and t("q3").locator("code").inner_text() == "/home/alice/Projects/maple/notes.md")
    check("several things left: the count, in the reason",
          t("q4").locator(".stuck-box .reason").inner_text() == "3 things left for you"
          and t("q4").locator(".say").count() == 0)
    check("one thing left: the count and the ask",
          t("q5").locator(".stuck-box .reason").inner_text() == "1 thing left for you"
          and t("q5").locator(".say").inner_text() == "Which branch should it go on?")
    check("an open question not written down yet: the reason, no options, and a plain note",
          t("q7").locator(".stuck-box .reason").inner_text() == "Question"
          and t("q7").locator(".stuck-box li").count() == 0
          and t("q7").locator(".stuck-box .late").inner_text() == "Its question is not in the transcript yet."
          and "needs" in t("q7").get_attribute("class"))
    check("a session that needs nothing has no box",
          t("q6").locator(".stuck-box").count() == 0 and "needs" not in t("q6").get_attribute("class"))
    check("a tile that needs you is marked, in amber, and says it once",
          all("needs" in t(k).get_attribute("class") for k in ("q1", "q2", "q3", "q4", "q5", "q7"))
          and t("q1").locator(".flag.needs").inner_text().lower() == "needs you"
          and t("q1").locator(".flag.waiting").count() == 0
          and t("q1").evaluate("e => getComputedStyle(e).borderTopColor") == probe("--wait"))

    # The copy button: on a command, never elsewhere.
    check("copy is on the command and on nothing else",
          page.locator("button.copy").count() == 1 and t("q2").locator("button.copy").count() == 1)

    # The card: the state is its second line, never above the name, in its colour.
    box = lambda loc: loc.bounding_box()
    for project, word in (("maple", "NEEDS YOU"), ("orchard", "MOVING"), ("pmd", "ALL IDLE")):
        h = head(project)
        name, state = box(h.locator(".ov-name")), box(h.locator(".ov-state"))
        check(f"{project}: the state word reads {word}", h.locator(".ov-state").inner_text() == word,
              h.locator(".ov-state").inner_text())
        check(f"{project}: the state word sits under the name, never above or beside it",
              state["y"] >= name["y"] + name["height"] - 1 and state["y"] > name["y"], (name, state))
    # The card is always coloured by its state: the top edge, a light tint, the
    # word and the strip's bars -- grey for a card with nothing moving too.
    plain = page.evaluate("""() => { const d = document.createElement('div'); d.style.background = 'var(--card)';
      document.body.appendChild(d); const c = getComputedStyle(d).backgroundColor; d.remove(); return c }""")
    for project, var in (("maple", "--wait"), ("orchard", "--busy"), ("pmd", "--idle")):
        h = head(project)
        paint = lambda loc, prop: loc.evaluate(f"e => getComputedStyle(e).{prop}")
        check(f"{project}: the card's top edge, word and bars take the state's colour",
              paint(h, "borderTopColor") == probe(var) and paint(h.locator(".ov-state"), "color") == probe(var)
              and paint(h.locator(".strip i:not(.u):not(.z)").first, "backgroundColor") == probe(var),
              (paint(h, "borderTopColor"), paint(h.locator(".ov-state"), "color"), probe(var)))
        check(f"{project}: the card has a light tint of its own", paint(h, "backgroundColor") != plain,
              paint(h, "backgroundColor"))

    # A minute the server did not see is a dotted stub in every card, whatever
    # its state tints the bars with: never a bar, and never a filled one.
    for project in ("maple", "pmd"):
        stubs = head(project).locator(".strip i.u")
        check(f"{project}: a minute not seen stays a dotted stub, with no fill of the state's colour",
              stubs.count() > 0 and all(stubs.nth(i).evaluate("e => getComputedStyle(e).backgroundColor")
                                        == "rgba(0, 0, 0, 0)" for i in range(stubs.count())),
              [stubs.nth(i).evaluate("e => getComputedStyle(e).backgroundColor") for i in range(stubs.count())])

    # The reason is part of what the tile knows. A click that jumps clears the
    # jump's own note and nothing else, whether the jump works or fails.
    kept = lambda k, word: t(k).locator(".stuck-box .reason").all_inner_texts() == [word]
    t("q1").locator(".nm").click()
    page.wait_for_timeout(150)
    check("a click on a Needs-you tile that jumps keeps its reason", kept("q1", "Question"))
    fake.answer["/api/jump"] = {"ok": False, "reason": "no pane for it"}
    t("q2").locator(".nm").click()
    page.wait_for_timeout(150)
    check("a jump that fails says why on the tile and keeps the reason",
          kept("q2", "Permission prompt") and t("q2").locator(".why").all_inner_texts() == ["no pane for it"],
          t("q2").locator(".why").all_inner_texts())
    del fake.answer["/api/jump"]

    # Copy does not answer the session and does not jump.
    posts = len(fake.posts)
    t("q2").locator("button.copy").click()
    page.wait_for_timeout(200)
    check("clicking copy sends nothing to the server: no jump, no seen mark, no answer",
          len(fake.posts) == posts, fake.posts[posts:])
    check("and the tile does not flash as jumped", "jumped" not in t("q2").get_attribute("class"))
    check("the button says copied", t("q2").locator("button.copy").inner_text() == "copied")
    page.close()

    # Copy puts the command on the clipboard, character for character.
    page = new_page(browser, fake, clipboard=True)
    page.goto("http://localhost/", wait_until="load")
    page.wait_for_selector(".tile")
    page.locator('.tile[data-sid="q2"] button.copy').click()
    page.wait_for_timeout(200)
    check("the clipboard holds the command", page.evaluate("navigator.clipboard.readText()") == cmd)
    page.context.close()

    # R7 at the page: question, options, header, command, tool, target and ask are text.
    nasty = f"echo {BOMB}\nls 'a b' \"c\""
    hostile = ("maple", "maple", [
        S("h1", "Vera", "waiting", "waiting", note="input needed",
          stuck=asks(BOMB, [(BOMB, BOMB)], header=BOMB, multi=True)),
        S("h2", "Mei", "waiting", "waiting", note="permission prompt", stuck=prompts(BOMB, nasty)),
        S("h3", "Nour", "waiting", "waiting", note="permission prompt", stuck=prompts(BOMB, target=BOMB)),
        S("h4", "Aziz", "idle", need=BOMB)])
    fake2 = Fake(roster([hostile]))
    page = new_page(browser, fake2, clipboard=True)
    seen = len(errors)
    page.goto("http://localhost/", wait_until="load")
    page.wait_for_selector(".tile")
    page.wait_for_timeout(300)
    text = page.locator("#main").inner_text()
    # The header and the tool are set in capitals by the page's CSS, and
    # `inner_text` returns them so: compare without case.
    check("R7: markup in a question, header, option, command, tool, target and ask is shown as text",
          text.lower().count(BOMB.lower()) == 9, text.lower().count(BOMB.lower()))
    check("R7: and builds no element from it",
          page.locator("img").count() == 0 and page.locator("#main [onerror]").count() == 0
          and page.evaluate("() => document.querySelectorAll('#main *').length < 200"))
    page.locator('.tile[data-sid="h2"] button.copy').click()
    page.wait_for_timeout(200)
    check("R7: copy copies the literal command, markup, line break and quotes included",
          page.evaluate("navigator.clipboard.readText()") == nasty, page.evaluate("navigator.clipboard.readText()"))
    check("R7: no dialog, no page error", len(errors) == seen, errors[seen:])
    page.context.close()

    # Where the page has no clipboard API (plain http on a name that is not
    # localhost), copy still works through the selection fallback.
    page = new_page(browser, fake)
    open_at(page)
    page.wait_for_selector(".tile")
    page.evaluate("""() => { window.__copied = null;
      document.addEventListener('copy', () => { window.__copied = document.getSelection().toString(); }); }""")
    check("the fallback case really has no clipboard API", page.evaluate("typeof navigator.clipboard") == "undefined")
    t("q2").locator("button.copy").click()
    page.wait_for_timeout(200)
    check("without a clipboard API, copy falls back to the selection and copies the command",
          page.evaluate("window.__copied") == cmd, page.evaluate("window.__copied"))
    page.close()


def clock_said(line):
    """The time of day a line says, as (hour, minute, on another day), whatever
    the browser's locale writes it as: `14:20`, `2:20 PM`, `Tue 14.20`."""
    got = re.search(r"(?:(?P<day>[^\W\d_]{2,})\.?\s+)?(?P<h>\d{1,2})[:.](?P<m>\d{2})\s*(?P<ap>[AaPp])?\.?[Mm]?", line)
    if not got:
        return None
    hour = int(got["h"]) % 12 + (12 if (got["ap"] or "").lower() == "p" else 0) if got["ap"] else int(got["h"])
    return hour, int(got["m"]), bool(got["day"])


def when(line):
    """The time part of 'resets 14:20 · held 22 min': what stands between the verb and the dot."""
    return line.split(" · ")[0].split(" ", 1)[1]


def clock_is(ms):
    """The same, from Python's own clock: what the page should have written."""
    moment = datetime.datetime.fromtimestamp(ms / 1000)
    return moment.hour, moment.minute, moment.date() != datetime.date.today()


def kinds_pass(browser):
    """Ticket 08: Error, Hung and Limit on the tile and on the card, in the
    card's full order. Fixtures are invented; so is every error and tool in them."""
    now_ms = int(time.time() * 1000)       # the page compares resets with its own clock
    soon, passed = now_ms + 98 * 60000, now_ms - 40 * 60000
    mix_p = ("mixed", "mixed", [
        S("a1", "Vera", "waiting", "waiting", note="input needed", stuck=asks("Publish?", [("Yes", ""), ("No", "")])),
        S("a2", "Mei", "idle", stuck=error_kind("Overloaded", "Invented: the service is busy", 3.0, "server_error")),
        S("a3", "Nour", "busy", "stuck", note="14m", stuck=hung_kind(14, "Run the unit tests", 14.0)),
        S("a4", "Aziz", "idle", stuck=limit_kind(soon, 22.0, "Invented: limit reached")),
        S("a5", "Dmitri", "busy", mv="writing · 8s ago"),
        S("a6", "Elin", "idle")])
    errors_p = ("errs", "errs", [
        S("e1", "Odile", "idle", stuck=error_kind("Auth error", "Invented: not signed in", 1.0, "authentication_failed")),
        S("e2", "Femi", "idle", stuck=error_kind("API error", "", None, "")),
        S("e3", "Gus", "busy", mv="writing · 8s ago")])
    hung_p = ("hangs", "hangs", [
        S("h1", "Ilse", "busy", "stuck", note="14m", stuck=hung_kind(14, "Run the unit tests", 14.0)),
        S("h2", "Joaquin", "busy", "stuck", note="190m", stuck=hung_kind(190)),
        S("h3", "Kasper", "idle", stuck=limit_kind(None, 5.0)),
        S("h4", "Lena", "busy", mv="writing · 8s ago")])
    limit_p = ("limits", "limits", [
        S("l1", "Maud", "idle", stuck=limit_kind(soon, 22.0, "Invented: limit reached")),
        S("l2", "Noor", "idle", stuck=limit_kind(passed, 301.0, "Invented: limit reached")),
        S("l3", "Odin", "idle", stuck=limit_kind(None, 5.0, "")),
        S("l4", "Pia", "idle", stuck=limit_kind(None, None, "Invented: limit reached")),
        S("l5", "Quin", "busy", mv="writing · 8s ago")])
    quiet_p = ("quiet", "quiet", [S("z1", "Rune", "idle"), S("z2", "Sol", "busy", mv="writing · 8s ago")])
    ask_p = ("asks", "asks", [
        S("q1", "Rhea", "waiting", "waiting", note="sandbox request", stuck=request_kind("sandbox request")),
        S("q2", "Soren", "waiting", "waiting", note="goal proposal", stuck=request_kind("goal proposal")),
        S("q3", "Tove", "waiting", "waiting", note="dialog open")])
    fake = Fake(roster([mix_p, errors_p, hung_p, limit_p, quiet_p, ask_p]))
    page = new_page(browser, fake)
    open_at(page)
    page.wait_for_selector(".ov-col")
    t = lambda sid: page.locator(f'.tile[data-sid="{sid}"]')
    head = lambda project: page.locator(f'.ov-col[data-project="{project}"] .ov-head')
    probe = lambda v: page.evaluate("""v => { const d = document.createElement('div'); d.style.color = `var(${v})`;
      document.body.appendChild(d); const c = getComputedStyle(d).color; d.remove(); return c }""", v)
    paint = lambda loc, prop: loc.evaluate(f"e => getComputedStyle(e).{prop}")
    reason = lambda k: t(k).locator(".stuck-box .reason").inner_text()
    late = lambda k: t(k).locator(".stuck-box .late").all_inner_texts()

    # The tile: tag, reason, context.
    check("Limit: the tag, the reason, and when it resets and how long it has been held",
          t("a4").locator(".flag.limit").inner_text().lower() == "limit"
          and reason("a4") == "Rate limit" and len(late("a4")) == 1
          and late("a4")[0].startswith("resets ") and late("a4")[0].endswith(" · held 22 min")
          and clock_said(when(late("a4")[0])) == clock_is(soon),
          (reason("a4"), late("a4"), clock_is(soon)))
    check("Limit: a reset time already past says reset, not resets",
          len(late("l2")) == 1 and late("l2")[0].startswith("reset ") and not late("l2")[0].startswith("resets ")
          and late("l2")[0].endswith(" · held 5 h") and clock_said(when(late("l2")[0])) == clock_is(passed),
          (late("l2"), clock_is(passed)))
    check("Limit: with no reset time it says only how long, and with nothing, its own words",
          late("l3") == ["held 5 min"] and t("l4").locator(".stuck-box .say").inner_text() == "Invented: limit reached"
          and late("l4") == [], (late("l3"), late("l4")))
    check("Error: the tag, the type as the reason, the error's words and when",
          t("a2").locator(".flag.error").inner_text().lower() == "error" and reason("a2") == "Overloaded"
          and t("a2").locator(".stuck-box .say").inner_text() == "Invented: the service is busy"
          and late("a2") == ["3 min ago"], (reason("a2"), late("a2")))
    check("Error: a login failure, and one that names nothing and has no words",
          reason("e1") == "Auth error" and late("e1") == ["1 min ago"]
          and reason("e2") == "API error" and t("e2").locator(".stuck-box .say").count() == 0
          and late("e2") == [], (reason("e1"), reason("e2")))
    check("Hung: the tag, how long, and the last tool with its age",
          t("h1").locator(".flag.hung").inner_text().lower() == "hung" and reason("h1") == "Not moving for 14 min"
          and late("h1") == ["last tool: Run the unit tests · 14 min ago"], (reason("h1"), late("h1")))
    check("Hung: with no tool to name it says so, and long silences are in hours",
          late("h2") == ["no tool called yet"] and reason("h2") == "Not moving for 190 min", late("h2"))
    check("a tile with a kind has no flag of the old pages beside it",
          all(t(k).locator(".flag").count() == 1 for k in ("a2", "a3", "a4", "h1", "l1", "e1"))
          and t("a3").locator(".flag.stuck").count() == 0)
    check("a session with no kind has no box", t("a5").locator(".stuck-box").count() == 0
          and t("a6").locator(".stuck-box").count() == 0)
    check("Needs you by a request: the tag, and its name as the reason, with nothing under it",
          t("q1").locator(".flag.needs").inner_text().lower() == "needs you"
          and reason("q1") == "Sandbox request" and reason("q2") == "Goal proposal"
          and t("q1").locator(".stuck-box .say, .stuck-box .late, .stuck-box .cmd").count() == 0,
          (reason("q1"), reason("q2")))
    check("and a menu the person opened (dialog open) is waiting, not Needs you",
          t("q3").locator(".stuck-box").count() == 0 and t("q3").locator(".flag.needs").count() == 0)

    # Colour: the border and the dot, per kind.
    check("Error and Hung are red, Limit is purple, on the border",
          paint(t("a2"), "borderTopColor") == probe("--bad") == paint(t("a3"), "borderTopColor")
          and paint(t("a4"), "borderTopColor") == probe("--limit") != probe("--bad"),
          (paint(t("a2"), "borderTopColor"), paint(t("a4"), "borderTopColor"), probe("--limit")))
    check("and the dot takes the kind's colour, not the green of a busy session or a tick",
          paint(t("a3").locator(".dot"), "backgroundColor") == probe("--bad")
          and paint(t("a2").locator(".dot"), "backgroundColor") == probe("--bad")
          and paint(t("a4").locator(".dot"), "backgroundColor") == probe("--limit")
          and t("a2").locator(".tick").count() == 0)
    check("the tag takes the colour too",
          paint(t("a2").locator(".flag"), "color") == probe("--bad")
          and paint(t("a4").locator(".flag"), "color") == probe("--limit")
          and paint(t("a4").locator(".stuck-box .reason"), "color") == probe("--limit")
          and paint(t("a3").locator(".stuck-box .reason"), "color") == probe("--bad"))

    # The card: the full order, the word, the colours, and the mix by kind.
    for project, word, var, mixline in (
            ("mixed", "NEEDS YOU", "--wait", "1 moving · 4 stuck · 1 idle"),
            ("errs", "ERROR", "--bad", "1 moving · 2 stuck · 0 idle"),
            ("hangs", "HUNG", "--bad", "1 moving · 3 stuck · 0 idle"),
            ("limits", "LIMIT", "--limit", "1 moving · 4 stuck · 0 idle"),
            ("quiet", "MOVING", "--busy", "1 moving · 0 stuck · 1 idle"),
            ("asks", "NEEDS YOU", "--wait", "0 moving · 2 stuck · 1 idle")):
        h = head(project)
        check(f"{project}: the card reads {word}", h.locator(".ov-state").inner_text() == word,
              h.locator(".ov-state").inner_text())
        check(f"{project}: its top edge, word and bars are {var}",
              paint(h, "borderTopColor") == probe(var) and paint(h.locator(".ov-state"), "color") == probe(var)
              and paint(h.locator(".strip i:not(.u):not(.z)").first, "backgroundColor") == probe(var),
              (paint(h, "borderTopColor"), probe(var)))
        check(f"{project}: the mix counts stuck by kind", h.locator(".mix").inner_text() == mixline,
              h.locator(".mix").inner_text())
    check("a card of Error, Hung and Limit is red before it is purple; Limit alone is purple",
          paint(head("hangs"), "borderTopColor") == probe("--bad") != paint(head("limits"), "borderTopColor"))

    # A click on a tile with a kind still jumps and keeps its reason.
    t("h1").locator(".nm").click()
    page.wait_for_timeout(150)
    check("a click on a Hung tile jumps and keeps its reason", reason("h1") == "Not moving for 14 min"
          and any(p == "/api/jump" for p, _ in fake.posts))
    page.close()

    # R7: what Claude Code and a session wrote is text, in every place a kind prints it.
    hostile = ("hostile", "hostile", [
        S("x1", "Vera", "idle", stuck=error_kind(BOMB, BOMB, 3.0, BOMB)),
        S("x2", "Mei", "busy", "stuck", note="14m", stuck=hung_kind(14, BOMB, 14.0)),
        S("x3", "Nour", "idle", stuck=limit_kind(None, None, BOMB))])
    page = new_page(browser, Fake(roster([hostile])))
    seen = len(errors)
    open_at(page)
    page.wait_for_selector(".tile")
    page.wait_for_timeout(300)
    text = page.locator("#main").inner_text().lower()
    check("R7: markup in an error's reason and words, a last tool, and a limit's words is shown as text",
          text.count(BOMB.lower()) == 4, text.count(BOMB.lower()))
    check("R7: and builds no element from it",
          page.locator("img").count() == 0 and page.locator("#main [onerror]").count() == 0)
    check("R7: no dialog, no page error", len(errors) == seen, errors[seen:])
    page.close()

    # A kind the page does not know is shown without a class of its own.
    odd = ("odd", "odd", [S("w1", "Wim", "idle", stuck={"kind": "x\"><b>", "source": "api", "reason": "Odd",
                                                             "context": {}})])
    page = new_page(browser, Fake(roster([odd])))
    open_at(page)
    page.wait_for_selector(".tile")
    check("an unknown kind builds no markup and adds no class from the server's text",
          page.locator("#main b").count() == 0 and "<" not in (t("w1").get_attribute("class") or ""),
          t("w1").get_attribute("class"))
    page.close()

    # A word every object has (`constructor`, `toString`) is not a kind or a state the page knows.
    inherited = roster([("inherit", "inherit", [
        S("i1", "Ivo", "idle", stuck={"kind": "constructor", "source": "api", "reason": "Inherited", "context": {}}),
        S("i2", "Jana", "idle", stuck={"kind": "toString", "source": "api", "reason": "Inherited too", "context": {}})])])
    inherited["columns"][0]["state"] = "toString"
    page = new_page(browser, Fake(inherited))
    open_at(page)
    page.wait_for_selector(".tile")
    text = page.locator("#main").inner_text()
    check("an inherited object key is no kind: no code printed, no class, no tag",
          "native code" not in text and "function" not in text
          and all("constructor" not in (t(k).get_attribute("class") or "") and "toString" not in (t(k).get_attribute("class") or "")
                  for k in ("i1", "i2"))
          and t("i1").locator(".flag.constructor, .flag.toString").count() == 0,
          (text, t("i1").get_attribute("class")))
    check("and the card says the word it was given, as a state of no colour",
          page.locator(".ov-state").inner_text() == "TOSTRING" and "st-other" in page.locator(".ov-head").get_attribute("class"),
          page.locator(".ov-head").get_attribute("class"))
    page.close()


def suggestion_pass(browser):
    """A session in No project carries a suggestion; one click assigns it."""
    body = roster([PMD, LOOSE])
    next(c for c in body["columns"] if c["project"] == "")["sessions"][0]["suggestion"] = {
        "project": "repo:example.com/alice/pmd", "name": "pmd"}
    fake = Fake(body)
    page = new_page(browser, fake)
    open_at(page)
    page.wait_for_selector(".ov-col")
    chip = page.locator('.ov-col[data-project=""] .guess')
    check("a suggestion is one chip, in the No project column, saying where it would go",
          chip.count() == 1 and chip.inner_text().strip().endswith("pmd"), chip.count())
    check("a column with a project has no chip", page.locator('.ov-col[data-project="pmd"] .guess').count() == 0)
    chip.click()
    page.wait_for_timeout(300)
    check("a click on it assigns the session by project identity",
          fake.of("/api/assign") == [{"key": "o1", "project": "repo:example.com/alice/pmd"}], fake.posts)
    check("and the tile under it is not opened", [p for p, _ in fake.posts if p != "/api/assign"] == [], fake.posts)
    check("suggestion: nothing stray reached the routes", not fake.stray, fake.stray)
    page.close()


def jump_pass(browser):
    """The three jumps and their failures. Every POST is the route's: nothing
    is attached, raised or opened, and a request the routes do not know fails."""
    fake = Fake(roster([("harbor", "harbor", [
        S("h1", "Quill", "idle", "ready", line="Reviewed the plan"),
        S("h2", "Sorrel", "idle", "ready", line="Tide table review", via="attach", can=False),
        S("h3", "Piet", "idle", can=False),
        S("h4", "Mona", "idle", can=False, why="attached, but in no window that can be raised")])]))
    page = new_page(browser, fake)
    open_at(page)
    page.wait_for_selector(".tile")
    t = lambda sid: page.locator(f'.tile[data-sid="{sid}"]')
    go = lambda sid: t(sid).locator(".go")

    check("a pane says open ↗", go("h1").inner_text() == "open ↗")
    check("a background session says attach ↗ and is clickable",
          go("h2").inner_text() == "attach ↗" and "can" in t("h2").get_attribute("class").split())
    check("a session with no terminal says so, greyed, in place of the jump",
          go("h3").inner_text() == "no terminal" and "can" not in t("h3").get_attribute("class").split()
          and go("h3").evaluate("e => getComputedStyle(e).opacity") == "1"
          and go("h3").evaluate("e => getComputedStyle(e).color") != go("h1").evaluate("e => getComputedStyle(e).color"))
    check("and the reason is one hover away", go("h4").get_attribute("title")
          == "attached, but in no window that can be raised" and go("h3").get_attribute("title") == "no terminal")

    t("h2").click()
    page.wait_for_timeout(300)
    check("an attach tile posts /api/jump with its key and nothing else", fake.of("/api/jump") == [{"key": "h2"}], fake.posts)
    check("a jump that worked shows no reason", t("h2").locator(".why").count() == 0)

    fake.answer["/api/jump"] = {"ok": False, "reason": "wezterm cli spawn failed"}
    t("h2").click()
    t("h2").locator(".why").wait_for(timeout=3000)
    check("a failed jump leaves its reason on the tile",
          t("h2").locator(".why").inner_text() == "wezterm cli spawn failed" and "failed" in t("h2").get_attribute("class"))
    check("and the handover is still unread there", t("h2").locator(".tick").count() == 1)
    poll_now(page)
    page.wait_for_function("document.querySelectorAll('.tile .why').length === 0", timeout=3000)
    check("until the next poll", t("h2").locator(".why").count() == 0 and t("h2").locator(".tick").count() == 1)

    # A successful retry takes the old reason away.
    t("h2").click()
    t("h2").locator(".why").wait_for(timeout=3000)
    fake.answer["/api/jump"] = {"ok": True, "ran": []}
    t("h2").click()
    page.wait_for_timeout(300)
    check("a jump that works clears the reason an earlier one left", t("h2").locator(".why").count() == 0)

    # A slow jump is answered after a poll has replaced every node. The reason
    # goes to the tile that is on the page now, not the one that was clicked.
    fake.answer["/api/jump"] = {"ok": False, "reason": "wezterm cli spawn failed"}
    fake.hold = True
    page.evaluate("window.clicked = document.querySelector('.tile[data-sid=\"h2\"]')")
    t("h2").click()
    for _ in range(30):
        if fake.held:
            break
        page.wait_for_timeout(100)
    poll_now(page)
    page.wait_for_timeout(300)
    check("a poll while the jump is out replaces the tile that was clicked",
          page.evaluate("window.clicked.isConnected") is False)
    fake.held.pop().fulfill(status=200, content_type="application/json", body=json.dumps(fake.answer["/api/jump"]))
    fake.hold = False
    t("h2").locator(".why").wait_for(timeout=3000)
    check("the reason of a slow jump still lands on the tile that is shown",
          t("h2").locator(".why").inner_text() == "wezterm cli spawn failed")

    # A click that only waited for a tab already being opened says so, and is not a failure.
    poll_now(page)
    page.wait_for_timeout(300)
    fake.answer["/api/jump"] = {"ok": True, "did": "opening"}
    t("h2").click()
    t("h2").locator(".why.note").wait_for(timeout=3000)
    check("a click that waited says it is opening a tab, without a failure",
          t("h2").locator(".why.note").inner_text().startswith("opening")
          and "failed" not in t("h2").get_attribute("class"))

    n = len(fake.of("/api/jump"))
    t("h3").click()
    page.wait_for_timeout(300)
    check("a click on a no-terminal tile jumps nowhere", len(fake.of("/api/jump")) == n
          and fake.of("/api/seen") == [{"key": "h3"}], fake.posts)
    check("jump: nothing stray reached the routes", not fake.stray, fake.stray)
    page.close()


def hostile_pass(browser, view):
    """R7 at the page: markup in a project, a name and a line is text."""
    s = S("h1", BOMB, "idle", line="line: " + BOMB, mv="waiting on: " + BOMB + ", 3 min")
    fake = Fake(roster([(BOMB, BOMB, [s])]))
    seen = len(errors)
    page = new_page(browser, fake)
    open_at(page, "/?view=blocks" if view == "blocks" else "/")
    page.wait_for_selector(".block" if view == "blocks" else ".tile")
    page.wait_for_timeout(500)
    text = page.locator("#main").inner_text()
    # The overview also prints what the session is waiting on, which is the
    # words of its own tool call.
    check(f"{view}: markup in a project, a name, a line and a sign is shown as text",
          text.count(BOMB) >= (3 if view == "blocks" else 4), text[:200])
    check(f"{view}: and builds no element from it",
          page.locator("img").count() == 0 and page.locator("#main [onerror]").count() == 0)
    check(f"{view}: no dialog, no page error", len(errors) == seen, errors[seen:])
    page.close()


def chime_pass(browser, view):
    fake = Fake(roster([("alpha", "alpha", [S("c1", "ALPHA", "busy")])]))
    page = new_page(browser, fake)
    open_at(page, "/?view=blocks" if view == "blocks" else "/")
    page.wait_for_selector(".block" if view == "blocks" else ".tile")
    woke = page.evaluate("""async () => {
      const ctx = speaker();
      await ctx.suspend();
      let notes = 0;
      const make = ctx.createOscillator;
      ctx.createOscillator = function () { notes++; return make.call(this); };
      const rang = await ring();
      ctx.createOscillator = make;
      return { rang, notes, state: ctx.state, button: document.getElementById("sound").textContent };
    }""")
    check(f"{view}: a suspended speaker wakes and sounds",
          woke["rang"] is True and woke["notes"] > 0 and woke["state"] == "running" and woke["button"] == "chime", woke)
    page.evaluate("() => { window.__rings = 0; window.__ticks = 0;"
                  " window.ring = () => { window.__rings++; return true; };"
                  " window.tick = () => { window.__ticks++; return true; }; }")
    rings = lambda: page.evaluate("window.__rings")
    ticks = lambda: page.evaluate("window.__ticks")
    if view == "overview":
        # Rendered offline: a graph that connects nothing sounds exactly like one that works.
        sound = page.evaluate("""async () => {
          const peaks = async (shape, cuts) => {
            const off = new OfflineAudioContext(1, 44100 * 3, 44100);
            shape(off);
            const data = (await off.startRendering()).getChannelData(0);
            return cuts.map(([from, to]) => {
              let peak = 0;
              for (let i = from * 44100; i < Math.min(to * 44100, data.length); i++)
                peak = Math.max(peak, Math.abs(data[i]));
              return peak; });
          };
          const [first, second] = await peaks(tone, [[0, 0.4], [0.45, 3]]);
          const [head, tail] = await peaks(blip, [[0, 0.3], [0.6, 3]]);
          return { first, second, head, tail };
        }""")
        check("the two strokes are there, and not deafening",
              0.05 < sound["first"] < 0.4 and 0.05 < sound["second"] < 0.4 and sound["second"] < sound["first"], sound)
        check("the finished tick is audible and over at once",
              0.05 < sound["head"] < 0.4 and sound["tail"] < 0.005, sound)
        check("the chime is armed by default", page.locator("#sound").inner_text() == "chime")
    fake.body = waiting("c2")
    page.wait_for_timeout(4000)
    check(f"{view}: rings when someone starts waiting", rings() == 1, rings())
    page.wait_for_timeout(4000)
    check(f"{view}: and not again while it waits", rings() == 1, rings())
    if view == "overview":
        page.locator("#sound").click()
        page.wait_for_timeout(300)
        check("it can be muted, and the mute is posted",
              page.locator("#sound").inner_text() == "muted" and fake.of("/api/chime") == [{"chime": False}], fake.posts)
        fake.body = waiting("c2", "c3") | {"chime": False}
        page.wait_for_timeout(4000)
        check("muted stays muted when another arrives", rings() == 1, rings())
        page.locator("#sound").click()
        page.wait_for_timeout(300)
        check("unmuted, it sounds at once", page.locator("#sound").inner_text() == "chime" and rings() == 2, rings())
        fake.body = waiting("c2", "c3", ready=["c4"])
        page.wait_for_timeout(4000)
        check("finishing gets the tick, not the chime", ticks() == 1 and rings() == 2, (rings(), ticks()))
        page.wait_for_timeout(4000)
        check("and the tick does not repeat", ticks() == 1, ticks())
        fake.body = waiting("c2", "c3", "c5", ready=["c4", "c6"])
        page.wait_for_timeout(4000)
        check("both at once: you hear the question", rings() == 3 and ticks() == 1, (rings(), ticks()))
    check(f"{view}: nothing stray reached the routes", not fake.stray, fake.stray)
    page.close()


def blocks_pass(browser):
    """The old view, still reachable at ?view=blocks with all its controls."""
    # Three projects and two loose sessions, so there is a third to pin and an
    # orphan to assign.
    loose = ("", "No project", [S("o1", "Rosalie"), S("o2", "Ines")])
    base = roster([("alpha", "alpha", [S("a1", "ALEF", "busy")]), ("beta", "beta", [S("b1", "BETA", "busy")]),
                   ("gamma", "gamma", [S("g1", "GIMEL", "busy")]), loose])
    base["blocks"][3]["members"][0]["suggestion"] = "alpha"
    fake = Fake(base)
    page = new_page(browser, fake)
    open_at(page, "/?view=blocks")
    page.wait_for_selector(".block")
    check("blocks view: it is the old page", page.locator(".ov-col").count() == 0 and page.locator(".block").count() == 4
          and not page.locator("#hold").is_hidden() and page.locator("#view").get_attribute("href") == "./")
    page.evaluate("""() => { window.removals = [];
      const orig = Element.prototype.remove;
      Element.prototype.remove = function () {
        if (this.classList?.contains('inline')) window.removals.push('removed');
        return orig.call(this); }; }""")

    # --- renaming and relabelling
    target = page.locator(".block:not(.orphan):not(.routines)").first
    open_editor(page, target.locator('[data-edit="name"]'))
    page.locator("input.inline").fill("RINOMINATO")
    page.locator("input.inline").press("Enter")
    page.wait_for_timeout(600)
    check("rename di un progetto", fake.of("/api/name") == [{"project": "alpha", "label": "RINOMINATO"}], fake.posts)
    check("etichetta mostrata", page.locator('.block[data-project="alpha"] [data-edit="name"]')
          .inner_text().strip() == "RINOMINATO")
    row = page.locator('.block:not(.orphan):not(.routines) [data-edit="line"]').first
    open_editor(page, row)
    page.locator("input.inline").fill("RIGA")
    page.locator("input.inline").press("Enter")
    page.wait_for_timeout(600)
    check("override della riga", fake.of("/api/line") == [{"key": "a1", "text": "RIGA"}], fake.posts)
    check("modificare non fa il jump", not fake.of("/api/jump"))
    open_editor(page, page.locator('.block:not(.orphan):not(.routines) [data-edit="line"]').first)
    page.keyboard.type("mezzo scritto")
    page.wait_for_timeout(7000)
    check("il campo regge due poll",
          page.locator("input.inline").count() == 1
          and page.evaluate("document.activeElement?.classList.contains('inline')")
          and page.locator("input.inline").input_value() == "mezzo scritto",
          page.evaluate("window.removals"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    # --- pinning
    blocks = page.locator(".block:not(.orphan):not(.routines)")
    third = blocks.nth(2).get_attribute("data-project")
    blocks.nth(2).locator(".pin").drag_to(blocks.nth(0))
    page.wait_for_timeout(900)
    check("trascinare fissa il blocco", fake.of("/api/order") and third in fake.of("/api/order")[-1]["pinned"], fake.posts)
    page.wait_for_function("p => document.querySelector(`.block[data-project=\"${p}\"]`)?.classList.contains('pinned')",
                           arg=third, timeout=5000)
    page.locator(f'.block[data-project="{third}"] .pin').click()
    page.wait_for_timeout(600)
    check("la ✳ lo libera", third not in fake.of("/api/order")[-1]["pinned"], fake.of("/api/order"))
    shown = page.locator(".block:not(.orphan):not(.routines)").evaluate_all("els => els.map(e => e.dataset.project)")
    check("the block view says which blocks it shows, on a drag and on an unpin, so a block named by an identity can be unpinned",
          all(sorted(post.get("shown") or []) == sorted(shown) for post in fake.of("/api/order")),
          (shown, fake.of("/api/order")))

    # --- assigning
    chip = page.locator(".guess").first
    chip.click()
    page.wait_for_timeout(600)
    check("accettare il suggerimento", fake.of("/api/assign") == [{"key": "o1", "project": "alpha"}], fake.posts)
    page.locator('.row[data-sid="o1"] .clear').click()
    page.wait_for_timeout(600)
    check("'togli' la riporta indietro", fake.of("/api/assign")[-1] == {"key": "o1", "project": ""}, fake.posts)
    page.locator('.row.stub[data-sid="o2"]').click()       # the second one is folded until asked for
    open_editor(page, page.locator('.assign-edit[data-sid="o2"]'))
    page.locator("input.inline").fill("progetto-scritto")
    page.locator("input.inline").press("Enter")
    page.wait_for_timeout(600)
    check("assegnare scrivendo il nome", fake.of("/api/assign")[-1] == {"key": "o2", "project": "progetto-scritto"})
    page.locator('section.orphan .row[data-sid="o1"]').drag_to(page.locator(".block:not(.orphan):not(.routines)").first)
    page.wait_for_timeout(600)
    check("trascinare assegna la sessione",
          fake.of("/api/assign")[-1]["key"] == "o1" and fake.of("/api/assign")[-1]["project"], fake.of("/api/assign"))
    check("blocks view: nothing stray reached the routes", not fake.stray, fake.stray)
    page.close()

    # --- stuck and waiting, routines, folding, states, a boss and its team
    def view(body):
        f = Fake(body)
        p = new_page(browser, f)
        open_at(p, "/?view=blocks")
        p.wait_for_selector(".row")
        return f, p

    stuck = roster([("maple", "maple", [
        S("s1", "Vera", "waiting", "waiting", note="input needed"), S("s2", "Mei", "busy", "stuck", note="17m"),
        S("s3", "Leila", "busy"), S("s4", "Aziz", "busy", "tool", note="34m"),
        S("s5", "Handoff review", "idle", line="Handoff review", kind="bg")])])
    f, p = view(stuck)
    check("la riga in attesa è marcata", p.locator(".row.waiting .flag.waiting").count() == 1)
    check("la riga ferma è marcata", p.locator(".row.stuck .flag.stuck").count() == 1)
    check("dice da quanto è ferma", "17m" in p.locator(".flag.stuck").inner_text().lower())
    check("chi lavora resta pulito", p.locator(".row:not(.stuck):not(.waiting)").count() == 3)
    check("il badge conta la chiamata, non il silenzio", "34m" in p.locator(".flag.tool").inner_text().lower()
          and p.locator(".row.tool").count() == 0)
    check("non ripete il titolo uguale al nome", p.locator('.row[data-sid="s5"] .title').count() == 0)
    head = p.locator("#count").inner_text()
    check("la testata avvisa", "waiting" in head and "stuck" in head, head)
    check("il titolo della scheda conta", p.title().startswith("(2)"), p.title())
    check("chi è fermo o in attesa non si piega mai", p.locator(".row.stub.stuck, .row.stub.waiting").count() == 0)
    p.close()

    routines = roster([("maple", "maple", [S("s1", "Vera", "busy")])])
    routines["blocks"].append(routine_block())
    f, p = view(routines)
    check("le routine stanno in un blocco solo, in fondo", p.locator(".block.routines").count() == 1
          and p.locator(".block.routines .row").count() == 2 and "routines" in p.locator(".block").last.get_attribute("class"))
    check("non si fissa e non si rinomina", p.locator(".block.routines .pin").count() == 0
          and p.locator('.block.routines [data-edit="name"]').count() == 0)
    check("ogni riga dice quale routine è", sorted(x.lower() for x in p.locator(".block.routines .bg-tag").all_inner_texts())
          == ["disk-check", "nightly-report"])
    check("le routine non contano come progetto", "1 projects" in p.locator("#count").inner_text(),
          p.locator("#count").inner_text())
    p.close()

    four = roster([("maple", "maple", [S("f1", "Vera", "busy"), S("f2", "Mei"), S("f3", "Leila"), S("f4", "Aziz")])])
    f, p = view(four)
    check("solo il più attivo è aperto", p.locator(".row:not(.stub)").count() == 1 and p.locator(".row.stub").count() == 3)
    p.locator('.row.stub[data-sid="f3"]').click()
    p.wait_for_timeout(300)
    check("cliccarne una la apre", p.locator('.row[data-sid="f3"]:not(.stub)').count() == 1)
    p.locator('.row[data-sid="f3"] .fold').click()
    p.wait_for_timeout(300)
    check("il chevron la richiude", p.locator('.row.stub[data-sid="f3"]').count() == 1)
    check("aprire e chiudere non fa il jump", not f.of("/api/jump"))
    p.locator('.row.stub[data-sid="f4"]').click()
    p.wait_for_timeout(7000)
    check("resta aperta attraverso i poll", p.locator('.row[data-sid="f4"]:not(.stub)').count() == 1)
    p.locator("#q").fill("leila")
    p.wait_for_timeout(500)
    check("cercando si apre quello che trova", p.locator(".row.stub").count() == 0 and p.locator(".row").count() == 1)
    check("mostra da quanto è in piedi", "up " in p.locator(".where").first.inner_text())
    p.close()

    states = roster([("maple", "maple", [
        S("p1", "Vera", "waiting", "waiting", note="input needed"), S("p2", "Mei", "busy", "stuck", note="17m"),
        S("p3", "Nour", "idle", "ready", said="Two had no composer — guess or skip?"),
        S("p4", "Halima", "busy"), S("p5", "Dmitri", "shell", bg=True)])])
    f, p = view(states)
    check("finito e non letto è una spunta blu", p.locator('.row[data-sid="p3"] .tick').count() == 1
          and p.locator('.row[data-sid="p3"] .dot').count() == 0 and p.locator(".row.ready").count() == 1)
    check("dice l'ultima cosa che ha detto", "guess or skip" in p.locator('.row[data-sid="p3"] .said').inner_text())
    check("chi aspetta dice cosa aspetta", p.locator('.row[data-sid="p1"] .wf').inner_text() == "input needed")
    check("un lavoro in background è marcato bg", p.locator('.row[data-sid="p5"] .bg-tag').inner_text().lower() == "bg")
    check("si muove solo chi lavora", p.locator(".row.working").count() == 2)
    check("la testata conta anche i pronti", "1 ready" in p.locator("#count").inner_text())
    p.close()

    team = roster([
        ("pmd", "pmd", [S("b1", "Lennart", "idle", boss=True, team=["Rosalie", "Kasper"], reportsTo=""),
                        S("b2", "Rosalie", "idle", "ready", reportsTo="Lennart", said="Schema migration is green"),
                        S("b3", "Kasper", "busy", reportsTo="Lennart"),
                        S("b5", "Nour", "waiting", "waiting", note="input needed", reportsTo="Lennart")]),
        ("maple", "maple", [S("b4", "Vera", "idle", reportsTo="Lennart")])])
    f, p = view(team)
    check("il boss è marcato e guida il blocco", p.locator('.row[data-sid="b1"] .bg-tag.boss').count() == 1
          and p.locator("#main .row").first.get_attribute("data-sid") == "b1")
    check("dice chi è la squadra", p.locator('.row[data-sid="b1"] .team').inner_text().strip() == "↳ Rosalie · Kasper")
    check("la squadra è annidata sotto di lui", p.locator('.row[data-sid="b3"].under').count() == 1
          and p.locator('.row[data-sid="b1"].under').count() == 0)
    check("il ready di un worker resta piegato", p.locator('.row.stub[data-sid="b2"] .tick').count() == 1)
    check("un worker che aspetta si apre lo stesso", p.locator('.row[data-sid="b5"]:not(.stub)').count() == 1)
    check("chi è in un altro progetto lo dice a parole",
          p.locator('.row[data-sid="b4"] .reports').inner_text().strip() == "↳ Lennart")
    p.close()

    # --- holding the order
    served = roster([("alpha", "alpha", [S("h1", "H1", "busy")]), ("beta", "beta", [S("h2", "H2", "busy")])])
    f, p = view(served)
    order = lambda: [b.get_attribute("data-project") for b in p.locator(".block").all()]
    check("di default si riordina da solo", order() == ["alpha", "beta"], order())
    p.locator("#hold").click()
    p.wait_for_timeout(600)
    check("il pulsante dice che è fermo", p.locator("#hold").inner_text() == "order held"
          and f.of("/api/hold") == [{"hold": True}], f.posts)
    f.body["blocks"].reverse()
    p.wait_for_timeout(4000)
    check("fermo, le carte non si muovono", order() == ["alpha", "beta"], order())
    p.locator("#hold").click()
    p.wait_for_timeout(4000)
    check("riacceso, si riordina subito", order() == ["beta", "alpha"] and p.locator("#hold").inner_text() == "auto-arrange", order())
    f.body["hold"] = True
    f.body["blocks"].reverse()
    p.reload(wait_until="load")
    p.wait_for_selector(".block")
    f.body["blocks"].reverse()
    p.wait_for_timeout(4000)
    check("ricaricando resta fermo, e non si muove al poll dopo", order() == ["alpha", "beta"], order())
    check("blocks view: nothing stray reached the routes", not f.stray, f.stray)
    p.close()


def hand_roster(**names):
    got = roster([("folder:pear", names.get("pear", "pear"), [S("p1", "Saskia")]),
                  ("folder:maple", "maple", [S("m1", "Ilse"), S("m2", "Femi")]),
                  ("folder:orchard", "orchard", [S("o1", "Odile")]),
                  ("", "No project", [S("n1", "Kasper")])])
    for c in got["columns"]:
        c.update(pinned=False, raw=c["project"].partition(":")[2], kind="none" if c["project"] == "" else "folder")
    return got


def hand_pass(browser):
    """By hand, as the page makes it: pin, arrows, unpin, rename, merge, move.
    The routes are the fixture's; what is checked is what the page asks and shows."""
    fake = Fake(hand_roster(pear=BOMB))
    page = new_page(browser, fake)
    open_at(page)
    page.wait_for_selector(".ov-col")
    col = lambda p: page.locator(f'.ov-col[data-project="{p}"]')
    order = lambda: page.locator(".ov-col").evaluate_all("els => els.map(e => e.dataset.project)")
    posts = lambda path: fake.of(path)

    check("a project card has a pin button and a merge; No project has neither",
          col("folder:maple").locator(".ov-pin").count() == 1 and col("folder:maple").locator(".ov-merge").count() == 1
          and col("").locator(".ov-tools").count() == 0)
    check("nothing is pinned: no arrows anywhere and the pin is not pressed",
          page.locator(".ov-arrow").count() == 0
          and page.locator('.ov-pin[aria-pressed="true"]').count() == 0)

    col("folder:maple").locator(".ov-pin").click()
    page.wait_for_function("() => document.querySelector('.ov-col[data-project=\"folder:maple\"] .ov-head.pinned')")
    col("folder:orchard").locator(".ov-pin").click()
    page.wait_for_function("() => document.querySelectorAll('.ov-head.pinned').length === 2")
    check("a click on the pin asks the server to pin that project, once each, by identity",
          [{k: v for k, v in p.items() if k != "shown"} for p in posts("/api/pin")]
          == [{"project": "folder:maple", "action": "pin"}, {"project": "folder:orchard", "action": "pin"}],
          posts("/api/pin"))
    check("and says which cards are pinned as the page shows them, in order (a pin by plain name can hold two)",
          [p["shown"] for p in posts("/api/pin")] == [[], ["folder:maple"]], posts("/api/pin"))
    check("pinned projects lead in the order they were pinned", order()[:3] == ["folder:maple", "folder:orchard", "folder:pear"], order())
    check("a pinned card is lit and its pin is pressed",
          col("folder:maple").locator(".ov-pin.on").get_attribute("aria-pressed") == "true"
          and "pinned" in col("folder:maple").locator(".ov-head").get_attribute("class"))
    arrows = lambda p: col(p).locator(".ov-arrow").evaluate_all("els => els.map(e => e.textContent)")
    check("the first pinned card can only go after, the last only before; unpinned have none",
          arrows("folder:maple") == ["›"] and arrows("folder:orchard") == ["‹"] and arrows("folder:pear") == [],
          (arrows("folder:maple"), arrows("folder:orchard")))

    page.locator("#q").fill("orch")
    page.wait_for_function("() => document.querySelectorAll('.ov-col').length === 1")
    check("a filter that hides the neighbour takes the arrow away rather than pointing at a hidden card",
          arrows("folder:orchard") == [], arrows("folder:orchard"))
    page.locator("#q").fill("")
    page.wait_for_function("() => document.querySelectorAll('.ov-col').length === 4")
    check("and clearing it gives the arrow back", arrows("folder:orchard") == ["‹"], arrows("folder:orchard"))

    col("folder:maple").locator(".ov-arrow").click()
    page.wait_for_function("() => document.querySelector('.ov-col').dataset.project === 'folder:orchard'")
    check("an arrow swaps with the neighbour it points at, named by identity",
          posts("/api/pin")[-1] == {"project": "folder:maple", "action": "swap", "with": "folder:orchard",
                                    "side": "after", "shown": ["folder:maple", "folder:orchard"]}
          and order()[:2] == ["folder:orchard", "folder:maple"], posts("/api/pin")[-1])

    col("folder:orchard").locator(".ov-pin").click()
    page.wait_for_function("() => document.querySelectorAll('.ov-head.pinned').length === 1")
    check("the pin again unpins, and the card goes back among the others",
          posts("/api/pin")[-1] == {"project": "folder:orchard", "action": "unpin",
                                    "shown": ["folder:orchard", "folder:maple"]}
          and order() == ["folder:maple", "folder:orchard", "folder:pear", ""]
          and arrows("folder:maple") == [], order())

    # Rename: the name is the field.
    open_editor(page, col("folder:orchard").locator(".ov-name"))
    page.locator("input.inline").fill("Orchard 2")
    page.keyboard.press("Enter")
    page.wait_for_function("() => !document.querySelector('input.inline')")
    check("a click on the name edits it in place and sends the project's identity",
          posts("/api/name") == [{"project": "folder:orchard", "label": "Orchard 2"}], posts("/api/name"))
    check("the raw name is on hover, so a rename hides nothing",
          col("folder:orchard").locator(".ov-name").get_attribute("title").startswith("orchard"))

    # Merge: a form that waits for you, and a poll that leaves it alone.
    col("folder:orchard").hover()
    col("folder:orchard").locator(".ov-merge").click()
    form = page.locator(".ov-form")
    check("merge opens one form on that card", form.count() == 1 and col("folder:orchard").locator(".ov-form").count() == 1)
    options = lambda: page.locator("select.pick option").evaluate_all("els => els.map(e => [e.value, e.textContent])")
    check("it offers every other project, not itself and not No project, and shows a hostile name as text",
          [v for v, _ in options()[1:]] == ["folder:maple", "folder:pear"]
          and options()[2][1] == BOMB and page.locator("select.pick img").count() == 0, options())
    poll_now(page)
    check("a poll while the form is open does not repaint it away", page.locator(".ov-form").count() == 1)
    page.keyboard.press("Escape")
    check("Escape closes it and nothing is sent", page.locator(".ov-form").count() == 0 and not posts("/api/merge"))
    col("folder:orchard").locator(".ov-merge").click()
    page.locator("select.pick").select_option("folder:maple")
    check("choosing is not merging: nothing is sent until the button", not posts("/api/merge"))
    page.locator(".ov-form button", has_text="merge").click()
    page.wait_for_function("() => !document.querySelector('.ov-form')")
    page.wait_for_function("() => !document.querySelector('.ov-col[data-project=\"folder:orchard\"]')")
    check("the merge button sends source and target by identity",
          posts("/api/merge") == [{"source": "folder:orchard", "target": "folder:maple",
                                   "shown": ["folder:maple"]}], posts("/api/merge"))
    check("the absorbed card is gone and its session is in the other",
          "folder:orchard" not in order() and col("folder:maple").locator(".tile").count() == 3, order())

    check("the card that took it says what it includes",
          col("folder:maple").locator(".ov-merged").inner_text().startswith("includes orchard"),
          col("folder:maple").locator(".ov-merged").count())
    col("folder:maple").locator(".ov-merged button").click()
    page.wait_for_function("() => !document.querySelector('.ov-merged')")
    check("undo moves the absorbed project into nothing, by identity, and says which card it was in",
          posts("/api/assign") == [{"key": "folder:orchard", "project": "", "was": "folder:maple"}], posts("/api/assign"))
    fake.posts[:] = [x for x in fake.posts if x[0] != "/api/assign"]

    # Move one session.
    tile = col("folder:maple").locator('.tile[data-sid="m2"]')
    opacity = lambda: tile.locator(".move").evaluate("e => getComputedStyle(e).opacity")
    box = lambda: tile.bounding_box()["height"]
    unlit, height = opacity(), box()
    tile.hover()
    check("the move button is unlit until the pointer is on the tile, and lighting it moves nothing",
          unlit == "0" and opacity() == "1" and box() == height, (unlit, opacity(), height, box()))
    tile.locator(".move").click()
    check("move opens a picker without the tile jumping", page.locator("select.pick").count() == 1
          and not [p for p, _ in fake.posts if p == "/api/jump"])
    check("it offers the other projects, not this one",
          [v for v, _ in options()[1:]] == ["folder:pear"], options())
    page.locator("select.pick").select_option("folder:pear")
    page.locator(".ov-form button", has_text="move").click()
    page.wait_for_function("() => !document.querySelector('.ov-form')")
    page.wait_for_function("() => document.querySelector('.tile[data-sid=\"m2\"] .clear')")
    check("the move sends the session's key and the project's identity",
          posts("/api/assign") == [{"key": "m2", "project": "folder:pear"}], posts("/api/assign"))
    moved = page.locator('.tile[data-sid="m2"]')
    check("the moved tile says so, with the way back always showing",
          moved.locator(".clear").inner_text().startswith("moved by you") and moved.locator(".clear").is_visible())
    moved.locator(".clear").click()
    page.wait_for_timeout(300)
    check("the way back sends an empty project", posts("/api/assign")[-1] == {"key": "m2", "project": ""}, posts("/api/assign"))

    # A refusal (409): another tab changed the card, nothing was written. The page reads
    # the roster again and says so in one short line that stays; it does not say "not done".
    stamp = lambda: page.locator("#stamp").inner_text()
    logged = len(errors)
    for label, path, act in (("a click on a card's pin", "/api/pin", lambda: col("folder:pear").locator(".ov-pin").click()),
                             ("a rename by its field", "/api/name", None)):
        fake.status[path] = 409
        forget_note(page)
        polls = fake.polls
        if act:
            act()
        else:
            open_editor(page, col("folder:pear").locator(".ov-name"))
            page.locator("input.inline").fill("Pear 2")
            page.keyboard.press("Enter")
        page.wait_for_function("() => document.getElementById('stamp').textContent === 'changed in another tab, refreshed'")
        check(f"409 on {label}: the roster is read again and the line says so", fake.polls > polls and "not done" not in stamp(), stamp())
        check(f"409 on {label}: nothing was applied", not col("folder:pear").locator(".ov-pin.on").count()
              and col("folder:pear").locator(".ov-name").inner_text() == BOMB, stamp())
        fake.status.clear()
    # Chromium logs each HTTP 409 as a console error: these two are the ones asked for, and no others.
    refused = [e for e in errors[logged:] if "status of 409" in e]
    errors[logged:] = [e for e in errors[logged:] if e not in refused]
    check("409: the console line Chromium logs for each of the two refusals, and nothing else", len(refused) == 2, refused)
    check("hand: nothing stray reached the routes", not fake.stray, fake.stray)
    page.close()


def picker_pass(browser):
    """Two projects called alike must read differently where you choose one:
    by kind, then by what the identity starts with (a client folder and a folder
    are both folders), then -- two repositories -- by the identity itself."""
    got = roster([("track:acme", "acme", [S("t1", "Ilse")]),
                  ("folder:acme", "acme", [S("f1", "Femi")]),
                  ("client:example.test/x/mono/acme", "acme", [S("c1", "Odile")]),
                  ("repo:example.test/a/shop", "shop", [S("r1", "Saskia")]),
                  ("repo:example.test/b/shop", "shop", [S("r2", "Kasper")]),
                  ("folder:solo", "solo", [S("s1", "Bram")]),
                  ("", "No project", [S("n1", "Ines")])])
    kinds = {"track": "track", "repo": "repository", "client": "folder", "folder": "folder"}
    for c in got["columns"]:
        c.update(pinned=False, raw=c["project"].partition(":")[2],
                 kind="none" if c["project"] == "" else kinds[c["project"].partition(":")[0]])
    page = new_page(browser, Fake(got))
    open_at(page)
    page.wait_for_selector(".ov-col")
    page.locator('.ov-col[data-project="folder:solo"]').hover()
    page.locator('.ov-col[data-project="folder:solo"] .ov-merge').click()
    options = page.locator("select.pick option").evaluate_all("els => els.map(e => [e.value, e.textContent])")[1:]
    labels = [text for _, text in options]
    check("the picker tells two projects with one name apart, whatever they share",
          len(set(labels)) == len(labels), labels)
    check("by kind where that is enough, by the identity's start where the kind is shared, by the identity otherwise",
          dict(options) == {"track:acme": "acme (track)", "folder:acme": "acme (folder)",
                            "client:example.test/x/mono/acme": "acme (client)",
                            "repo:example.test/a/shop": "shop (repo:example.test/a/shop)",
                            "repo:example.test/b/shop": "shop (repo:example.test/b/shop)"}, options)
    page.close()


def start_hand_server(root, procs):
    """`tests/hand_server.py` on a port the system picks, state under `root`; its pid is proven with `ss`."""
    env = {**os.environ, "XDG_STATE_HOME": str(root / "state"), "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.Popen([sys.executable, str(HERE / "hand_server.py"), str(root)],
                            stdout=subprocess.PIPE, text=True, env=env)
    procs.append(proc)
    port = int(proc.stdout.readline().split()[1])
    held = subprocess.run(["ss", "-ltnp", f"sport = :{port}"], capture_output=True, text=True).stdout
    check("e2e: the listener on the test port is the server just started", f"pid={proc.pid}," in held and port != 8765,
          held.strip())
    return proc, port


def open_hand_page(browser, port, refusals=None):
    """A page that may reach nothing but the test server on `port`. Chromium logs every
    HTTP 409 as a console error; a pass that makes some on purpose passes a list to collect them."""
    page = browser.new_page(viewport={"width": 1700, "height": 2400})
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: (refusals.append(m.text) if refusals is not None and "status of 409" in m.text
                                  else errors.append(f"console: {m.text}")) if m.type == "error" else None)
    page.on("dialog", lambda d: (errors.append(f"dialog: {d.message}"), d.dismiss()))
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(f"http://127.0.0.1:{port}/")
               else r.abort())
    page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
    page.wait_for_selector(".ov-col")
    return page


def forget_note(page):
    """Clear the line a refusal left on the page (it holds for six seconds), so that the next
    wait for it is a wait for the next refusal and not for the last one."""
    page.evaluate("() => { NOTE = null; document.getElementById('stamp').textContent = ''; }")


def hold_back(page):
    """Make a tab stale, as a picker left open does: from now on it is served the roster it
    already has, until the first thing it POSTs -- then the real one again, for the page's
    own refresh after a refusal."""
    body = page.evaluate("fetch('/api/roster', {cache: 'no-store'}).then(r => r.text())")
    state = {"posted": False}
    page.on("request", lambda r: state.update(posted=True) if r.method == "POST" else None)
    page.route("**/api/roster", lambda route: route.continue_() if state["posted"]
               else route.fulfill(status=200, content_type="application/json", body=body))


def stale_pass(browser):
    """Two or three tabs on one real server, some of them behind: a tab clicks on a card
    another tab has since changed, the two routes hunt 6 found. The server must refuse,
    change nothing, and the page must read again and say so."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="stale-"))
    cfg = root / "config.json"
    procs = []
    stored = lambda: json.loads(cfg.read_text())
    line = "changed in another tab, refreshed"
    try:
        proc, port = start_hand_server(root, procs)
        refused = []        # Chromium's own console line for each 409 this pass provokes
        a, b, c = (open_hand_page(browser, port, refused) for _ in range(3))
        col = lambda page, p: page.locator(f'.ov-col[data-project="{p}"]')
        order = lambda page: page.locator(".ov-col").evaluate_all("els => els.map(e => e.dataset.project)")
        wait_order = lambda page, want: page.wait_for_function(
            "want => [...document.querySelectorAll('.ov-col')].map(e => e.dataset.project).join() === want.join()",
            arg=want, timeout=8000)
        def wait_for(cond):
            for _ in range(80):
                if cond():
                    return
                a.wait_for_timeout(100)
        said = lambda page: page.locator("#stamp").inner_text()

        # Hunt 6, finding 2: both tabs show maple, orchard and both click the arrow on maple.
        for p in ("folder:maple", "folder:orchard"):
            col(a, p).locator(".ov-pin").click()
            wait_for(lambda p=p: p in stored().get("pinned", []))
        b.wait_for_function("() => document.querySelectorAll('.ov-head.pinned').length === 2")
        hold_back(b)
        col(a, "folder:maple").locator(".ov-arrow").click()
        wait_for(lambda: stored()["pinned"] == ["folder:orchard", "folder:maple"])
        check("stale: tab b still shows what it showed, maple before orchard",
              order(b)[:2] == ["folder:maple", "folder:orchard"], order(b))
        forget_note(b)
        col(b, "folder:maple").locator(".ov-arrow").click()
        b.wait_for_function("line => document.getElementById('stamp').textContent === line", arg=line)
        wait_order(b, ["folder:orchard", "folder:maple", "folder:pear"])
        check("stale: the same arrow clicked in a tab that was behind does not undo the first",
              stored()["pinned"] == ["folder:orchard", "folder:maple"] and order(a) == order(b), stored())

        # Hunt 6, finding 1: orchard and pear merged into maple while b and c still show them.
        wait_order(c, ["folder:orchard", "folder:maple", "folder:pear"])
        hold_back(b)
        hold_back(c)
        for p in ("folder:orchard", "folder:pear"):
            col(a, p).hover()
            col(a, p).locator(".ov-merge").click()
            a.locator("select.pick").select_option("folder:maple")
            a.locator(".ov-form button", has_text="merge").click()
            wait_for(lambda p=p: p in stored().get("assign", {}))
        wait_order(a, ["folder:maple"])
        done = stored()
        check("stale: both merges are in the config, and maple took orchard's place among the pins",
              done["assign"] == {"folder:orchard": "folder:maple", "folder:pear": "folder:maple"}
              and done["pinned"] == ["folder:maple"], done)
        check("stale: tabs b and c still show the cards that are gone", "folder:orchard" in order(b) and "folder:pear" in order(c),
              (order(b), order(c)))
        forget_note(b)
        col(b, "folder:orchard").locator(".ov-pin").click()      # the star it still shows lit
        b.wait_for_function("line => document.getElementById('stamp').textContent === line", arg=line)
        wait_order(b, ["folder:maple"])
        check("stale: the star of a card another tab merged away does not unpin the card that took its pin",
              stored() == done and col(b, "folder:maple").locator(".ov-pin.on").count() == 1, stored())
        forget_note(c)
        col(c, "folder:pear").locator(".ov-pin").click()          # the star it still shows unlit
        c.wait_for_function("line => document.getElementById('stamp').textContent === line", arg=line)
        wait_order(c, ["folder:maple"])
        check("stale: nor does one pin a project with no card",
              stored() == done and "not done" not in said(c), stored())
        check("stale: and the line says what happened, calmly", said(c) == line and said(b) == line, (said(b), said(c)))
        check("stale: three clicks, three refusals, nothing else refused", len(refused) == 3, refused)
        for page in (a, b, c):
            page.close()
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(10)
        shutil.rmtree(root, ignore_errors=True)


def block_view_pass(browser):
    """Hunts 7 and 8: the old block view after a session was moved by hand into a project and
    that project was merged away. A tab that is up to date must be able to rename, drag and drop
    on the session's block (the server must not call it behind); a tab that is behind, which
    clicks the star of the block that was merged away, must be told rather than answered 200
    with nothing unpinned."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="blocks-"))
    cfg = root / "config.json"
    procs = []
    stored = lambda: json.loads(cfg.read_text())
    line = "changed in another tab, refreshed"
    try:
        proc, port = start_hand_server(root, procs)
        refused_a, refused_b = [], []
        a, b = open_hand_page(browser, port, refused_a), open_hand_page(browser, port, refused_b)
        post = lambda page, path, body: page.evaluate(
            "([p, b]) => fetch(p, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Fleet': '1'},"
            " body: JSON.stringify(b)}).then(r => r.status)", [path, body])
        check("blocks e2e: a session moved by hand into maple, and maple pinned",
              (post(a, "/api/assign", {"key": "fake:c", "project": "folder:maple"}),
               post(a, "/api/pin", {"project": "folder:maple", "action": "pin", "shown": []})) == (200, 200), stored())

        # Tab b is on the block view and behind when maple is merged away; it clicks the star of that block.
        b.goto(f"http://127.0.0.1:{port}/?view=blocks", wait_until="load")
        b.wait_for_selector(".block")
        check("blocks e2e: tab b shows the block named for maple, pinned",
              b.locator('.block.pinned[data-project="folder:maple"]').count() == 1,
              b.locator(".block").evaluate_all("els => els.map(e => e.dataset.project + (e.classList.contains('pinned') ? '*' : ''))"))
        hold_back(b)
        check("blocks e2e: maple merged into orchard in the other tab",
              post(a, "/api/merge", {"source": "folder:maple", "target": "folder:orchard", "shown": ["folder:maple"]}) == 200
              and stored()["pinned"] == ["folder:orchard"], stored())
        done = stored()
        forget_note(b)
        b.locator('.block[data-project="folder:maple"] .pin').click()
        b.wait_for_function("line => document.getElementById('stamp').textContent === line", arg=line)
        check("blocks e2e: the star of a block that was merged away is refused, and nothing is written",
              stored() == done and len(refused_b) == 1, (stored(), refused_b))
        check("blocks e2e: and the tab reads again: the block is named for orchard, still pinned",
              b.locator('.block.pinned[data-project="folder:orchard"]').count() == 1
              and b.locator('.block[data-project="folder:maple"]').count() == 0, b.locator(".block").count())
        b.close()

        # Tab a is up to date: its blocks are all ones it may rename.
        a.goto(f"http://127.0.0.1:{port}/?view=blocks", wait_until="load")
        a.wait_for_selector(".block")
        names = a.locator(".block").evaluate_all("els => els.map(e => e.dataset.project)")
        check("blocks e2e: its block is named by where the project went, not by the one merged away",
              "folder:orchard" in names and "folder:maple" not in names, names)
        block = a.locator('.block[data-project="folder:orchard"]')
        open_editor(a, block.locator(".pname"))
        a.locator("input.inline").fill("Orchard 2")
        a.keyboard.press("Enter")
        a.wait_for_function("() => !document.querySelector('input.inline')")
        a.wait_for_timeout(500)
        check("blocks e2e: renaming that block is accepted, and the page does not say it is behind",
              stored().get("names") == {"folder:orchard": "Orchard 2"} and not refused_a
              and "changed in another tab" not in a.locator("#stamp").inner_text(),
              (stored(), refused_a))
        a.close()
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(10)
        shutil.rmtree(root, ignore_errors=True)


def e2e_pass(browser):
    """The same clicks against a real server: fake sessions, a config of its own,
    on a port the system picked. What the page does must be in the config file
    afterwards, and still there when the server is started again."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="hand-"))
    cfg = root / "config.json"
    procs = []

    start = lambda: start_hand_server(root, procs)
    look = lambda port: open_hand_page(browser, port)

    stored = lambda: json.loads(cfg.read_text())
    try:
        proc, port = start()
        page = look(port)
        col = lambda p: page.locator(f'.ov-col[data-project="{p}"]')
        order = lambda: page.locator(".ov-col").evaluate_all("els => els.map(e => e.dataset.project)")
        wait_order = lambda want: page.wait_for_function(
            "want => [...document.querySelectorAll('.ov-col')].map(e => e.dataset.project).join() === want.join()",
            arg=want, timeout=8000)
        check("e2e: three projects from the sessions, in name order", order() == ["folder:maple", "folder:orchard", "folder:pear"], order())

        col("folder:pear").locator(".ov-pin").click()
        wait_order(["folder:pear", "folder:maple", "folder:orchard"])
        col("folder:orchard").locator(".ov-pin").click()
        wait_order(["folder:pear", "folder:orchard", "folder:maple"])
        check("e2e: pins are in the config in the order they were made", stored()["pinned"] == ["folder:pear", "folder:orchard"],
              stored())
        col("folder:orchard").locator(".ov-arrow").click()
        wait_order(["folder:orchard", "folder:pear", "folder:maple"])
        check("e2e: an arrow reorders the pins in the config", stored()["pinned"] == ["folder:orchard", "folder:pear"], stored())
        col("folder:pear").locator(".ov-pin").click()
        wait_order(["folder:orchard", "folder:maple", "folder:pear"])
        check("e2e: unpinning takes it out of the config", stored()["pinned"] == ["folder:orchard"], stored())

        open_editor(page, col("folder:maple").locator(".ov-name"))
        page.locator("input.inline").fill("Maple tree")
        page.keyboard.press("Enter")
        page.wait_for_function("() => document.querySelector('.ov-name') && [...document.querySelectorAll('.ov-name')].some(e => e.textContent === 'Maple tree')")
        check("e2e: a rename is in the config by identity", stored()["names"] == {"folder:maple": "Maple tree"}, stored())

        def merge_pear():
            col("folder:pear").hover()
            col("folder:pear").locator(".ov-merge").click()
            page.locator("select.pick").select_option("folder:maple")
            page.locator(".ov-form button", has_text="merge").click()
            wait_order(["folder:orchard", "folder:maple"])

        merge_pear()
        check("e2e: a merge is a move of the whole project in the config",
              stored()["assign"] == {"folder:pear": "folder:maple"}, stored())
        check("e2e: and the card that took it says so",
              col("folder:maple").locator(".ov-merged").inner_text().startswith("includes Pear"))   # the default name, made readable
        col("folder:maple").locator(".ov-merged button").click()
        wait_order(["folder:orchard", "folder:maple", "folder:pear"])
        check("e2e: undo takes it back out of the config and the project is its own again",
              stored().get("assign", {}) == {} and col("folder:maple").locator(".ov-merged").count() == 0, stored())
        merge_pear()

        # One session: moved, shown as moved, and taken back.
        tile = col("folder:maple").locator('.tile[data-sid="fake:c"]')
        tile.hover()
        tile.locator(".move").click()
        page.locator("select.pick").select_option("folder:orchard")
        page.locator(".ov-form button", has_text="move").click()
        page.wait_for_function("() => document.querySelector('.ov-col[data-project=\"folder:orchard\"] .tile[data-sid=\"fake:c\"] .clear')")
        check("e2e: a session moved by hand is in the config under its own key and says so on its tile",
              stored()["assign"] == {"folder:pear": "folder:maple", "fake:c": "folder:orchard"}
              and col("folder:orchard").locator('.tile[data-sid="fake:c"] .clear').is_visible(), stored())
        col("folder:orchard").locator('.tile[data-sid="fake:c"] .clear').click()
        page.wait_for_function("() => document.querySelector('.ov-col[data-project=\"folder:maple\"] .tile[data-sid=\"fake:c\"]')")
        check("e2e: the way back takes it out of the config and puts it where its project is",
              stored()["assign"] == {"folder:pear": "folder:maple"}
              and col("folder:maple").locator('.tile[data-sid="fake:c"] .clear').count() == 0, stored())
        page.close()

        # A restart: the same config, a new server.
        proc.terminate()
        proc.wait(10)
        before = stored()
        proc, port = start()
        page = look(port)
        check("e2e: after a restart the pins, the name and the merge are all still there",
              order() == ["folder:orchard", "folder:maple"]
              and page.locator('.ov-col[data-project="folder:maple"] .ov-name').inner_text() == "Maple tree"
              and page.locator('.ov-col[data-project="folder:maple"] .tile').count() == 3, order())
        check("e2e: and starting it did not rewrite the config", stored() == before, stored())
        page.close()
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(10)
        shutil.rmtree(root, ignore_errors=True)


def finished_e2e_pass(browser):
    """Ticket 10 against a real server: invented sessions that stopped hours ago on
    a throwaway server, a config of its own. A handover you have not read keeps a
    tile; once read, a pill; a new write brings the tile back; a pin survives
    polls and a restart and ends with the session; and what the block view
    marked seen does not count as read."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="finished-"))
    (root / "config.json").write_text("{}")
    procs = []
    clock = int(time.time() * 1000)
    minutes = lambda n: clock - n * 60000
    sessions = [dict(id="a", name="Ilse", cwd="/home/alice/Projects/maple", status="idle",
                     updatedAt=minutes(300), said="Ilse rebuilt the search index."),
                dict(id="b", name="Odile", cwd="/home/alice/Projects/maple", status="idle",
                     updatedAt=minutes(400), said="Odile drafted the release notes."),
                dict(id="c", name="Saskia", cwd="/home/alice/Projects/maple", status="busy",
                     updatedAt=minutes(2), quietFor=0.1)]

    def write(rows):
        tmp = root / "sessions.json.tmp"
        tmp.write_text(json.dumps(rows))
        tmp.replace(root / "sessions.json")

    state = lambda: json.loads((root / "finished.json").read_text()) if (root / "finished.json").exists() else {}
    config_before = (root / "config.json").read_bytes()
    try:
        # What the block view left behind: Odile's stop was marked seen there.
        (root / "seen.json").write_text(json.dumps({"fake:b": sessions[1]["updatedAt"]}))
        write(sessions)
        proc, port = start_hand_server(root, procs)
        page = open_hand_page(browser, port)
        tile = lambda sid: page.locator(f'.tile[data-sid="fake:{sid}"]')
        pill = lambda sid: page.locator(f'.pill[data-sid="fake:{sid}"]')
        shown = lambda: page.locator(".tile, .pill").evaluate_all(
            "els => els.map(e => e.className.split(' ')[0] + ':' + e.dataset.sid.split(':')[1]).sort().join()")
        wait = lambda want: page.wait_for_function(
            "want => [...document.querySelectorAll('.tile, .pill')].map(e => e.className.split(' ')[0] + ':' + e.dataset.sid.split(':')[1]).sort().join() === want",
            arg=want, timeout=8000)

        check("finished e2e: sessions idle for hours whose handover is unread are full tiles", shown() == "tile:a,tile:b,tile:c", shown())
        check("and each has what it told you on it, in quotes",
              tile("a").locator(".said").inner_text() == "“Ilse rebuilt the search index.”"
              and tile("b").locator(".said").inner_text() == "“Odile drafted the release notes.”")
        check("R19: Odile, marked seen by the block view, is unread here all the same",
              tile("b").locator(".flag.unread").inner_text().lower() == "unread" and not state().get("read", {}).get("fake:b"), state())

        tile("a").click()
        wait("pill:a,tile:b,tile:c")
        check("a click that looked at Ilse's handover makes it a pill, 5 h idle",
              pill("a").locator(".for").inner_text() == "5 h" and state()["read"] == {"fake:a": sessions[0]["updatedAt"]}, state())
        check("the card counts what is left: the pill is in no count",
              head_counts(page) == ["0 need you", "0 other stuck", "1 moving"], head_line(page))

        pill("a").hover()
        pill("a").locator("button.keep").click()
        wait("tile:a,tile:b,tile:c")
        check("pinning it makes it a tile that says unpin, and the server keeps the pin",
              tile("a").locator("button.keep.on").inner_text() == "unpin" and state()["pinned"] == ["fake:a"], state())
        for _ in range(2):
            poll_now(page)
        check("the pin survives polls", shown() == "tile:a,tile:b,tile:c", shown())

        # A new write turns a pill back into a tile, and the new stop is unread.
        tile("b").click()
        wait("pill:b,tile:a,tile:c")
        write([sessions[0], {**sessions[1], "status": "busy", "quietFor": 0.1, "updatedAt": minutes(0)}, sessions[2]])
        poll_now(page)
        wait("tile:a,tile:b,tile:c")
        check("a new write brings Odile's tile back, working", tile("b").locator(".mv").inner_text().startswith("writing"))
        odile = {**sessions[1], "updatedAt": minutes(1), "said": "Odile finished the second round."}
        write([sessions[0], odile, sessions[2]])
        poll_now(page)
        page.wait_for_function("() => document.querySelector('.tile[data-sid=\"fake:b\"] .said')?.textContent.includes('second round')", timeout=8000)
        check("and when it stops again its new handover is unread",
              tile("b").locator(".said").inner_text() == "“Odile finished the second round.”", shown())

        # The pin ends with the session: closed, it is forgotten; resumed, it is not pinned.
        write([odile, sessions[2]])
        poll_now(page)
        wait("tile:b,tile:c")
        page.wait_for_timeout(200)
        check("a pinned session that closed takes its pin with it", state()["pinned"] == [], state())
        write([sessions[0], odile, sessions[2]])
        poll_now(page)
        wait("tile:a,tile:b,tile:c")
        check("resumed under the same id it is an ordinary tile with its handover unread again",
              tile("a").locator("button.keep").count() == 0 and tile("a").locator(".said").count() == 1)

        # A restart keeps what you read and what you pinned.
        tile("a").click()
        wait("pill:a,tile:b,tile:c")
        pill("a").hover()
        pill("a").locator("button.keep").click()
        wait("tile:a,tile:b,tile:c")
        page.close()
        proc.terminate()
        proc.wait(10)
        proc, port = start_hand_server(root, procs)
        page = open_hand_page(browser, port)
        check("after a restart the pin is still there and the config was not touched",
              shown() == "tile:a,tile:b,tile:c" and tile("a").locator("button.keep.on").count() == 1
              and (root / "config.json").read_bytes() == config_before, shown())
        page.close()
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(10)
        shutil.rmtree(root, ignore_errors=True)


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    url, cfg, pid = sys.argv[1], pathlib.Path(sys.argv[2]), sys.argv[3]
    parts = urllib.parse.urlsplit(url)
    if parts.hostname != "127.0.0.1" or not parts.port or not pid.isdigit():
        sys.exit("BASE_URL must be http://127.0.0.1:PORT/ and SERVER_PID a number")
    if parts.port == 8765:
        sys.exit("refusing 8765: that is the server the owner's tabs depend on")
    if not cfg.is_file() or json.loads(cfg.read_text()).get("port") != parts.port:
        sys.exit(f"{cfg} is not the config of the server on port {parts.port}")
    before = sha(cfg)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        real_keys = real_pass(browser, url, pid)
        overview_pass(browser)
        header_pass(browser)
        finished_pass(browser)
        card_pass(browser)
        needs_pass(browser)
        kinds_pass(browser)
        hand_pass(browser)
        picker_pass(browser)
        e2e_pass(browser)
        finished_e2e_pass(browser)
        stale_pass(browser)
        block_view_pass(browser)
        suggestion_pass(browser)
        jump_pass(browser)
        for view in ("overview", "blocks"):
            hostile_pass(browser, view)
            chime_pass(browser, view)
        blocks_pass(browser)
        browser.close()

    # No routed request may have carried a session the machine really has.
    sent = json.dumps(posted)
    check(f"no routed request ({len(posted)} POSTs) carried a real session key",
          not any(k in sent for k in real_keys))
    check("no JS errors, console errors or dialogs anywhere", not errors, errors[:5])
    check("the test config was only read", sha(cfg) == before, (before, sha(cfg)))
    print()
    print("all green" if not failures else f"FAILED: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
