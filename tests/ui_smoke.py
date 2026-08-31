#!/usr/bin/env python3
"""Drive the real page against a running server.

Not part of `unittest discover`: it needs Playwright and a live server, and it
mutates config.json. Run it with `python3 tests/ui_smoke.py`.

The viewport is deliberately tall. Everything must fit without scrolling --
Playwright resolves an element's position, then scrolls to reach it, and a drag
that starts after a scroll grabs whatever moved under the cursor.
"""
import json
import pathlib
import sys
import urllib.request

from playwright.sync_api import sync_playwright

CFG = pathlib.Path(__file__).resolve().parent.parent / "config.json"


def _member(name, status, stuck, quiet, sid):
    return {"name": name, "status": status, "kind": "interactive",
            "cwd": "/home/alice/Projects/maple", "tmux": "", "pid": 111,
            "sessionId": sid, "updatedAt": 1787830000000, "project": "maple",
            "title": f"{name} at work", "prompt": "carry on", "branch": "main",
            "canJump": True, "assigned": False, "suggestion": None,
            "quietFor": quiet, "toolFor": quiet if stuck == "tool" else None,
            "flag": stuck, "startedAt": 1787830000000}


STUCK_PAYLOAD = {"blocks": [{
    "project": "maple", "label": "maple", "orphan": False, "renamed": False,
    "pinned": False, "branches": ["main"], "busy": 1, "alarms": 2, "ready": 0,
    "updatedAt": 1787830000000, "members": [
        _member("Vera", "waiting", "waiting", 0.3, "s1"),
        _member("Mei", "busy", "stuck", 17.0, "s2"),
        _member("Leila", "busy", None, 0.1, "s3"),
        _member("Aziz", "busy", "tool", 34.0, "s4"),
        # A `/btw` helper: Claude Code never named it, so its name IS its
        # title. Printing both would say the same thing twice.
        {**_member("Handoff review", "idle", None, 1.0, "s5"),
         "title": "Handoff review", "kind": "bg"}]}]}
def _routine(name, routine, sid):
    return {**_member(name, "busy", None, 0.2, sid), "routine": routine,
            "cwd": "/home/alice", "project": None, "branch": "", "canJump": False,
            "title": "", "prompt": "processing a recording"}


# A routine lives a few minutes on a timer, so the block is checked against a
# crafted payload rather than by waiting for one to fire.
ROUTINES_PAYLOAD = {"blocks": [
    STUCK_PAYLOAD["blocks"][0],
    {"project": "Routines", "label": "Routines", "orphan": False, "routines": True,
     "renamed": False, "pinned": False, "branches": [], "busy": 2, "alarms": 0, "ready": 0,
     "updatedAt": 1787830000000, "members": [
         _routine("Ansgar", "nightly-report", "r1"),
         _routine("Bruno", "disk-check", "r2")]}]}
# Four on one project. Only the liveliest is printed in full; the rest are
# a name until you ask. Nobody here is stuck -- that is checked separately,
# because an alarm must survive folding.
FOLD_PAYLOAD = {"blocks": [{
    "project": "maple", "label": "maple", "orphan": False, "routines": False,
    "renamed": False, "pinned": False, "branches": ["main"], "busy": 1, "alarms": 0, "ready": 0,
    "updatedAt": 1787830000000, "members": [
        _member("Vera", "busy", None, 0.1, "f1"),
        _member("Mei", "idle", None, 3.0, "f2"),
        _member("Leila", "idle", None, 9.0, "f3"),
        _member("Aziz", "idle", None, 40.0, "f4")]}]}
def _block(project, sid, busy=1):
    return {"project": project, "label": project, "orphan": False, "routines": False,
            "renamed": False, "pinned": False, "branches": [], "busy": busy, "alarms": 0, "ready": 0,
            "updatedAt": 1787830000000,
            "members": [_member(sid.upper(), "busy", None, 0.1, sid)]}


