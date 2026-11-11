# 34: The page test's "folded" check never asks for the `on` class to be absent

**What to fix:** in `goal_pass` (`tests/ui_smoke.py`), `unfolded(project)` requires the `on` class on the card's "N of M" button, but `folded(project)` checks only `aria-expanded="false"` and that no `.ov-boxes` is shown. The only check for a missing `on` runs once, on the first card before any click (`tests/ui_smoke.py:1281`). So a page that lights every card's "N of M" once one card is unfolded passes the whole pass. Add `"on" not in one(col(project).locator(".ov-count")).get("cls", "on").split()` to `folded`, and pin it with the mutation below.

**Input:** a mutation of `index.html:839`, `class="ov-count ${BOXES.has(c.project) ? "on" : ""}"` changed to `class="ov-count ${BOXES.size ? "on" : ""}"`. Traced through the checks at 1281, 1291, 1302, 1304 and 1308 at bd76240: all stay green.

**Failing lines (bd76240):** `tests/ui_smoke.py:1274-1275`:

```python
    folded = lambda project: one(col(project).locator(".ov-count")).get("expanded") == "false" \
        and col(project).locator(".ov-boxes").count() == 0
```

**Class:** b (a check weaker than its name: "unfolding unfolds that card only" does not see the other cards' highlight).

**Found in:** Codex review 2 of PR #18 (Opus fallback, run by Yasmin at close-out, 2026-11-11), over ca4d8dd..bd76240. Citations verified at bd76240. Report: `agentview-wt/Yasmin-reviews/bughunt-18-2-opus.md`.

**Blocked by:** None.

**Status:** done

**Claimed by:** Samir 2026-11-11

- [x] The mutation `BOXES.size ? "on"` at `index.html:839` fails a named check -- evidence: the mutation and its output

## Evidence

**Samir, 2026-11-11.** Fixed as the ticket says: `folded` also requires `on` to be absent from the card's "N of M" class (a missing button counts as `on`, so it fails). `goal_pass` alone, `PYTHONDONTWRITEBYTECODE=1`, index.html restored and its hash checked after the mutation.

Red, the mutation `BOXES.has(c.project) ? "on"` -> `BOXES.size ? "on"` before the fix (load 13.4):

```
unfolding unfolds that card only                           OK
another card's N of M unfolds that card, and leaves the first as it was OK
all green
```

The same mutation after the fix (load 10.8):

```
unfolding unfolds that card only                           FAILED
another card's N of M unfolds that card, and leaves the first as it was FAILED ['☑ The cups are warm', '☐ The tray is dry']
FAILED: ['unfolding unfolds that card only', "another card's N of M unfolds that card, and leaves the first as it was"]
```

Green on the real page, `goal_pass`, `paste_pass` and `paste_stay_pass` in one run (load 10.6): all green, no page or console error.
