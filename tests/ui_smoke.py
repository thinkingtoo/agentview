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

  * Every pass but one is *routed*. The page's HTML, the roster, the search and
    every POST are answered by `page.route` from fixtures built below, so a
    jump, a reopen, a revival, a rename, a snapshot never leave the browser,
    and no request carries a real session key. A request the routes do not
    know is aborted and fails the run.
  * One pass is not routed (R21): it loads the page from the server, lets the
    page poll the server's own `/api/roster` and asserts that real columns
    render. It clicks nothing, writes nothing, saves no screenshot (it shows
    real sessions), and any request that is not a GET is aborted and fails.
  * The config file is only read: its hash is taken before and after.

Playwright is needed (`pip install playwright`); the chromium it drives must
already be installed.
"""
import copy
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
PAGE = (HERE.parent / "index.html").read_text(encoding="utf-8") \
    .replace("{{ZOOM}}", "1").replace("{{HOME}}", "/home/alice")
failures = []
errors = []        # page errors, console errors and dialogs, from every page
posted = []        # every body the routed pages POSTed, from every pass
BOMB = "<img src=x onerror=alert(1)>"


def check(label, ok, detail=""):
    print(f"{label:<58} {'OK' if ok else 'FAILED ' + str(detail)}")
    if not ok:
        failures.append(label)


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


# --- fixtures -----------------------------------------------------------------
# One description of a session produces the row the block view reads (`blocks`,
# which the chime and the counts also read) and the tile the overview prints
# (`columns`), so the two never disagree about who is waiting.

def S(key, name, status="idle", flag=None, *, note="", line="", tags=(), can=True, **extra):
    return {"key": key, "name": name, "status": status, "flag": flag, "note": note,
            "line": line, "tags": list(tags), "can": can, "extra": extra}


def member(s, project):
    m = {"name": s["name"], "status": s["status"], "kind": "interactive", "provider": "claude",
         "cwd": f"/home/alice/Projects/{project}", "tmux": "", "pid": 111, "key": s["key"],
         "updatedAt": 1787830000000, "project": project, "title": s["line"] or f"{s['name']} at work",
         "prompt": "carry on", "branch": "main", "canJump": s["can"], "assigned": False,
         "suggestion": None, "quietFor": 0.2, "toolFor": None, "flag": s["flag"],
         "startedAt": 1787830000000}
    if s["flag"] == "waiting":
        m["waitingFor"] = s["note"]
    if s["flag"] in ("stuck", "tool"):
        m["quietFor"] = float(s["note"].rstrip("m"))
        m["toolFor"] = m["quietFor"] if s["flag"] == "tool" else None
    return {**m, **s["extra"]}


def tile(s):
    return {"key": s["key"], "name": s["name"], "provider": "claude", "status": s["status"],
            "tags": s["tags"], "line": s["line"], "flag": s["flag"], "flagNote": s["note"],
            "jump": {"via": "pane" if s["can"] else "none"},
            "find": f"{s['name']}\n{s['line']}".lower()}


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
                        "kind": "none" if orphan else "folder", "sessions": [tile(s) for s in sessions]})
    return {"blocks": blocks, "columns": columns, "hold": False, "chime": True, "providers": {},
            "restore": None, "closed": [], "saved": None, **top}


def routine_block():
    ms = [member(S(k, n, "busy"), "Routines") | {"routine": r, "canJump": False, "project": None}
          for k, n, r in (("r1", "Ansgar", "nightly-report"), ("r2", "Bruno", "disk-check"))]
    return {"project": "Routines", "label": "Routines", "orphan": False, "routines": True,
            "renamed": False, "pinned": False, "branches": [], "busy": 2, "alarms": 0, "ready": 0,
            "updatedAt": 1787830000000, "members": ms}


MAPLE = ("maple", "maple", [
    S("m1", "Vera", "waiting", "waiting", note="input needed", line="Port the importer", tags=["boss"]),
    S("m2", "Mei", "busy", "stuck", note="17m", line="Rewrite the parser"),
    S("m3", "Nour", "idle", "ready", line="Two had no composer — guess or skip?"),
    S("m4", "Aziz", "busy", "tool", note="34m", line="Running the full suite"),
    S("m5", "Dmitri", "idle", can=False)])
PMD = ("pmd", "pmd", [S("p1", "Lennart", "idle", tags=["boss", "codex"], line="Plan the cutover"),
                      S("p2", "Kasper", "busy", line="Schema migration")])
LOOSE = ("", "No project", [S("o1", "Rosalie", "idle", line="a loose end")])


def overview_fixture():
    """Columns in an order no browser rule would produce (not alphabetical, the
    waiting session not first), blocks the other way round with a routine block
    the columns leave out: whatever the page shows came from `columns`."""
    got = roster([PMD, MAPLE, LOOSE])
    got["blocks"] = [routine_block()] + list(reversed(got["blocks"]))
    return got


def many(n, tiles=1):
    return roster([(f"proj{i:02d}", f"proj{i:02d}",
                    [S(f"x{i}-{j}", f"S{i}-{j}", "idle", line="working on it") for j in range(tiles)])
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
        elif path == "/api/order":
            pins = b["pinned"]
            for blk in self.body["blocks"]:
                blk["pinned"] = blk["project"] in pins
            self.body["blocks"].sort(key=lambda blk: pins.index(blk["project"])
                                     if blk["project"] in pins else len(pins))

    def handle(self, route):
        req = route.request
        url = urllib.parse.urlsplit(req.url)
        json_ = lambda data: route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
        if req.method == "GET" and url.path in ("/", "/index.html"):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=PAGE)
        elif req.method == "GET" and url.path == "/api/roster":
            json_(self.body)
        elif req.method == "GET" and url.path == "/api/search":
            json_(self.found)
        elif req.method == "GET" and url.path == "/favicon.ico":
            route.fulfill(status=204)
        elif req.method == "POST" and url.path.startswith("/api/"):
            body = json.loads(req.post_data or "{}")
            self.posts.append((url.path, body))
            posted.append(body)
            self.apply(url.path, body)
            json_(self.answer.get(url.path, {"ok": True, "did": "opened", "changed": False}))
        else:
            self.stray.append(f"{req.method} {req.url}")
            route.abort()


def new_page(browser, fake, width=1700):
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
    names = lambda: [t.strip() for t in page.locator(".ov-head").all_inner_texts()]

    check("one column per project", cols() == 3, cols())
    check("columns in the order the server sent, not the blocks' or a sort",
          names() == ["pmd", "maple", "No project"], names())
    check("the routine block is not a column", "Routines" not in names())
    check("sessions in the order the server sent",
          page.locator('.ov-col[data-project="maple"] .tile').evaluate_all("els => els.map(e => e.dataset.sid)")
          == ["m1", "m2", "m3", "m4", "m5"])
    check("the project card is its name and nothing else",
          page.locator(".ov-head *").count() == 0)
    check("one tile per session", page.locator(".tile").count() == 8, page.locator(".tile").count())

    t = lambda sid: page.locator(f'.tile[data-sid="{sid}"]')
    check("a waiting tile says waiting, and what on",
          t("m1").locator(".flag.waiting").count() == 1 and t("m1").locator(".wf").inner_text() == "input needed"
          and "waiting" in t("m1").get_attribute("class"))
    check("a stuck tile says for how long", "17m" in t("m2").locator(".flag.stuck").inner_text().lower())
    check("a long tool call is news: its minutes, no alarm tint",
          "34m" in t("m4").locator(".flag.tool").inner_text().lower()
          and not any(c in t("m4").get_attribute("class") for c in ("waiting", "stuck")))
    check("finished and unread is a tick, not a dot",
          t("m3").locator(".tick").count() == 1 and t("m3").locator(".dot").count() == 0)
    check("a busy session has the breathing dot", t("m2").locator(".dot.busy").count() == 1
          and t("p2").locator(".dot.busy").count() == 1)
    check("tags print", [x.lower() for x in t("p1").locator(".bg-tag").all_inner_texts()] == ["boss", "codex"]
          and t("m1").locator(".bg-tag.boss").count() == 1)
    check("the line sits under the name", t("m2").locator(".tline").inner_text() == "Rewrite the parser"
          and t("m5").locator(".tline").count() == 0)
    check("open ↗ only where there is a pane to go to",
          t("m1").locator(".go").count() == 1 and t("m5").locator(".go").count() == 0)

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

    # Both views carry the same chime, tick and counts: the overview's header
    # reads `blocks` exactly as the block view's did.
    check("the header counts alarms from blocks", "waiting" in page.locator("#count").inner_text()
          and "stuck" in page.locator("#count").inner_text(), page.locator("#count").inner_text())
    check("the tab title counts what wants you", page.title().startswith("(2)"), page.title())
    check("the overview has no hold button and a way to the block view",
          page.locator("#hold").is_hidden() and page.locator("#view").get_attribute("href") == "?view=blocks")
    check("overview: nothing stray reached the routes", not fake.stray, fake.stray)
    page.close()
    return fake


def hostile_pass(browser, view):
    """R7 at the page: markup in a project, a name and a line is text."""
    s = S("h1", BOMB, "idle", line="line: " + BOMB)
    fake = Fake(roster([(BOMB, BOMB, [s])]))
    seen = len(errors)
    page = new_page(browser, fake)
    open_at(page, "/?view=blocks" if view == "blocks" else "/")
    page.wait_for_selector(".block" if view == "blocks" else ".tile")
    page.wait_for_timeout(500)
    text = page.locator("#main").inner_text()
    check(f"{view}: markup in a project, a name and a line is shown as text",
          text.count(BOMB) >= 3, text[:200])
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
        overview = overview_pass(browser)
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
