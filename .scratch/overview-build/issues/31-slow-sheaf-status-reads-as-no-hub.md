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

**Claimed by:** Habib 2026-11-11

**Status:** done

## Evidence

- **Decision:** both halves of "give a timeout its own reason, or keep the last known answer". `_run` returns `TIMED_OUT` (124, timeout(1)'s code) for `subprocess.TimeoutExpired`; `_refresh` then keeps the port found last for one look (a second timeout in a row drops it, so a hub that died is not linked for ever), and with none says `SLOW`: "sheaf took more than 10 s to say whether its hub runs: asked again in 30 s". `at` is still set, so a slow sheaf is asked once every `STATUS_EVERY`, not on every poll. Other `SubprocessError`s stay NO_HUB.
- **Red** (dev at 6e34b2f, run on t-compute), a real script sleeping 5 s run by `_run` with `TIMEOUT` 0.3:

  ```
  FAIL: test_a_sheaf_too_slow_to_answer_keeps_the_hub_it_found_last
  AssertionError: {'url': None, 'why': 'no sheaf hub runs: start one with `sheaf start`'} != {'url': 'http://127.0.0.1:27419/claude/pm/checkout.goal.md', 'why': ''}
  ERROR: test_a_sheaf_too_slow_to_answer_is_said_as_slow_and_not_as_no_hub
  AttributeError: module 'goal_page' has no attribute 'SLOW'
  ```

- **Green:** same run as ticket 30, `Ran 185 tests ... OK (skipped=1)`. README says it in the goal link paragraph.
- **Bug hunt round 1 (Opus), class b, fixed:** sheaf's own health check gives up on its hub after 3 s (`hub/client.py:43` `TIMEOUT = 3.0`), long before agentview's 10 s. `cmd_status` then exits 1 with stdout empty (`cli.py:433`, `return _hub_failure(e)`, the message on stderr); only a hub that is really not there prints `  no hub is running` (`cli.py:435`). Read in the installed sheafmd. That case was still said as NO_HUB. Now an exit 1 without that line is handled like a timeout: the hub found last is kept for one look, else `UNSURE` ("sheaf could not tell whether its hub runs ..."). Red, `test_a_hub_that_does_not_answer_sheaf_in_time_is_not_said_as_no_hub`, run on t-compute before the fix:

  ```
  ERROR: test_a_hub_that_does_not_answer_sheaf_in_time_is_not_said_as_no_hub
  AttributeError: module 'goal_page' has no attribute 'UNSURE'
  ```

  With the fix and the new condition removed again (mutation): `AssertionError: {'url': None, 'why': 'no sheaf hub runs: start one with `sheaf start`'} != {'url': None, 'why': 'sheaf could not tell whether its hub runs[48 chars]0 s'}`. Green with the fix: `tests.test_goal_page tests.test_context tests.test_goal_href`, `Ran 186 tests ... OK (skipped=1)`.
- **Left, class c, from the same hunt:** "one look" is one refresh, and a goal newly asked for starts one at once, so a kept link can go a few seconds after a timeout instead of `STATUS_EVERY` later (and the "asked again in 30 s" is then early). `TIMED_OUT = 124` would misread a sheaf that ever exits 124 (sheaf 1.0.3 exits 0, 1 or 2 only). Neither is wrong today on a single card.
- **Bug hunt round 2 (Opus), class b, fixed:** round 1's fix read every exit 1 without "no hub is running" as a busy hub, so a stranger on the hub's port (sheaf's plain `Impostor`, "something else holds 127.0.0.1:PORT, not your sheaf hub"), a config error (`main`'s `ConfigError`) or a traceback kept the old link for one look and said "too busy". Now `_run` reads stderr: only sheaf's `HubSilent`/`HubHungUp` texts ("the sheaf hub on 127.0.0.1:PORT did not answer", "... proved itself and then ended") give `SILENT`, which keeps the last hub for one look, else `UNSURE`. "No hub" is said only when sheaf prints `no hub is running`; any other failure, an exit 0 that `RUNNING` cannot read included, is `FAILED` ("`sheaf status` failed: run it to see why") and drops the link. Texts read in the installed sheafmd 1.0.3 (`hub/client.py` `Impostor`, `HubSilent`, `HubHungUp`; `cli.py` `_hub_failure`, `main`); a sandboxed real `sheaf status` (own `SHEAF_HOME`, free port) printed `  no hub is running` on stdout, and with `SHEAF_PORT=x` exit 1, stdout empty, stderr `sheaf: SHEAF_PORT='x' is not a port number`. Red, before the fix (t-compute):

  ```
  ERROR: test_a_status_that_fails_otherwise_drops_the_link_and_is_not_said_as_no_hub (err='  ! something else holds 127.0.0.1:27419, not your sheaf hub')
  AttributeError: module 'goal_page' has no attribute 'FAILED'
  ERROR: test_a_status_that_says_neither_way_is_not_said_as_no_hub
  AttributeError: module 'goal_page' has no attribute 'FAILED'
  ```

  Green: `Ran 189 tests ... OK (skipped=1)`. Mutations: dropping the stderr check fails the two silent-hub tests; saying NO_HUB for any failure fails the two FAILED tests.

