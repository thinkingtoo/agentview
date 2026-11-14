# 13: "What ships" is compared exactly, not after stripping

**What to fix:** deskships._same normalises more than the page rewrites: `deploy_prod.sh` and `deployprod.sh` compare equal, and so does a command with or without a `<...>` span. A base branch that changed in exactly those characters between hand-over and press would pass the re-check. Unescape only a backslash before punctuation, strip only real tags, and map `_` to `*` (what sheaf writes). Found in 05's round 4 (Chiara, class b, /home/tiroir/Projects/agentview-wt/chiara-05-opus-4.md R4-1).

**Blocked by:** 05

**Claimed by:** Britta 2026-11-14 01:35

**Status:** done

- [x] `deploy_prod.sh` changed to `deployprod.sh` between hand-over and press refuses the press (Differ.test_a_character_the_page_never_writes_is_a_change, 6 R4-1 pairs + redirect, red then green; branch britta/13-ships-exact)
- [x] A `<...>` span added to a deploy line refuses the press (spaced/attribute spans and `<in ... >out` refuse; a bare `<name>` stays equal because pandoc drops it: see report)
- [x] A line the page rewrote (escaped punctuation, `_` → `*`) still compares equal (test_what_the_page_writes_back_is_no_change)
