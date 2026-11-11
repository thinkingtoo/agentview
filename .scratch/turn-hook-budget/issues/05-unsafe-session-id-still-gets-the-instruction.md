# 05: An unsafe session id still gets the instruction, unquoted

**What to fix:** `begin()` in `hooks/turn_line.py` returns `{}` when the id fails `lines.SAFE`, the way `begin_turn` already refuses it.

**Input:** a UserPromptSubmit payload `{"session_id": "a b; touch X"}` (or `5`, or `["x"]`).

**Failing line:** `hooks/turn_line.py:67-72`:

```python
    if not sid:
        return {}
    lines.begin_turn(sid, root)
    return {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": ASK.format(writer=WRITER, paste=PASTE, sid=sid)}}
```

The context then reads `.../team-line a b; touch X --did '...'`; a session following it runs `touch X --did ...`. Probed: `'touch X --did' in additionalContext` is True while `lines.SAFE.match(sid)` is False.

**Class:** b (Claude Code sends UUIDs). Predates the track.

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Status:** needs-triage
