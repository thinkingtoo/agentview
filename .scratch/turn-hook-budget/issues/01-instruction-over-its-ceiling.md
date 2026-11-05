# 01: the turn hook's instruction is 2310 characters, over its 2150 ceiling

**What to fix:** `tests/test_turn_hook.py`, `Starting.test_the_instruction_stays_short`, fails on origin/dev: `AssertionError: 2310 not less than 2150 : 2310`. Reconfirmed 2026-11-05 on origin/dev 6f59209 by running that one test file (26 tests, 1 failure). It also fails without the change of PR 2 (ticket 40), which does not touch `hooks/turn_line.py` or this test, so it is older than that merge. Found on t-compute by Vikram.

**Which commit did it:** `c046ff0` (2026-11-01, "Turn reminder: team-line goes before an AskUserQuestion that ends the turn, and a typed command must fit whole in the ask"). It changed only `hooks/turn_line.py` (6 insertions, 2 deletions) and left the test alone. Length of the injected text, measured the way the test measures it (session id of 36 characters, writer path fixed at `/home/alice/Projects/agentview/hooks`), at each commit that changed `hooks/turn_line.py` since 2026-10-22:

| Commit | Date | Length |
|---|---|---|
| 25955b6 | 2026-10-22 | 1534 |
| 0d0ac0c | 2026-10-22 | 1622 |
| 7aedbeb | 2026-10-22 | 1917 |
| e21777b | 2026-10-22 | 1975 |
| 57db02a | 2026-10-22 | 2020 (the commit that set the 2150 ceiling) |
| 0c1da83 | 2026-10-25 | 2020 (last commit that touched the file's inputs before c046ff0) |
| **c046ff0** | 2026-11-01 | **2310** |

The commits between 2026-10-19 and 2026-10-21 could not be measured the same way: their `turn_line.py` has no `PASTE` attribute, which the measuring wrapper patches; they are before the Paste paragraph and below the ceiling then in force. There is no CI workflow in this repo (`.github/workflows` does not exist), so nothing ran the test on 2026-11-01.

**What the test guards:** the text is injected into every turn of every session on this machine (UserPromptSubmit hook additional context), so its size is paid in every turn. The test's own comment records that each growth was approved by the owner: 731 on 2026-09-25, one more sentence and one for the single quote on 2026-10-19, the Paste paragraph (ticket paste-04) on 2026-10-22. The ceiling of 2150 "leaves room for one more sentence and no more". c046ff0 added about 290 characters past it with no recorded approval of that size in the test or the commit message. Its lower bound (`assertGreater(len(said), 2000)`) also has to move with any change.

**Why now:** `python3 -m unittest discover -s tests` does not exit 0 on origin/dev, which the overview-build objective needs on a fresh clone.

**Left open (not decided here):** shorten the text back under 2150 without losing what c046ff0 added (team-line before an AskUserQuestion that ends the turn; a command goes last and whole within 160 characters); or raise the ceiling and the floor to the new size, which is the owner's call because it is a standing per-turn cost. Do not do either without the owner's word on the size.

**Blocked by:** None

**Claimed by:** none

**Status:** needs-triage

- [ ] The test passes on origin/dev, by a decision the owner made about the size
- [ ] The test's comment records that decision (date and size), as it does for the earlier ones
