# 02: the turn hook says the `$ ` rule twice

**What:** `hooks/turn_line.py` ASK states where a command goes twice: "A command the user must run goes inside double quotes, or after "$ " at the end of the ask" in the first paragraph, and "A command the user must run or type goes after "$ " in the ask too, even when an option of your question offers it" at the end of the Paste paragraph. Both are pinned by tests (`test_a_command_the_person_must_run_is_asked_for_in_double_quotes_or_after_a_dollar`, `test_a_command_the_person_types_reaches_the_ask_line`). Merging them would save about 100 characters per turn and leave one place to keep in step.

**Found by:** the standards review of PR #3 (ticket 01), 2026-11-10. It was already there before that PR.

**Blocked by:** None

**Claimed by:** Tarek 2026-11-11

**Status:** needs-triage

- [ ] The rule is said once, and the tests pin the merged sentence
