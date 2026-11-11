# 28: Pin the escaping of the goal url in "goal ↗"

**What to build:** a check in `goal_pass` (`tests/ui_smoke.py`) where `track.goal.url` starts with `http://127.0.0.1:` and carries a quote or markup, and the link's `href` reads back exactly as sent, with no attribute or element built from it. A mutation that drops `esc()` around `g.url` in `goalLinkOf` (`index.html`) must fail it. (Built as a node unittest, `tests/test_goal_href.py`, not in `goal_pass`: see Comments.)

**Found in:** Codex review 1 of PR #18 (Opus fallback, run by Tarek, 2026-11-11), class c. The url comes from the hub's port and sheaf's roots (`goal_page.py`), whose paths are `quote()`d, so the risk is low.

**Blocked by:** None.

**Claimed by:** Tarek 2026-11-11

**Status:** done

- [x] The check exists and fails with `esc()` dropped -- evidence: the mutation. `tests/test_goal_href.py`, green on origin/dev (ca36575), red with `esc()` dropped; both quoted below

## Comments

**Tarek 2026-11-11, where the check went and evidence.** Not in `goal_pass`: the boss classed the ticket c, with no browser. The check is a unittest, `tests/test_goal_href.py`, that runs the real `esc` and `goalLinkOf` from index.html in node (as `tests/test_announce_sound.py` runs `announce()`), on a page at 127.0.0.1, and parses the link with Python's `html.parser`: it must build one `<a>` and nothing else, with only its five attributes (class, href, target, rel, title), and its href must read back exactly as sent. Two urls, both starting `http://127.0.0.1:7417/goals/kettle.md`: one ending in `"><img src=x onerror=alert(1)> x="`, one carrying `&lt;` and `&quot;` as text (an unescaped `&` turns them into `<` and `"`). Run here (load 9.3 on 16 cores), PYTHONDONTWRITEBYTECODE=1, `tests/__pycache__` cleared before each run, index.html restored with `git checkout` and `git status` clean after.

Real code: `PYTHONPATH=tests python3 -m unittest -v tests.test_goal_href`

```
test_a_quote_or_markup_in_the_goal_url_stays_in_the_href_and_builds_nothing ... ok
Ran 1 test in 0.233s
OK
```

Mutation, `href="${esc(g.url)}"` -> `href="${g.url}"` in `goalLinkOf`: both urls fail.

```
- ['a', 'img']
+ ['a'] : [('a', {'class': 'ov-goal', 'href': 'http://127.0.0.1:7417/goals/kettle.md'}), ('img', {'src': 'x', 'onerror': 'alert(1)'})]
AssertionError: 'http://127.0.0.1:7417/goals/kettle.md?a=1<b"c' != 'http://127.0.0.1:7417/goals/kettle.md?a=1&lt;b&quot;c'
Ran 1 test in 0.253s
FAILED (failures=2)
```
