# 30: Class c test leftovers of the AgentView half of 25

**What to fix:** three class c test findings of the Codex review of ticket 25's AgentView half (/home/tiroir/Projects/agentview-wt/bram-25-codex-1.md, run by Pablo, verdict GO; checked at 1920f16, the cited lines were off, the real places are below). Tests only; a test that exposes a real bug stops the ticket and goes to Tarek.
1. tests/test_deskwatch.py ~552: `skipUnless("structure sha256" in deskships.CLASSIFIER.read_text(), ...)` reads the classifier at import, so a missing classifier file errors the whole module. It must skip cleanly.
2. tests/test_deskships.py ~117, `test_the_classifier_gets_a_checkout_with_a_head_in_its_dot_git`: it relies on the machine-local classifier and never inspects HEAD. It must prove what it names, with a stub classifier that records what it saw.
3. tests/test_deskships.py ~112, `test_a_new_hint_line_that_only_contains_the_digest_mark_is_still_a_change`: add the near-miss cases (wrong indentation, suffix text, non-hex text).

**Blocked by:** 25

**Claimed by:** Leire 2026-11-14

**Status:** open

- [ ] test_deskwatch: a missing classifier file skips the digest tests instead of erroring the module (run with the classifier path pointed at a missing file)
- [ ] the .git/HEAD test uses a stub classifier that records the checkout it was given and its HEAD, and asserts on that record
- [ ] the digest-mark test covers wrong indentation, suffix text and non-hex text, each still a change
