# 30: One bad entry in sheaf's roots.json hides every goal link

**What to fix:** `_roots()` promises "[] when ... it is not what sheaf writes", but `os.path.realpath` inside its list comprehension raises on a path holding a NUL, outside the `try`. The error reaches `_refresh`'s catch-all, which marks every wanted goal `UNREADABLE` with no path. Skip the one entry instead.

**Input:** `roots.json` = `{"x": {"path": "/a\u0000b", "git": true}}` next to valid roots. Probed: `os.path.realpath('/a\x00b')` raises `ValueError: lstat: embedded null character in path`.

**Failing line:** `goal_page.py:89`:

```python
    return [(name, Path(os.path.realpath(r["path"])), r.get("git") is True) for name, r in got.items()
```

then `goal_page.py:134` `except Exception:` sets `why=UNREADABLE` for all goals.

**Class:** b.

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Claimed by:** Habib 2026-11-11

**Status:** done

## Evidence

- **Red** (dev at 6e34b2f, run on t-compute): `tests/test_goal_page.py` `test_a_root_whose_path_no_file_can_have_is_skipped_and_the_others_still_give_pages` registers `claude` (the goal's git root) beside `odd` at `/a\x00b`:

  ```
  FAIL: test_a_root_whose_path_no_file_can_have_is_skipped_and_the_others_still_give_pages
  AssertionError: None != 'http://127.0.0.1:27419/claude/pm/checkout.goal.md'
  ```

- **Fix:** `goal_page._roots` resolves each root in its own `try`; a `ValueError` from `os.path.realpath` drops that entry only. The docstring says so.
- **Green:** `python3 -m unittest tests.test_goal_page tests.test_context tests.test_goal_href` on t-compute: `Ran 185 tests ... OK (skipped=1)` (the skip is the node-only href test, node is not on t-compute).
