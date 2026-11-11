# 32: The card counts Done when boxes the boss does not

**What to fix:** `BOX` counts `[X]`, `*`/`+` bullets, indented sub-boxes and a box with no space after it; claude-boss `objective.criteria` reads `^- \[([ x])\] (.*)$`. The card's "n of m" then differs from the boss's. Align on one rule (and decide boxes inside an HTML comment, which both count and the sheaf page does not show).

**Input:** `## Done when\n- [x]b\n- [ ] c\n` — the card says 1 of 2, the boss 0 of 1. Probed: `BOX.match('- [x]b')` is True.

**Failing line:** `context.py:86`:

```python
BOX = re.compile(r"^\s*[-*+]\s+\[([ xX])\]")
```

No real `~/.claude/pm/*.goal.md` shows a difference today apart from the bold `**Done when:**` label, which agentview reads on purpose.

**Class:** b.

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Status:** needs-triage
