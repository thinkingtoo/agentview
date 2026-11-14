# 31: The desk never deletes a person's text (deskfile.py, class a, sensitive)

**What to build:** three ways deskfile.py takes a person's text for AgentView's and later deletes it. Found by Codex reviews of tickets 19, 27 and 28 on merged heads; all three are data loss on the person's own page. A person's line is never removed, rewritten or exposed by a hand-over, a settle, a drop or an adopt. Sensitive (deleting data): up to three review rounds.

Reviews and heads:
- 19a: /home/tiroir/Projects/agentview-wt/nuno-19-codex-6.md, head 5059517, `deskfile.py:~605` (Codex cited 607).
- 27a: /home/tiroir/Projects/agentview-wt/arvid-27-codex-6.md, head 6501f8b, `deskfile.py:530` and `~555` (Codex cited 554).
- 28a: /home/tiroir/Projects/agentview-wt/kofi-28-codex-6.md, head 3a2b72f, `deskfile.py:167`.

## 31a (from 19a): `_adoptable` adopts a person's 4-space note under What ships
`_adoptable` takes every non-empty line that starts with four spaces under `What ships:` as one of our bullets. On a legacy page (no record) holding `    - NOTE: deploy manually` under What ships, `desk adopt` records that note as AgentView's; the next hand-over removes it as an obsolete ships bullet. This is the data-loss case ticket 19 was made to close.

## 31b (from 27a): `_prev_stands` decides on LCS length only, and `prev` concatenates generations
- `_prev_stands` (`deskfile.py:530`) compares `len(_mine(texts, prev)) > len(_mine(texts, lines))`. Record holds generation B with A in `prev`; the page is B, but the person changed or removed two B-specific lines and added their own copy of A's old pin line. A now matches more lines than B, the page is judged "behind", `_own` claims the copied A pin, and the next hand-over deletes it.
- `_record_block` (`~555`) with `behind` builds `prev = was["lines"] + was["prev"]`. After failed writes A to B and B to C while the page stays A, a later successful write records `prev` as C+B+A, a hybrid no single generation ever had. Once the page is at C and the person adds a copy of any B or A line, `_prev_stands` can match the hybrid and `_own` treats the person's line as ours.
- `prev` has to hold distinguishable generations (or one generation), and the "behind" decision has to need more than a longer match count.

## 31c (from 28a): a closed note holding a list line and a literal `<!-- sheaf-comment`
`_open_at` (`deskfile.py:167`) marks a comment broken when a thread opener (`THREAD.match`) follows a task or heading line inside it. A person's closed note that holds a list line and a literal `<!-- sheaf-comment` is read as left open; `_unhidden` then inserts `-->` before the list line, which exposes the list line as an item. Reproduced in memory on 3a2b72f:

    import deskfile as d
    t = '<!-- private note\n- [ ] Merge a/b#9: old\nperson tail\nliteral <!-- sheaf-comment x -->\nmore tail\n-->\n- [ ] Merge a/b#1: real\n'
    d.drop(t, 'a/b#9', record={})
    # returns '<!-- private note -->\n- [ ] Merge a/b#1: real\n'  (the note's lines are gone)

`put` on the same page exposes the hidden item and the note's contents (rewrites the note to `<!-- private note -->` and turns the list line into a real item). Sonnet rated this class c; Codex class a, and the repro shows deletion of the person's text. The existing regression test has the nested opener before the list line, so it does not cover this order. Treat the comment as broken only when the thread is whole (opener and its closing `-->` on the same line) and it hides the later text, or find another test that tells a left-open comment from a closed note.

**Blocked by:** none

Order: this ticket goes first; the ticket after it waits on it, same file.

**Claimed by:** Nuno 2026-11-14 20:10

**Status:** done

## Acceptance criteria
- [x] A person's 4-space note under What ships on a legacy page is not adopted, and a hand-over after `adopt` keeps it (red test on the 19a page, with the note `    - NOTE: deploy manually`)
- [x] A page where the person changed two lines of our current generation and added a copy of an old pin line is not judged behind, and a hand-over keeps the copy (red test, 27a scenario)
- [x] After failed writes A to B and B to C with the page at A, a successful write records `prev` as one generation, never C+B+A, and a person's copy of a B or A line is kept once the page is at C (red test)
- [x] The 28a text above: `drop` of `a/b#9` returns the note's lines intact, and `put` leaves the note closed and exposes no item from it (red tests on the exact string above, both functions)
- [x] An open comment closed only by a later thread's `-->` is still told apart from a closed note (the existing tests of ticket 28 stay green)
- [x] Each fix is red on its review's head, green after, with the commands and results in the report

Evidence (Nuno, 2026-11-14): branch nuno/31 head b87a1c1 (on origin). New tests are red on the review heads 5059517, 6501f8b and on 3a2b72f (the prev-generation test is red on 5059517 and 6501f8b only: an earlier ticket already fixed it on dev) and green on b87a1c1. Reviews: /home/tiroir/Projects/agentview-wt/nuno-31-codex-1.md (3 class a, all fixed, red tests first), round 2 by a fresh Sonnet (Codex out of tokens until Nov 15 01:00): /home/tiroir/Projects/agentview-wt/nuno-31-sonnet-2.md, no class a. Codex run on the final head is still owed (sensitive).
