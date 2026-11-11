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

**Status:** needs-triage
