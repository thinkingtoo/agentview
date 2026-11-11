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

**Status:** done

**Claimed by:** Habib 2026-11-11

## Evidence

- **Decision:** both halves of "give a timeout its own reason, or keep the last known answer". `_run` returns `TIMED_OUT` (124, timeout(1)'s code) for `subprocess.TimeoutExpired`; `_refresh` then keeps the port found last, and with none found says `SLOW`: "sheaf took more than 10 s to say whether its hub runs: asked again in 30 s". `at` is still set, so a slow sheaf is asked once every `STATUS_EVERY`, not on every poll. Other `SubprocessError`s stay NO_HUB.
- **Red** (dev at 6e34b2f, run on t-compute), a real script sleeping 5 s run by `_run` with `TIMEOUT` 0.3:

  ```
  FAIL: test_a_sheaf_too_slow_to_answer_keeps_the_hub_it_found_last
  AssertionError: {'url': None, 'why': 'no sheaf hub runs: start one with `sheaf start`'} != {'url': 'http://127.0.0.1:27419/claude/pm/checkout.goal.md', 'why': ''}
  ERROR: test_a_sheaf_too_slow_to_answer_is_said_as_slow_and_not_as_no_hub
  AttributeError: module 'goal_page' has no attribute 'SLOW'
  ```

- **Green:** same run as ticket 30, `Ran 185 tests ... OK (skipped=1)`. README says it in the goal link paragraph.
