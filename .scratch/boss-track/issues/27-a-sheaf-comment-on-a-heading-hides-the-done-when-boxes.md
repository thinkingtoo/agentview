# 27: A sheaf comment on a goal's heading hides every Done when box

**Status:** done

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

## (2) The agentview fix

Two more cases from claude-boss PR 142 (found for multi-line sheaf-comment blocks), checked here with fixtures: **(a)** a `- [ ]` / `- [x]` line inside a multi-line `<!-- … -->` block was counted as a box (it was: the fixture failed); **(b)** a `## ` line inside a block ended the Done when section (it did: the fixture failed). Cases that already passed: the block on its own line, an unclosed `<!--`, a `<!--` in a code span.

`context.track_card` takes sheaf's comment blocks out of the goal text before reading it (`without_sheaf_comments`, after the fences are out): the `<!-- sheaf-comment …` and older `rd-comment` openers, to the next `-->`, over as many lines as they run. A code span is code. A comment of any other kind stays as written, as before, and so does a sheaf block that never closes. A comment cut across a heading word (`Done<!-- sheaf-comment … --> when`) joins to `Done when`. The Outcome is read from the same lines, so a block's text is no longer in it either.

First version (Opus round 1, PR 55): it took out every `<!--` (the README reader's `without_comments`). Round 1 showed that a hand-written `<!--` that never closes then pairs with the `-->` of a sheaf block further down and hides every box between them, and that a `<!--` in an indented code block or a double-backtick span did the same. Only sheaf's own blocks are taken out now; `without_comments` is as it was.

- [x] A heading with a trailing, inner or multi-line inner sheaf-comment block opens the same section as without -- evidence: `tests/test_context.py` `Tracks` (three tests)
- [x] The boxes, progress and rows are those of the file without the block -- evidence: `assertCart` in the same tests
- [x] (a) a box line inside a multi-line block is no box -- evidence: `test_a_box_line_inside_a_multi_line_comment_is_no_box`
- [x] (b) a `## ` line inside a block does not end the section -- evidence: `test_a_heading_line_inside_a_multi_line_comment_does_not_end_the_section`
- [x] A comment after a box's words is not in its text; a comment of the person's own (unclosed, in a code span, in an indented example) is left as it is and never pairs with a later block; an unclosed sheaf block is left as text -- evidence: the last four tests; mutation-checked (opener pattern, code-span rule, unclosed rule)

**Known limit:** a hand-written comment (not a sheaf block) with box or heading lines inside it still counts them, as before this ticket. A sheaf-comment opener inside a code span that spans lines, or an indented code block, is taken for a block. So is one inside a hand-written comment (`<!-- see <!-- sheaf-comment -->` leaves `<!-- see`). A bare fence line inside an old `rd-comment` body unfences the rest of the file, as before this ticket (sheaf 1.0.0 and later escape such lines).

Review round 2 (Lennart, PR 55): a code span now ends at a backtick run of its own length, and `\`` opens none (CommonMark), so a block after ``` ``a`b`` ``` or `` \` `` is taken out too. Evidence: `test_a_code_span_ends_at_a_run_of_its_own_length_and_an_escaped_backtick_opens_none`; the Outcome case: `test_a_multi_line_sheaf_comment_in_the_outcome_is_not_part_of_it` (fails with the old `track_card` line).

## Live check after the merge (2026-11-13)

PR 55 merged as eac5ca0 (Codex review 3, the last one before the merge, read the final head df4e4d3; the full suite on t-compute at df4e4d3 passed, 2576 tests, OK, 29 skipped). Restart at 11:26:21: MainPID 3345513 to 3895922, `is-active` active, build 4dabf0f39431 = sha1(index.html)[:12]. Before and after, the same 45 `claude` processes (pid and start time identical), tmux server 8512 on the default socket, and the service cgroup holding `server.py` alone; 0 `session.gone` in the 54 events since.

- The client track whose comment started this ticket shows 9 of 10, with 10 boxes and 10 rows. Its goal file (read only, unchanged since 10:46:25) holds Thierry's c1 block on its own line under the heading (the boss's repair). Run in memory on the merged code, the same file with that block put back inside the heading as sheaf wrote it (`## Done<!-- sheaf-comment id=c1 … --> when`) gives 9 of 10 and 10 boxes as well.
- No track lost rows. The rows per track are the same before and after: 12, 10, 10, 12, 11 and 13 across the six track cards.
