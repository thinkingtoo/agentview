# 14: the hammers-on-top test leaves four gaps

**What to build:** close the gaps the review of PR 45 found in `tests/test_hammers_on_top.py` (all test-side; the product code had no finding):
- assert exactly one `<ul class="ov-objs">` and that the output starts with it, in the rows case and the no-rows case (today a bare `<li>` with no `<ul>`, or the hammers back in a separate `<ul>` before the rows, would pass);
- a folded card draws nothing, hammers included (the harness never fills `FOLDED`);
- take `esc` and `known` from index.html instead of keeping copies in the harness;
- move `import re` to the top of the file.

**Blocked by:** 13

**Status:** needs-triage

- [ ] The one-`<ul>` assert is red with the hammers put back in their own `<ul>` -- evidence: mutation run
- [ ] A folded project draws `""` -- evidence: new test
- [ ] The harness uses the page's own `esc` and `known` -- evidence: test passes with them extracted

Also seen, not from this branch: a project in `FOLDED` whose card has no boxes and no rows has no `.ov-count` button, so its hammers are hidden with nothing to unfold them (same on dev).
