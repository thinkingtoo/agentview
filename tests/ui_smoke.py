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
URL = "http://127.0.0.1:8765/"
failures = []


def cfg(key):
    return json.loads(CFG.read_text()).get(key, {})


def reset():
    kept = json.loads(CFG.read_text())
    kept.update({"assign": {}, "names": {}, "lines": {}, "pinned": []})
    CFG.write_text(json.dumps(kept, indent=2, ensure_ascii=False) + "\n")


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
    target.locator('[data-edit="name"]').click()
    page.locator("input.inline").fill("RINOMINATO")
    page.locator("input.inline").press("Enter")
    page.wait_for_timeout(900)
    check("rename di un progetto", cfg("names").get(project) == "RINOMINATO")
    check("etichetta mostrata",
          page.locator(f'.block[data-project="{project}"] [data-edit="name"]')
              .inner_text().strip() == "RINOMINATO")

    row = page.locator('.block:not(.orphan) [data-edit="line"]').first
    sid = row.get_attribute("data-sid")
    row.click()
    page.locator("input.inline").fill("RIGA")
    page.locator("input.inline").press("Enter")
    page.wait_for_timeout(900)
    check("override della riga", cfg("lines").get(sid) == "RIGA")

    # A click on a control is never also a jump: the terminal arriving in
    # front steals focus, and the field being typed into commits itself.
    check("modificare non fa il jump", not jumps, jumps)

    # An open field must survive the poll.
    page.locator('.block:not(.orphan) [data-edit="line"]').first.click()
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
    cell.click()
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

    check("nessun errore JS", not errors, errors)
    reset()
    browser.close()

print()
print("tutto verde" if not failures else f"FALLITI: {failures}")
sys.exit(1 if failures else 0)
