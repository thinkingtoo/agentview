import json, pathlib, sys
from playwright.sync_api import sync_playwright

CFG = pathlib.Path("/home/alice/Projects/claude-team/config.json")
errors = []

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1600, "height": 1000})
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8765/", wait_until="networkidle")
    page.wait_for_selector(".block")

    # 1. rename a project by double-clicking its name
    target = page.locator('.block:not(.orphan)').first
    project = target.get_attribute("data-project")
    target.locator('[data-edit="name"]').click()
    page.locator("input.inline").fill("RINOMINATO-TEST")
    page.locator("input.inline").press("Enter")
    page.wait_for_timeout(900)
    names = json.loads(CFG.read_text()).get("names", {})
    print("1. rename  :", "OK" if names.get(project) == "RINOMINATO-TEST"
          else f"FALLITO ({names.get(project)!r})")

    # 2. the page shows the new label
    page.wait_for_timeout(400)
    shown = page.locator(f'.block[data-project="{project}"] [data-edit="name"]').inner_text()
    print("2. mostrato:", "OK" if shown.strip() == "RINOMINATO-TEST" else f"FALLITO ({shown!r})")

    # 3. override a session line
    row = page.locator('.block:not(.orphan) [data-edit="line"]').first
    sid = row.get_attribute("data-sid")
    row.click()
    page.locator("input.inline").fill("RIGA-TEST")
    page.locator("input.inline").press("Enter")
    page.wait_for_timeout(900)
    lines = json.loads(CFG.read_text()).get("lines", {})
    print("3. riga    :", "OK" if lines.get(sid) == "RIGA-TEST" else f"FALLITO ({lines.get(sid)!r})")

    # 4. drag the third block onto the first
    blocks = page.locator(".block:not(.orphan)")
    third = blocks.nth(2).get_attribute("data-project")
    blocks.nth(2).drag_to(blocks.nth(0))
    page.wait_for_timeout(900)
    pinned = json.loads(CFG.read_text()).get("pinned", [])
    print("4. drag    :", "OK" if third in pinned else f"FALLITO (pinned={pinned})")

    # 5. unpin by clicking the mark
    page.locator(f'.block[data-project="{third}"] .pin').click()
    page.wait_for_timeout(900)
    pinned2 = json.loads(CFG.read_text()).get("pinned", [])
    print("5. unpin   :", "OK" if third not in pinned2 else f"FALLITO (pinned={pinned2})")

    # An edit must never also fire a jump: the terminal coming to the front
    # steals focus, the input blurs, and the edit commits behind your back.
    jumps = []
    page.on("request", lambda r: jumps.append(r.url) if "/api/jump" in r.url else None)
    page.reload(wait_until="networkidle")
    page.wait_for_selector(".block")
    page.locator('.block:not(.orphan) [data-edit="line"]').first.click()
    page.wait_for_timeout(300)
    print("6. clic apre, non salta:",
          "OK" if page.locator("input.inline").count() == 1 and not jumps else "FALLITO")
    for ch in "lento":
        page.locator("input.inline").type(ch, delay=0)
        page.wait_for_timeout(700)
    print("7. regge il poll       :",
          "OK" if page.locator("input.inline").count() == 1 else "FALLITO")
    page.locator("input.inline").press("Escape")
    page.wait_for_timeout(500)

    print("8. errori JS:", errors or "nessuno")
    b.close()
