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

**Status:** needs-triage
