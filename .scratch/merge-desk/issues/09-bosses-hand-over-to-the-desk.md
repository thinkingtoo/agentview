# 09: Bosses and concierges hand merges to the desk

**What to build:** in the claude-boss plugin (sweatshop-ai/claude-boss), the boss and concierge instructions say: a PR ready for the person's merge goes to `desk ready`, not to a Paste and an ask per PR. The ask stays for decisions that are not a merge.

**Blocked by:** 02

**Claimed by:** Santiago 2026-11-14 00:13

**Status:** done

- [x] The boss skill's merge step names `desk ready` (SKILL.md P13/P14; `test_a_merge_for_the_owner_goes_to_the_desk_not_to_an_ask` passes, PR 151)
- [x] A boss that wraps up lists its desk items in its wrap-up state (Phase E step 4; `test_wrap_up_lists_the_desk_items_in_the_state_line` passes, PR 151)
