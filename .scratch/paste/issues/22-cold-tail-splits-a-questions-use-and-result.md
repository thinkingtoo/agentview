# 22: The cold-start tail can cut a question's tool_use from its answer

**What to fix (or pin as accepted):** on first sight of a transcript over `COLD_BYTES` (2 MB), e.g. after an agentview restart, only the tail is absorbed. If Q1's AskUserQuestion `tool_use` lies before the cut and its `tool_result` after, `state["uses"]` has no Q1, the answer is not counted, `answeredAt` stays None, and Q2's card offers Q1's command (paste/13 undone for that session).

**Input:** a transcript over 2 MB whose cut point falls between Q1's `tool_use` and `tool_result` records, read cold. The two are written next to each other, so this is rare.

**Failing lines:** `providers/base.py:313-316`:

```python
        if state["offset"] == 0 and stat.st_size > COLD_BYTES:
            # First sight of a large file. Every value is a *latest* one, so
            # the tail answers them; what it cannot, `cold` reads once.
            text, offset = read_from(path, stat.st_size - COLD_BYTES)
```

**Class:** c (traced; no test covers it).

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Status:** needs-triage
