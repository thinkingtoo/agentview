# 13: "What ships" is compared exactly, not after stripping

**What to fix:** deskships._same normalises more than the page rewrites: `deploy_prod.sh` and `deployprod.sh` compare equal, and so does a command with or without a `<...>` span. A base branch that changed in exactly those characters between hand-over and press would pass the re-check. Unescape only a backslash before punctuation, strip only real tags, and map `_` to `*` (what sheaf writes). Found in 05's round 4 (Chiara, class b, /home/tiroir/Projects/agentview-wt/chiara-05-opus-4.md R4-1).

**Blocked by:** 05

**Claimed by:** Britta 2026-11-14 01:35

**Status:** in-progress

- [x] `deploy_prod.sh` changed to `deployprod.sh` between hand-over and press refuses the press (the press compares the raw lines stored in the `ready` record with a fresh raw read; tests/test_deskships.py test_the_stored_lines_are_compared_exactly_not_after_stripping, tests/test_deskwatch.py Ships)
- [x] A `<...>` span added to a deploy line, or `\$TOKEN` vs `$TOKEN`, `dist/_` vs `dist/*`, refuses the press; the same raw line (`<staging>` included) passes
- [x] The page's text is never compared (`_same` removed); an item handed over before the lines were stored refuses with "hand it over again" (test_an_item_handed_over_before_the_lines_were_stored_must_be_handed_over_again)
