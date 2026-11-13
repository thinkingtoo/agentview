# 27: A sheaf comment on a goal's heading hides every Done when box

**Status:** diagnosed, fix not built (Tarek asked for the findings first)

**What happened (2026-11-13, found by the boss of a client track):** Thierry commented on the words "Done when" of a goal page. Sheaf wrote the comment block into the heading line, and `boss-goal` then found 0 criteria. The boss moved the block onto its own line by hand; claude-boss ticket 47 covers `boss-goal`.

## (1) Does agentview lose the rows too? Yes.

`context.track_card` reads the boxes from `section(lines, "done when")`; `section` finds the heading by `heading_text(...)` equal to the title, so a heading that carries a comment block is no longer called "done when". The rows of the card come from those boxes (`objectives.rows(track["boxes"], …)`), so no boxes means no "n of m" and no rows.

Fixture (`context.track_card` on a goal with one ticked box of three; the block is a real one, as sheaf writes it):

| Heading line | progress | boxes |
| --- | --- | --- |
| `## Done when` | 1 of 3 | 3 |
| `## Done when<!-- sheaf-comment … -->` | none | 0 |
| `## Done<!-- sheaf-comment … quote="Done" --> when` (what sheaf wrote) | none | 0 |
| `## Done when` then the block on its own line | 1 of 3 | 3 |
| `## Done when` then the block on its own line, `when` left after it | 1 of 3 | 3 |

So agentview loses every row in the same two cases as `boss-goal`.

## (3) Why a comment lands on the heading line (sheaf `origin/main`, read only)

- `comments.add_comment` puts the block **right after the selected text**: `anchor_point(b.content, start, end, quote)` returns the offset where the selection ends, and `pos = block offset + that`. Thierry selected the word "Done", so the block went after "Done", **inside** the heading: `## Done<!-- sheaf-comment … quote="Done" --> when`. That is why the live file had `quote="Done"` and, after the boss's repair, a stray ` when` after the block's closing `-->` (line 7 of the goal file still ends `--> when`).
- For a `heading` (and `table`) block, `format(c, one_line=True)` writes the whole comment on one line joined by `<br>`: `ONE_LINE_KINDS = {"heading", "table"}`. The module says why: in a heading or table cell a newline ends the block, so the comment cannot take its own lines as in a paragraph.
- Nothing in `add_comment` moves the anchor for a heading to the end of the line or to the line after it. The SPEC (the rule for a sheaf's title) even treats the block in a heading as intended: "a review comment anchored in the heading is written on that line", and sheaf strips HTML comments when it reads a heading as a title. Other readers of the same file (`boss-goal`, agentview) are not told.

**What to ask of sheaf (for the sheaf team):** for a `heading` block, anchor at the **end of the heading line** whatever the selection (or write the block on the line after the heading as its own HTML block), so no reader sees a comment inside a heading's words. A comment in a heading's middle also splits the heading's text for any other tool.

## (2) The agentview fix, to build after PR 54

`context.HEADING` / `heading_text` take the comment blocks out of a heading line before comparing it with the title: `<!-- … -->` on the line, whole, including a block that is cut across the line by a heading word (`Done<!-- … --> when` → `Done when`). A block that runs over several lines (a heading comment is one line, but a hand-written one may not be) is out of scope.

- [ ] A heading with a trailing or inner sheaf-comment block opens the same section as without -- evidence: test in `tests/test_context.py` with the fixtures above
- [ ] The boxes, progress and rows are those of the file without the block -- evidence: same test
- [ ] A block-free heading and a heading that only looks like a block (`<!-- note` unclosed) behave as before -- evidence: tests
