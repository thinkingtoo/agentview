# 02: the turn hook says the `$ ` rule twice

**What:** `hooks/turn_line.py` ASK states where a command goes twice: "A command the user must run goes inside double quotes, or after "$ " at the end of the ask" in the first paragraph, and "A command the user must run or type goes after "$ " in the ask too, even when an option of your question offers it" at the end of the Paste paragraph. Both are pinned by tests (`test_a_command_the_person_must_run_is_asked_for_in_double_quotes_or_after_a_dollar`, `test_a_command_the_person_types_reaches_the_ask_line`). Merging them would save about 100 characters per turn and leave one place to keep in step.

**Found by:** the standards review of PR #3 (ticket 01), 2026-11-10. It was already there before that PR.

**Blocked by:** None

**Claimed by:** Tarek 2026-11-11

**Status:** done

- [x] The rule is said once, and the tests pin the merged sentence (PR #12 merged as eeb5caf; text 2047 characters; `python3 -m unittest tests.test_turn_hook` on t-compute at 019b3e3: "Ran 26 tests in 5.110s / OK")

## Comments

**Tarek, 2026-11-11** (boss dispatch from Noor). The two sentences are one, in the first paragraph: a command the user must run or type goes inside double quotes, or after "$ " at the end of the ask, even when an option of the question offers it, and without a leading !. The text went from 2112 to 2047 characters; the 2150 ceiling stayed, the floor went from 2050 to 2000. The sentence test pins the merged sentence and that "$ " is said once. Tests ran on t-compute (26, OK). The bug hunt's two class c findings are tickets 03 and 04.