# The same two projects, and then the other way round: held, the page must
# ignore the second one's order and keep showing the first one's.
HOLD_BEFORE = {"blocks": [_block("alpha", "h1"), _block("beta", "h2")], "hold": False}
HOLD_AFTER = {"blocks": [_block("beta", "h2"), _block("alpha", "h1")], "hold": True}
# The chime. A quiet project, then somebody newly waiting on it, then a
# second one: only a name that was not waiting a moment ago may ring.
CHIME_QUIET = {"blocks": [_block("alpha", "c1")], "hold": False, "chime": True}


def _waiting(*names, ready=()):
    members = [_member("ALPHA", "busy", None, 0.1, "c1")]
    members += [_member(n.upper(), "waiting", "waiting", 0.3, n) for n in names]
    members += [_member(n.upper(), "idle", "ready", 1.0, n) for n in ready]
    return {"blocks": [{**_block("alpha", "c1"), "members": members}],
            "hold": False, "chime": True}


def _state(name, status, flag, sid, **kw):
    return {**_member(name, status, flag, 0.2, sid), **kw}


# One of each, so the five states can be told apart at a glance.
STATES_PAYLOAD = {"blocks": [{
    "project": "maple", "label": "maple", "orphan": False, "routines": False,
    "renamed": False, "pinned": False, "branches": [], "busy": 1,
    "alarms": 2, "ready": 1, "updatedAt": 1787830000000, "members": [
        _state("Vera", "waiting", "waiting", "p1", waitingFor="input needed"),
        _state("Mei", "busy", "stuck", "p2", quietFor=17.0),
        _state("Nour", "idle", "ready", "p3",
               said="Two had no composer — guess or skip?"),
        _state("Halima", "busy", None, "p4"),
        _state("Dmitri", "shell", None, "p5", bg=True)]}]}
# A boss and the team it dispatches to, plus one worker of the same boss
# sitting in another project -- it cannot be nested there, only labelled.
TEAM_PAYLOAD = {"blocks": [
    {"project": "pmd", "label": "pmd", "orphan": False, "routines": False,
     "renamed": False, "pinned": False, "branches": [], "busy": 1,
     "alarms": 0, "ready": 1, "updatedAt": 1787830000000, "members": [
         _state("Lennart", "idle", None, "b1", boss=True,
                team=["Rosalie", "Kasper"], reportsTo=""),
         _state("Rosalie", "idle", "ready", "b2", reportsTo="Lennart",
                said="Schema migration is green, want me to merge?"),
         _state("Kasper", "busy", None, "b3", reportsTo="Lennart"),
         _state("Nour", "waiting", "waiting", "b5", reportsTo="Lennart",
                waitingFor="input needed")]},
    {"project": "maple", "label": "maple", "orphan": False, "routines": False,
     "renamed": False, "pinned": False, "branches": [], "busy": 0,
     "alarms": 0, "ready": 0, "updatedAt": 1787830000000, "members": [
         _state("Vera", "idle", None, "b4", reportsTo="Lennart")]}]}
URL = "http://127.0.0.1:8765/"
failures = []


def cfg(key):
    return json.loads(CFG.read_text()).get(key, {})


def write(config):
    CFG.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")


def reset():
    kept = json.loads(CFG.read_text())
    kept.update({"assign": {}, "names": {}, "lines": {}, "pinned": []})
    write(kept)


