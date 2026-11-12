# 25: A failed read-back in paste_engine_pass crashes the smoke instead of failing a check

**What to fix:** when the Paste does not land in the textarea, `wait_for_function` raises a TimeoutError. It propagates out of `main`, so the run dies with a traceback before the final checks ("no routed request carried a real session key", "no JS errors…", "the test config was only read"). The run is still red (exit 1), but no named check fails and the guards at the end never run. Catch the timeout and turn it into a `check(f"{name}: …", False, …)`.

**Input:** WebKit or Firefox, a copy that does not reach the clipboard (a refused write, or a mutation that breaks the copy): Control+V leaves `#readback` empty.

**Failing lines:** `tests/ui_smoke.py:1808` at 7dc96ed:

```python
    page.wait_for_function("document.getElementById('readback').value !== ''")
```

called from `tests/ui_smoke.py:3115-3118` (`for engine in (pw.webkit, pw.firefox): … paste_engine_pass(other)`), ahead of the closing checks at 3122-3125.

**Class:** c. Introduced by paste/18 (PR 29).

**Found in:** PR 29 hunt (Samir, Opus), 2026-11-11. Read from the code; ui_smoke was not run.

**Blocked by:** None.

## Evidence

**Ferran, 2026-11-12.** Fixed in `paste_engine_pass`: both waits (the button, the read-back) take a 5 s timeout and turn `TimeoutError` into a failed named check, so the closing guards run. Run on t-compute (Firefox 159, WPE WebKit from Playwright 1.65.1, a private venv), `PYTHONPATH` the clone's `tests/`, `TMPDIR` beside it. Mutation: `copyFetched` returns `false` at once.

Before (origin/dev's `ui_smoke.py`): `playwright._impl._errors.TimeoutError: Page.wait_for_function: Timeout 30000ms exceeded.`, a traceback, exit 1, no check named.

After:

```
firefox: the button says it copied                         FAILED not copied
firefox: copy puts the whole text on the clipboard, byte-order mark included FAILED nothing reached the clipboard
firefox: and the copy went by the selection, written inside the tap: [] FAILED ([], [])
firefox: and told the server                               FAILED []
no JS errors, console errors or dialogs anywhere           OK
```

WebKit gives the same four, then the closing guard runs and the run ends `FAILED: [...]`, exit 1.

**Status:** done
