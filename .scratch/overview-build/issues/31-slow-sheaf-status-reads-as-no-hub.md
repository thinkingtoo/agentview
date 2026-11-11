# 31: A slow sheaf status is reported as "no hub"

**What to fix:** `_run` turns a timeout (`TIMEOUT = 10` s, `subprocess.TimeoutExpired` is a `SubprocessError`) into `(1, "")`, and `_refresh` then says `NO_HUB` ("no sheaf hub runs: start one with `sheaf start`") while a hub runs, for `STATUS_EVERY` (30 s). Give a timeout its own reason, or keep the last known answer.

**Input:** `sheaf status` taking more than 10 s on a loaded laptop (load sat at 17 during this hunt).

**Failing lines:** `goal_page.py:74-75`:

```python
    except subprocess.SubprocessError:
        return 1, ""
```

and `goal_page.py:132` `why=NO_SHEAF if code == MISSING else NO_HUB)`.

**Class:** b (traced).

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Status:** needs-triage
