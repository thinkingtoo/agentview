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

**Claimed by:** Habib 2026-11-11

**Status:** done

## Evidence

- **The boss's rule**, claude-boss 0.22.0 `skills/boss/objective.py:178`, which `boss-goal check` and `verify` count through `obj criteria`:

  ```python
  BOX_RE = re.compile(r"^- \[([ x])\] (.*)$")
  ```

  applied to each line of `## Done when` (`criteria`, line 181). agentview's `BOX` is now `^- \[([ x])\] `, the same line rule (the box text is the rest of the line in both). `* [x]`, `+ [ ]`, `[X]`, an indented box, `- [x]b`, `-  [ ]`, a tab and `- [x]` with nothing after are no box.
- **Kept on purpose, not the boss's:** the bold `**Done when:**` label and `## Done when ##` (ticket 23's reading), and a box inside a code fence is no box (pinned by `test_only_the_boxes_under_done_when_count_and_not_in_code`). Boxes inside an HTML comment are counted, as the boss counts them: the card's number is the boss's, though the sheaf page does not show those boxes.
- **Accepted differences from the boss's section rule** (code review, spec axis): `_section_span` takes only `^##\s+Done when\s*$`, case-sensitive, and ends at any `## ` line, a fenced one included. agentview's `section()` also takes `# `/`### Done when`, `## done when`, `## Done when:` and `## Done when ##`, and a fence hides a `## ` line. Where the boss reads no section at all, the card still shows the boxes; the line rule, which decides "n of m" inside one section, is the same. Not changed here: ticket 23 reads goal files leniently on purpose, and no real file differs.
- **Real files:** old and new rule compared on all 56 `~/.claude/pm/*.goal.md`: no line counts differently.
- **Red** (dev at 6e34b2f, run on t-compute), `tests/test_context.py` `test_a_box_is_what_the_boss_counts_as_one_and_nothing_else`:

  ```
  FAIL: test_a_box_is_what_the_boss_counts_as_one_and_nothing_else
  AssertionError: Tuples differ: (7, 11) != (2, 3)
  ```

- **Tests changed with the rule:** `[X] refund` became `[x] refund` in the order test; the "any style" test lost `* [X]` and the indented box and is now `test_only_the_boxes_under_done_when_count_and_not_in_code`. `pace.py` restarts its count when the total changes; no real file changes total.
- **Green:** same run as ticket 30, `Ran 185 tests ... OK (skipped=1)`. README says the rule.