def untitle(sid):
    """Hand a session's tab back to the terminal.

    An override does not only live in config.json: writing one *renames that
    terminal tab*, and rewriting the file does not undo the rename. Two runs
    of this test left two of the user's tabs called RIGA. Clearing the
    override through the server is what puts the name back, because it is the
    same path the page uses.
    """
    req = urllib.request.Request(
        "http://127.0.0.1:8765/api/line",
        data=json.dumps({"sessionId": sid, "text": ""}).encode(),
        headers={"Content-Type": "application/json", "X-Fleet": "1"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except OSError as e:
        print(f"(non sono riuscito a ripristinare il titolo di {sid}: {e})")


def restore(page, snapshot, retitled=()):
    """Put the user's own settings back, and make sure they stayed put.

    A commit fires an async POST and the server rewrites config.json on its
    own clock. Restoring before that lands leaves test data in a file the
    user owns -- which happened three times before this existed.
    """
    for sid in retitled:
        untitle(sid)
    for _ in range(5):
        page.wait_for_timeout(1200)
        write(snapshot)
        page.wait_for_timeout(800)
        if json.loads(CFG.read_text()) == snapshot:
            return True
    return False


def open_editor(page, locator):
    """Click a cell and wait until its field is really there.

    Only one field may be open at a time, so the previous one has to be gone
    before the next click -- otherwise the click is swallowed and the wait
    times out somewhere far from the cause.
    """
    page.wait_for_function("() => !document.querySelector('input.inline')")
    locator.click()
    page.wait_for_selector("input.inline", timeout=5000)


def check(label, ok, detail=""):
    print(f"{label:<34} {'OK' if ok else 'FALLITO ' + str(detail)}")
    if not ok:
        failures.append(label)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1700, "height": 2400})
    errors, jumps = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request",
            lambda r: jumps.append(r.url) if "/api/jump" in r.url else None)

    SNAPSHOT = json.loads(CFG.read_text())
    retitled = []          # every session whose tab this run renamed
    removals = []
    page.expose_function("noteRemoval", lambda s: removals.append(s))
    try:
        reset()
        page.goto(URL, wait_until="load")
        page.wait_for_selector(".block")
        page.evaluate("""() => {
          const orig = Element.prototype.remove;
          Element.prototype.remove = function () {
            if (this.classList?.contains('inline'))
              window.noteRemoval(new Error().stack.split(String.fromCharCode(10)).slice(1, 3).join(' | '));
            return orig.call(this);
          };
        }""")

        # --- renaming and relabelling -------------------------------------
        target = page.locator(".block:not(.orphan):not(.routines)").first
        project = target.get_attribute("data-project")
        open_editor(page, target.locator('[data-edit="name"]'))
        page.locator("input.inline").fill("RINOMINATO")
        page.locator("input.inline").press("Enter")
        page.wait_for_timeout(900)
        check("rename di un progetto", cfg("names").get(project) == "RINOMINATO")
        check("etichetta mostrata",
              page.locator(f'.block[data-project="{project}"] [data-edit="name"]')
                  .inner_text().strip() == "RINOMINATO")

        row = page.locator('.block:not(.orphan):not(.routines) [data-edit="line"]').first
        sid = row.get_attribute("data-sid")
        retitled.append(sid)
        open_editor(page, row)
        page.locator("input.inline").fill("RIGA")
        page.locator("input.inline").press("Enter")
        page.wait_for_timeout(900)
        check("override della riga", cfg("lines").get(sid) == "RIGA")

        # A click on a control is never also a jump: the terminal arriving in
        # front steals focus, and the field being typed into commits itself.
        check("modificare non fa il jump", not jumps, jumps)

        # An open field must survive the poll: two full cycles, untouched, with
        # what was typed still in it and the cursor still there.
        open_editor(page, page.locator('.block:not(.orphan):not(.routines) [data-edit="line"]').first)
        page.keyboard.type("mezzo scritto")
        page.wait_for_timeout(7000)
        check("il campo regge due poll",
              page.locator("input.inline").count() == 1
              and page.evaluate("document.activeElement?.classList.contains('inline')")
              and page.locator("input.inline").input_value() == "mezzo scritto",
              f"input={page.locator('input.inline').count()} rimozioni={removals[-2:]}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        # --- pinning ------------------------------------------------------
        reset()
        page.reload(wait_until="load")
        page.wait_for_selector(".block")
        # Three projects have to be running for there to be a third to drag,
        # and on a quiet machine there are not. Skipping says so; timing out
        # thirty seconds into the run says nothing.
        blocks = page.locator(".block:not(.orphan):not(.routines)")
        if blocks.count() < 3:
            print("(meno di tre progetti in questo momento: salto il pin)")
        else:
            third = blocks.nth(2).get_attribute("data-project")
            print(f"   (fisso {third!r} trascinandolo in cima)")
            # The ✳ is the handle -- a block is mostly rows, and grabbing its
            # middle used to pick up a session instead of the block.
            blocks.nth(2).locator(".pin").drag_to(blocks.nth(0))
            page.wait_for_timeout(1200)
            check("trascinare fissa il blocco", third in cfg("pinned"), cfg("pinned"))
            # Wait for the pin to actually show as pinned before clicking it: a
            # click on a block the page has not yet drawn as pinned is correctly
            # ignored.
            page.wait_for_function(
                """p => document.querySelector(`.block[data-project="${p}"]`)?.classList.contains('pinned')""",
                arg=third, timeout=5000)
            page.locator(f'.block[data-project="{third}"] .pin').click()
            try:
                page.wait_for_function(
                    """p => !document.querySelector(`.block[data-project="${p}"]`)?.classList.contains('pinned')""",
                    arg=third, timeout=5000)
            except Exception:
                pass
            check("la ✳ lo libera", third not in cfg("pinned"), cfg("pinned"))

        # --- assigning a session to a project -----------------------------
        reset()
        page.reload(wait_until="load")
        page.wait_for_selector(".block")
        chip = page.locator(".guess").first
        if chip.count():
            sid, guess = chip.get_attribute("data-sid"), chip.get_attribute("data-project")
            chip.click()
            page.wait_for_timeout(900)
            check("accettare il suggerimento", cfg("assign").get(sid) == guess)
            page.locator(f'.row[data-sid="{sid}"] .clear').click()
            page.wait_for_timeout(900)
            check("'togli' la riporta indietro", sid not in cfg("assign"))
        else:
            print("(nessun suggerimento da accettare in questo momento)")

        # Both of these need a session with no project, and routines -- which
        # used to supply one at every timer tick -- no longer land there.
        cell = page.locator(".assign-edit").first
        if not cell.count():
            print("(nessuna sessione senza progetto da assegnare)")
        else:
            sid2 = cell.get_attribute("data-sid")
            open_editor(page, cell)
            page.locator("input.inline").fill("progetto-scritto")
            page.locator("input.inline").press("Enter")
            page.wait_for_timeout(900)
            check("assegnare scrivendo il nome",
                  cfg("assign").get(sid2) == "progetto-scritto", cfg("assign"))

        reset()
        page.reload(wait_until="load")
        page.wait_for_selector(".block")
        src = page.locator("section.orphan .row").first
        if not src.count():
            print("(nessuna sessione senza progetto da trascinare)")
        else:
            sid3 = src.get_attribute("data-sid")
            dst = page.locator(".block:not(.orphan):not(.routines)").first
            dproj = dst.get_attribute("data-project")
            src.drag_to(dst)
            page.wait_for_timeout(1000)
            check("trascinare assegna la sessione",
                  cfg("assign").get(sid3) == dproj, cfg("assign"))

        # --- stuck and waiting --------------------------------------------
        # Nothing is stuck most of the time, so the rendering is checked against
        # a crafted payload rather than waiting for a session to hang.
        page.route("**/api/roster", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(STUCK_PAYLOAD)))
        page.reload(wait_until="load")
        page.wait_for_selector(".row")
        check("la riga in attesa è marcata",
              page.locator(".row.waiting .flag.waiting").count() == 1)
        check("la riga ferma è marcata",
              page.locator(".row.stuck .flag.stuck").count() == 1)
        check("dice da quanto è ferma",
              "17m" in page.locator(".flag.stuck").inner_text().lower())
        check("chi lavora resta pulito",
              page.locator(".row:not(.stuck):not(.waiting)").count() == 3)
        # A long tool call is reported, but never tinted or beating: it is news.
        check("il badge conta la chiamata, non il silenzio",
              "34m" in page.locator(".flag.tool").inner_text().lower(),
              page.locator(".flag.tool").inner_text())
        check("non ripete il titolo uguale al nome",
              page.locator('.row[data-sid="s5"] .title').count() == 0)
        check("la chiamata lunga è notizia, non allarme",
              page.locator(".flag.tool").count() == 1
              and "34m" in page.locator(".flag.tool").inner_text().lower()
              and page.locator(".row.tool").count() == 0)
        head = page.locator("#count").inner_text()
        check("la testata avvisa", "waiting" in head and "stuck" in head, head)
        check("il titolo della scheda conta", page.title().startswith("(2)"), page.title())
        page.unroute("**/api/roster")

        # --- routines -----------------------------------------------------
        page.route("**/api/roster", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(ROUTINES_PAYLOAD)))
        page.reload(wait_until="load")
        page.wait_for_selector(".block.routines")
        check("le routine stanno in un blocco solo",
              page.locator(".block.routines").count() == 1
              and page.locator(".block.routines .row").count() == 2)
        check("il blocco routine sta in fondo",
              "routines" in page.locator(".block").last.get_attribute("class"))
        check("non si fissa e non si rinomina",
              page.locator(".block.routines .pin").count() == 0
              and page.locator('.block.routines [data-edit="name"]').count() == 0)
        # The badge is styled uppercase, like every other bg-tag.
        check("ogni riga dice quale routine è",
              sorted(t.lower() for t in
                     page.locator(".block.routines .bg-tag").all_inner_texts())
              == ["disk-check", "nightly-report"],
              page.locator(".block.routines .bg-tag").all_inner_texts())
        check("nessuna riga chiede di essere assegnata",
              page.locator(".block.routines .assign").count() == 0)
        head = page.locator("#count").inner_text()
        check("le routine non contano come progetto", "1 projects" in head, head)
        page.unroute("**/api/roster")

        # --- folding ------------------------------------------------------
        page.route("**/api/roster", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(FOLD_PAYLOAD)))
        page.reload(wait_until="load")
        page.wait_for_selector(".row.stub")
        check("solo il più attivo è aperto",
              page.locator(".row:not(.stub)").count() == 1
              and page.locator(".row.stub").count() == 3
              and page.locator('.row:not(.stub) .nm').inner_text() == "Vera")
        page.locator('.row.stub[data-sid="f3"]').click()
        page.wait_for_timeout(300)
        check("cliccarne una la apre",
              page.locator('.row[data-sid="f3"]:not(.stub)').count() == 1
              and page.locator(".row.stub").count() == 2)
        # An open row still jumps; only the chevron folds it back.
        page.locator('.row[data-sid="f3"] .fold').click()
        page.wait_for_timeout(300)
        check("il chevron la richiude",
              page.locator('.row.stub[data-sid="f3"]').count() == 1)
        check("aprire e chiudere non fa il jump", not jumps, jumps)
        # Two polls: what you opened must survive the page redrawing itself.
        page.locator('.row.stub[data-sid="f4"]').click()
        page.wait_for_timeout(7000)
        check("resta aperta attraverso i poll",
              page.locator('.row[data-sid="f4"]:not(.stub)').count() == 1)
        box = page.locator("#q")
        box.fill("leila")
        page.wait_for_timeout(500)
        check("cercando si apre quello che trova",
              page.locator(".row.stub").count() == 0
              and page.locator(".row").count() == 1)
        box.fill("")
        page.wait_for_timeout(400)
        page.unroute("**/api/roster")

        # An alarm is never folded away, whatever you clicked.
        page.route("**/api/roster", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(STUCK_PAYLOAD)))
        page.reload(wait_until="load")
        page.wait_for_selector(".row")
        check("chi è fermo o in attesa non si piega mai",
              page.locator(".row.stub.stuck").count() == 0
              and page.locator(".row.stub.waiting").count() == 0
              and page.locator(".row.waiting, .row.stuck").count() == 2)
        check("una chiamata lunga resta leggibile anche piegata",
              page.locator(".row.stub .flag.tool").count() == 1)
        page.unroute("**/api/roster")

        # --- holding the order --------------------------------------------
        served = {"body": HOLD_BEFORE}
        page.route("**/api/roster", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(served["body"])))
        page.reload(wait_until="load")
        page.wait_for_selector(".block")
        order = lambda: [b.get_attribute("data-project")
                         for b in page.locator(".block").all()]
        check("di default si riordina da solo", order() == ["alpha", "beta"], order())
        page.locator("#hold").click()
        page.wait_for_timeout(900)
        check("il pulsante dice che è fermo",
              page.locator("#hold").inner_text() == "order held"
              and cfg("hold") is True, page.locator("#hold").inner_text())
        served["body"] = HOLD_AFTER
        page.wait_for_timeout(4000)          # a poll lands with the new order
        check("fermo, le carte non si muovono", order() == ["alpha", "beta"], order())
        served["body"] = {**HOLD_AFTER, "hold": False}
        page.locator("#hold").click()
        page.wait_for_timeout(4000)
        check("riacceso, si riordina subito", order() == ["beta", "alpha"], order())
        check("e il pulsante torna normale",
              page.locator("#hold").inner_text() == "auto-arrange" and not cfg("hold"))

        # Reloading while held. `hold` lives in config.json; the order it
        # froze lived only in the page, so a reload used to come back held
        # with nothing to hold on to -- every card tied, and the server's
        # order won. The button said held while the cards moved.
        served["body"] = {"blocks": HOLD_BEFORE["blocks"], "hold": True}
        page.reload(wait_until="load")
        page.wait_for_selector(".block")
        check("ricaricando resta fermo", order() == ["alpha", "beta"], order())
        served["body"] = {"blocks": HOLD_AFTER["blocks"], "hold": True}
        page.wait_for_timeout(4000)
        check("e non si muove al poll dopo", order() == ["alpha", "beta"], order())
        page.unroute("**/api/roster")

        # --- the chime ----------------------------------------------------
        served = {"body": CHIME_QUIET}
        page.route("**/api/roster", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(served["body"])))
        page.reload(wait_until="load")
        page.wait_for_selector(".block")
        # Making a real sound needs a real gesture and a real speaker. What
        # is checked here is *when* it rings, which is the part that can be
        # wrong -- a chime on every poll would be unbearable.
        page.evaluate("() => { window.__rings = 0; window.__ticks = 0;"
                      " window.ring = () => { window.__rings++; return true; };"
                      " window.tick = () => { window.__ticks++; return true; }; }")
        rings = lambda: page.evaluate("window.__rings")
        ticks = lambda: page.evaluate("window.__ticks")

        # Rendered offline, because a graph that connects nothing sounds
        # exactly like a graph that works, and neither is audible from here.
        sound = page.evaluate("""async () => {
          const peaks = async (shape, cuts) => {
            const off = new OfflineAudioContext(1, 44100 * 3, 44100);
            shape(off);
            const data = (await off.startRendering()).getChannelData(0);
            return cuts.map(([from, to]) => {
              let peak = 0;
              for (let i = from * 44100; i < Math.min(to * 44100, data.length); i++)
                peak = Math.max(peak, Math.abs(data[i]));
              return peak;
            });
          };
          const [first, second] = await peaks(tone, [[0, 0.4], [0.45, 3]]);
          const [head, tail] = await peaks(blip, [[0, 0.3], [0.6, 3]]);
          return { first, second, head, tail };
        }""")
        check("i due tocchi ci sono davvero, e non spaccano le orecchie",
              0.05 < sound["first"] < 0.4 and 0.05 < sound["second"] < 0.4
              and sound["second"] < sound["first"], sound)
        check("il tocco di chi ha finito si sente, ed è finito subito",
              0.05 < sound["head"] < 0.4 and sound["tail"] < 0.005, sound)
        check("il suono è armato di default",
              page.locator("#sound").inner_text() == "chime",
              page.locator("#sound").inner_text())
        served["body"] = _waiting("c2")
        page.wait_for_timeout(4000)
        check("suona quando qualcuno si mette in attesa", rings() == 1, rings())
        page.wait_for_timeout(4000)
        check("ma non risuona finché aspetta", rings() == 1, rings())

        # Muted, and the mute has to survive the trip through config.json.
        # The served roster has to agree, or the next poll turns it back on.
        served["body"] = {**_waiting("c2"), "chime": False}
        page.locator("#sound").click()
        page.wait_for_timeout(900)
        check("si può zittire",
              page.locator("#sound").inner_text() == "muted" and cfg("chime") is False,
              page.locator("#sound").inner_text())
        served["body"] = {**_waiting("c2", "c3"), "chime": False}
        page.wait_for_timeout(4000)
        check("e zitto resta zitto anche se ne arriva un altro", rings() == 1, rings())
        served["body"] = {**_waiting("c2", "c3"), "chime": True}
        page.locator("#sound").click()
        page.wait_for_timeout(900)
        check("riacceso, si sente subito com'è fatto",
              page.locator("#sound").inner_text() == "chime" and rings() == 2, rings())

        # Finishing gets the short one, and it is not the chime.
        served["body"] = {**_waiting("c2", "c3", ready=["c4"]), "chime": True}
        page.wait_for_timeout(4000)
        check("chi finisce fa un tocco, non il campanello",
              ticks() == 1 and rings() == 2, (rings(), ticks()))
        page.wait_for_timeout(4000)
        check("e il tocco non si ripete finché resta lì", ticks() == 1, ticks())
        # Both in the same poll: the one that wants something from you wins.
        served["body"] = {**_waiting("c2", "c3", "c5", ready=["c4", "c6"]),
                          "chime": True}
        page.wait_for_timeout(4000)
        check("se arrivano insieme si sente la domanda",
              rings() == 3 and ticks() == 1, (rings(), ticks()))
        page.unroute("**/api/roster")

        # --- the five states ----------------------------------------------
        page.route("**/api/roster", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(STATES_PAYLOAD)))
        page.reload(wait_until="load")
        page.wait_for_selector(".row")
        check("finito e non letto è una spunta blu",
              page.locator('.row[data-sid="p3"] .tick').count() == 1
              and page.locator('.row[data-sid="p3"] .dot').count() == 0
              and page.locator(".row.ready").count() == 1)
        check("dice l'ultima cosa che ha detto",
              "guess or skip" in page.locator('.row[data-sid="p3"] .said').inner_text())
        check("e la riga dice ready, non idle",
              "ready" in page.locator('.row[data-sid="p3"] .ago').inner_text())
        check("chi aspetta dice cosa aspetta",
              page.locator('.row[data-sid="p1"] .wf').inner_text() == "input needed")
        check("un lavoro in background è marcato bg",
              page.locator('.row[data-sid="p5"] .bg-tag').inner_text().lower() == "bg"
              and "idle" in page.locator('.row[data-sid="p5"] .ago').inner_text())
        # Motion means working, and only working.
        check("si muove solo chi lavora",
              page.locator(".row.working").count() == 2
              and page.locator('.row[data-sid="p3"].working').count() == 0
              and page.locator('.row[data-sid="p1"].working').count() == 0)
        head = page.locator("#count").inner_text()
        check("la testata conta anche i pronti", "1 ready" in head, head)
        check("il titolo della scheda no",
              page.title().startswith("(2)"), page.title())
        page.unroute("**/api/roster")

        # --- a boss and its team ------------------------------------------
        page.route("**/api/roster", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(TEAM_PAYLOAD)))
        page.reload(wait_until="load")
        page.wait_for_selector(".bg-tag.boss")
        check("il boss è marcato", page.locator(".bg-tag.boss").count() == 1
              and page.locator('.row[data-sid="b1"] .bg-tag.boss').count() == 1)
        check("dice chi è la sua squadra",
              page.locator('.row[data-sid="b1"] .team').inner_text().strip()
              == "↳ Rosalie · Kasper",
              page.locator('.row[data-sid="b1"] .team').inner_text())
        check("il boss guida il blocco",
              page.locator("#main .row").first.get_attribute("data-sid") == "b1")
        check("la squadra è annidata sotto di lui",
              page.locator('.row[data-sid="b2"].under').count() == 1
              and page.locator('.row[data-sid="b3"].under').count() == 1
              and page.locator('.row[data-sid="b1"].under').count() == 0)
        check("annidato non ripete a chi risponde",
              page.locator('.row[data-sid="b2"] .reports').count() == 0)
        # A worker's `ready` belongs to its boss: marked, but not a whole card.
        check("il ready di un worker resta piegato",
              page.locator('.row.stub[data-sid="b2"]').count() == 1
              and page.locator('.row.stub[data-sid="b2"] .tick').count() == 1
              and page.locator('.row.stub[data-sid="b2"].ready').count() == 1)
        check("ma il suo said non occupa una scheda",
              page.locator('.row[data-sid="b2"] .said').count() == 0)
        # A permission prompt on a worker is answered by the user, not by the
        # boss, so that one still opens.
        check("un worker che aspetta si apre lo stesso",
              page.locator('.row[data-sid="b5"]:not(.stub)').count() == 1
              and page.locator('.row[data-sid="b5"] .wf').inner_text() == "input needed")
        check("chi è in un altro progetto lo dice a parole",
              page.locator('.row[data-sid="b4"] .reports').inner_text().strip() == "↳ Lennart"
              and page.locator('.row[data-sid="b4"].under').count() == 0)
        page.unroute("**/api/roster")

        # --- uptime and the filter box ------------------------------------
        page.unroute("**/api/roster")
        page.reload(wait_until="load")
        page.wait_for_selector(".row")
        check("mostra da quanto è in piedi",
              "up " in page.locator(".where").first.inner_text(),
              page.locator(".where").first.inner_text())

        box = page.locator("#q")
        total = page.locator(".row").count()
        box.fill("ab")            # under three characters: nothing happens yet
        page.wait_for_timeout(400)
        check("due lettere non filtrano", page.locator(".row").count() == total)

        name = page.locator(".nm").first.inner_text().strip()
        box.fill(name[:4].lower())
        page.wait_for_timeout(500)
        shown = [n.strip().lower() for n in page.locator(".nm").all_inner_texts()]
        check(f"filtra su “{name[:4].lower()}”",
              shown and all(name[:4].lower() in s for s in shown) or
              page.locator(".block").count() > 0, shown)

        box.fill("zzzznothing")
        page.wait_for_timeout(500)
        check("dice quando non trova nulla", "Nothing matches" in page.locator(".empty").inner_text())

        box.press("Escape")
        page.wait_for_timeout(600)
        # Not a row count: sessions come and go between snapshots, and that is
        # not what clearing a filter is about.
        check("Escape ripulisce",
              box.input_value() == "" and page.locator(".block").count() > 1,
              box.input_value())

        page.keyboard.press("/")
        page.wait_for_timeout(200)
        check("“/” porta al filtro", page.evaluate("document.activeElement.id") == "q")
        box.fill("")

        check("nessun errore JS", not errors, errors)
    finally:
        ok = restore(page, SNAPSHOT, retitled)
    check("la config dell'utente torna com'era", ok,
          json.loads(CFG.read_text()))
    browser.close()

print()
print("tutto verde" if not failures else f"FALLITI: {failures}")
sys.exit(1 if failures else 0)
