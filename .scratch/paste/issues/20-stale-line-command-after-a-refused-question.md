# 20: The answered-question check does not cover a turn that ends on the old line

**What to decide, then pin:** `guessed_commands_of` drops a line older than the last answer only under an open question (source `"question"`). paste/13 left source `"line"` unchanged on purpose. No test pins that choice, and it offers a stale command in two real cases:

1. The session writes `team-line --n 1 --ask 'Type this here: $ bash push.sh'`, opens Q1, the person rejects Q1 with Esc. A rejected question gets no Stop hook, so the line stays; the turn ends idle, source `"line"`, `guessedCommands == ['bash push.sh']` for a refused question.
2. Q1 is answered and the turn ends without a new line.

Either extend the `lineAt <= answeredAt` check to source `"line"`, or add a test that pins today's behaviour as intended.

**Failing lines:** `fleet.py:1294-1296`:

```python
    if (stuck["source"] == "question" and m["answeredAt"]
            and (m["lineAt"] or 0) <= m["answeredAt"]):
        return []
```

**Class:** c (traced, not run on a live session).

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Status:** needs-triage
