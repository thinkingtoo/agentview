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

from playwright.sync_api import sync_playwright

CFG = pathlib.Path(__file__).resolve().parent.parent / "config.json"


def _member(name, status, stuck, quiet, sid):
    return {"name": name, "status": status, "kind": "interactive",
            "cwd": "/home/alice/Projects/maple", "tmux": "", "pid": 111,
            "sessionId": sid, "updatedAt": 1787830000000, "project": "maple",
            "title": f"{name} at work", "prompt": "carry on", "branch": "main",
            "canJump": True, "assigned": False, "suggestion": None,
            "quietFor": quiet, "stuck": stuck}


STUCK_PAYLOAD = {"blocks": [{
    "project": "maple", "label": "maple", "orphan": False, "renamed": False,
    "pinned": False, "branches": ["main"], "busy": 1, "stuck": 2,
    "updatedAt": 1787830000000, "members": [
        _member("Vera", "waiting", "waiting", 0.3, "s1"),
        _member("Mei", "busy", "stuck", 17.0, "s2"),
        _member("Leila", "busy", None, 0.1, "s3")]}]}
URL = "http://127.0.0.1:8765/"
failures = []


def cfg(key):
    return json.loads(CFG.read_text()).get(key, {})


def reset():
    kept = json.loads(CFG.read_text())
    kept.update({"assign": {}, "names": {}, "lines": {}, "pinned": []})
    CFG.write_text(json.dumps(kept, indent=2, ensure_ascii=False) + "\n")


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

    reset()
    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector(".block")

    # --- renaming and relabelling -------------------------------------
    target = page.locator(".block:not(.orphan)").first
    project = target.get_attribute("data-project")
    open_editor(page, target.locator('[data-edit="name"]'))
    page.locator("input.inline").fill("RINOMINATO")
    page.locator("input.inline").press("Enter")
    page.wait_for_timeout(900)
    check("rename di un progetto", cfg("names").get(project) == "RINOMINATO")
    check("etichetta mostrata",
          page.locator(f'.block[data-project="{project}"] [data-edit="name"]')
              .inner_text().strip() == "RINOMINATO")

    row = page.locator('.block:not(.orphan) [data-edit="line"]').first
    sid = row.get_attribute("data-sid")
    open_editor(page, row)
    page.locator("input.inline").fill("RIGA")
    page.locator("input.inline").press("Enter")
    page.wait_for_timeout(900)
    check("override della riga", cfg("lines").get(sid) == "RIGA")

    # A click on a control is never also a jump: the terminal arriving in
    # front steals focus, and the field being typed into commits itself.
    check("modificare non fa il jump", not jumps, jumps)

    # An open field must survive the poll.
    open_editor(page, page.locator('.block:not(.orphan) [data-edit="line"]').first)
    for ch in "lento":
        page.locator("input.inline").type(ch, delay=0)
        page.wait_for_timeout(700)
    check("il campo regge il poll", page.locator("input.inline").count() == 1)
    page.locator("input.inline").press("Escape")
    page.wait_for_timeout(400)

    # --- pinning ------------------------------------------------------
    reset()
    page.reload(wait_until="networkidle")
    page.wait_for_selector(".block")
    blocks = page.locator(".block:not(.orphan)")
    third = blocks.nth(2).get_attribute("data-project")
    # The ✳ is the handle -- a block is mostly rows, and grabbing its middle
    # used to pick up a session instead of the block.
    blocks.nth(2).locator(".pin").drag_to(blocks.nth(0))
    page.wait_for_timeout(900)
    check("trascinare fissa il blocco", third in cfg("pinned"), cfg("pinned"))
    page.locator(f'.block[data-project="{third}"] .pin').click()
    page.wait_for_timeout(900)
    check("la ✳ lo libera", third not in cfg("pinned"), cfg("pinned"))

    # --- assigning a session to a project -----------------------------
    reset()
    page.reload(wait_until="networkidle")
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

    cell = page.locator(".assign-edit").first
    sid2 = cell.get_attribute("data-sid")
    open_editor(page, cell)
    page.locator("input.inline").fill("progetto-scritto")
    page.locator("input.inline").press("Enter")
    page.wait_for_timeout(900)
    check("assegnare scrivendo il nome",
          cfg("assign").get(sid2) == "progetto-scritto", cfg("assign"))

    reset()
    page.reload(wait_until="networkidle")
    page.wait_for_selector("section.orphan .row")
    src = page.locator("section.orphan .row").first
    sid3 = src.get_attribute("data-sid")
    dst = page.locator(".block:not(.orphan)").first
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
    page.reload(wait_until="networkidle")
    page.wait_for_selector(".row")
    check("la riga in attesa è marcata",
          page.locator(".row.waiting .flag.waiting").count() == 1)
    check("la riga ferma è marcata",
          page.locator(".row.stuck .flag.stuck").count() == 1)
    check("dice da quanto è ferma",
          "17m" in page.locator(".flag.stuck").inner_text().lower())
    check("chi lavora resta pulito",
          page.locator(".row:not(.stuck):not(.waiting)").count() == 1)
    head = page.locator("#count").inner_text()
    check("la testata avvisa", "waiting for you" in head and "stuck" in head, head)
    check("il titolo della scheda conta", page.title().startswith("(2)"), page.title())
    page.unroute("**/api/roster")

    # --- uptime and the filter box ------------------------------------
    page.unroute("**/api/roster")
    page.reload(wait_until="networkidle")
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
    page.wait_for_timeout(500)
    check("Escape ripulisce", page.locator(".row").count() == total)

    page.keyboard.press("/")
    page.wait_for_timeout(200)
    check("“/” porta al filtro", page.evaluate("document.activeElement.id") == "q")
    box.fill("")

    check("nessun errore JS", not errors, errors)
    # A commit fires an async POST; the server merges and rewrites config.json
    # on its own clock. Resetting without waiting lets that write land after
    # the reset and leave test data behind.
    page.wait_for_timeout(1200)
    reset()
    browser.close()

print()
print("tutto verde" if not failures else f"FALLITI: {failures}")
sys.exit(1 if failures else 0)
