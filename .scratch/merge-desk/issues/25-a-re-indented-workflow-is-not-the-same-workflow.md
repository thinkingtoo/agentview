# 25: A re-indented workflow is not the same workflow

**What to fix:** carried from tickets 18, 21 and 22 (Carmen's recommendation): the desk compares hint lines with their indentation stripped, so a change that only moves a key under another mapping (a step into another job, a branch filter out of `on.push`) compares equal at the press. Keeping indentation on every --full hint line would change every "What ships" line; instead give each workflow one digest of its structure (keys with their nesting) in --full, store it in the ready record, and refuse the press when it changed. Also (pre-existing, Carmen's review): an unlistable `.github/workflows` directory makes branch_deploys.py exit 1, which a push check reads as "nothing fires".
Also from Codex on 21's merged diff (/home/tiroir/Projects/agentview-wt/yara-21-codex-3.md, all in main(), class b): an empty `.git` directory is accepted as a checkout with no workflows (exit 1); a workflow entry that is a FIFO, or a symlink to a FIFO or device (a symlink can be committed in a hostile repo), blocks `read_bytes` for ever. Read only regular files inside the checkout; anything else gives a could-not-parse line.

**Blocked by:** 22

**Claimed by:** Bram 2026-11-14 16:11

**Status:** done

- [x] Moving a step under another job between hand-over and press refuses it (test through deskwatch.check_ships; AgentView 1920f16 (dev, live since the 16:38 restart): Ships.test_a_key_moved_under_another_mapping_between_the_hand_over_and_the_press_is_refused: job `b` re-indented under job `d`, same hint lines and numbers; red against the old classifier, green with the new; plus test_deskships.test_a_changed_structure_digest_is_a_change_and_a_record_without_one_is_not and test_a_new_hint_line_that_only_contains_the_digest_mark_is_still_a_change)
- [x] An unchanged workflow keeps the same digest across runs and machines (test_the_digest_is_the_same_across_runs_hash_seeds_comments_and_indent_width: PYTHONHASHSEED 1 vs 777, a comment, a doubled indent; test_a_changed_value_with_the_same_keys_keeps_the_digest)
- [x] An unlistable workflows directory gives a could-not-parse line, exit 0 (test_an_unlistable_workflows_directory_is_could_not_parse_not_exit_1: chmod 0 on the directory)
- [x] A workflow that is a symlink to a FIFO or device, or points outside the checkout, gives a could-not-parse line and returns at once (done in ticket 22, b087c9e: test_a_fifo_is_could_not_parse_and_does_not_block, test_a_symlink_to_dev_zero_is_could_not_parse, test_a_symlink_to_a_file_outside_the_checkout_is_could_not_parse)
- [x] A checkout whose .git is empty is not read as "nothing fires" (test_an_empty_git_directory_is_not_a_checkout; a worktree `.git` file and a FIFO `.git` covered too; deskships now writes `.git/HEAD` in its temp checkout)
- [x] Default output stays byte-identical on monorepo, agentview, sheaf, ~/.claude, thinkingtoo (old origin/main vs new, main and dev: 10 of 10 identical before and after the review fixes; --full identical once the `= structure` lines are filtered; merged live: sheaf main --full gives one `= structure` line and no could-not-parse; monorepo main 4 and dev 5 structure lines, 0 could-not-parse; agentview and thinkingtoo have no firing workflows, exit 1 as before)
- [x] Class c left by ticket 22's reviews (carmen-22-sonnet-5.md, -6.md), in branch_deploys.py, each with a test in test_branch_deploys.py (double-print window: `hits[len(out):]`, structural, no test):
  - a TimeUp landing between `out.append(...)` and `shown += 1` in main() could print one name twice (a two-bytecode window, never seen in four sweeps);
  - a closed stdout pipe gives a BrokenPipeError traceback, exit 1; a stdout write failure exits 120 (the old script does too);
  - a file where every line contains "deploy" prints every line, so output is as large as the file (at most 1 MB); cap the hint lines per file;
  - a workflow file name containing a newline can add fake lines to the output.

## Done (Bram, 2026-11-14)
- Merged: AgentView half into dev at 1920f16 (branch bram/25, history-check clean, live classifier b087c9e: test_deskwatch, test_deskships, test_deskscan, test_desk, test_desk_relay 435 OK, 1 skipped = the move test, which needs the new classifier), restarted 16:38:05 (MainPID 1314470, 200, claude 45 before and after, `hooks/desk status` identical, sheaf#293 still pinned 11ff860 and check_ships on it did not refuse). ~/.claude half into main at 2295355 (`branch_deploys.py ~/.claude main` still exit 1). Reviews: bram-25-sonnet-1.md (GO, class c only; F1 class b fixed), bram-25-sonnet-2.md (GO, class c only).
- Digest design: keys and nesting of the composed YAML graph, never values, keys json-quoted, aliased nodes walked once as back-references; lines `= structure sha256:<32 hex>` in --full only, `  - <name>: structure sha256:<hex>` in the What-ships lines. A record handed over before the digest existed has none and is not refused for lacking it (only a whole digest line is skipped).
- Accepted limit (Tarek, F6): the digest over-refuses when keys or a sequence are reordered, and does not walk complex (non-scalar) keys. That fails safe.
- Not done: Codex on both halves, after the 20:00 Codex run on ticket 22.
