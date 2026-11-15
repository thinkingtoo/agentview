# 36: Items whose keys differ only by case: one rule in adopt, put, settle and drop

**What to fix:** a class b finding of Rosalie's Codex run on the merged range of 32 (/home/tiroir/Projects/agentview-wt/rosalie-32b-codex-1.md, `deskfile.py:987` `adopt`, VERIFIED by Rosalie on dev 88f816a, handoff /home/tiroir/Projects/agentview-wt/handoff-rosalie-2026-11-15.md).
- Two items whose keys differ only by case (`a/b#1` and `A/b#1`) on one page. `adopt` skips the first as ambiguous (two Recommendation lines), then adopts the second under the shared lowercase slot: it returns `(['A/b#1'], ['a/b#1'])` and the record key is `a/b#1`.
- A later `put` finds the first block case-insensitively (`deskfile.py:741`) but reads the record of the second item: the page's first block is read with lines that are not its own.
- The four functions do not agree on case today: `put` and `_unhidden` match keys case-insensitively, `settle` (`k != key`) and `drop` (`k == key`) match exactly, and `_slot` lowercases every key but `install:` ones. The fix names one rule and applies it in all four, and `adopt` stops giving one item the record slot of another.
- The rule to write down (in the `deskfile` docstring that holds the key rule, and here): GitHub owner and repo names are case-insensitive, so `a/b#1` and `A/b#1` are one PR and share one record slot; an `install:` key is a tool's and is exact. One page holding two items of one slot is a conflict for the person to sort out: `adopt` skips both and reports both under skipped (neither takes the other's record); `put`, `settle` and `drop` act on the first of them in page order, the one `put` already takes.
- Tests only through `deskfile` (`adopt`, `put`, `settle`, `drop`) on the exact page above; the desk test files touched pass at load < 8.

**Blocked by:**

**Claimed by:** Anika 2026-11-15 01:09

**Status:** done

## Acceptance criteria
- [x] a red test on that exact page (`a/b#1` and `A/b#1`, each with two Recommendation lines for the first), then green: neither item takes the other's record
  - Evidence: test_adopt_gives_neither_of_two_items_that_differ_only_by_case_the_others_record: red on 88f816a (`(['A/b#1'], ['a/b#1'])`), green on anika/36 cb0ad1a (`([], ['A/b#1', 'a/b#1'])`, record empty); the three conflict tests were also run red with deskfile.py and deskscan.py stashed
- [x] the rule for case written down: one PR or a conflict, and the same rule applied in `adopt`, `put`, `settle` and `drop` (a test per function on a page whose key differs from the item's by case)
  - Evidence: `deskfile._same` / `_conflict` docstrings and `adopt`'s docstring; test_one_rule_for_case_in_put_settle_and_drop, test_two_items_of_one_slot_are_a_conflict_that_put_settle_and_drop_resolve_on_the_first, test_settle_on_a_conflict_page_does_not_take_a_persons_identical_result_line_for_ours, test_deskscan Tidy.test_two_items_of_one_pr_whose_keys_differ_by_case_are_not_tidied
- [x] the desk test files I touch pass at load < 8
  - Evidence: `python3 -m unittest test_desk test_deskscan` from tests/: 308 OK, at load 7.71 (two earlier runs started at 8.03 and 8.67 and also passed)

## Known limit
- `deskscan.tidy` looks up the history of an item by its exact key (`k not in last`, deskscan.py:466, as on dev 88f816a): a lone item whose page key and history key differ only by case is not tidied. It fails safe (the item stays). Codex rounds 2 and 3 (class b). Ticket candidate.
