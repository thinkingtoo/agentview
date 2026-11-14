# 25: A re-indented workflow is not the same workflow

**What to fix:** carried from tickets 18, 21 and 22 (Carmen's recommendation): the desk compares hint lines with their indentation stripped, so a change that only moves a key under another mapping (a step into another job, a branch filter out of `on.push`) compares equal at the press. Keeping indentation on every --full hint line would change every "What ships" line; instead give each workflow one digest of its structure (keys with their nesting) in --full, store it in the ready record, and refuse the press when it changed. Also (pre-existing, Carmen's review): an unlistable `.github/workflows` directory makes branch_deploys.py exit 1, which a push check reads as "nothing fires".
Also from Codex on 21's merged diff (/home/tiroir/Projects/agentview-wt/yara-21-codex-3.md, all in main(), class b): an empty `.git` directory is accepted as a checkout with no workflows (exit 1); a workflow entry that is a FIFO, or a symlink to a FIFO or device (a symlink can be committed in a hostile repo), blocks `read_bytes` for ever. Read only regular files inside the checkout; anything else gives a could-not-parse line.

**Blocked by:** 22

**Status:** ready-for-agent

- [ ] Moving a step under another job between hand-over and press refuses it (test through deskwatch.check_ships)
- [ ] An unchanged workflow keeps the same digest across runs and machines (test)
- [ ] An unlistable workflows directory gives a could-not-parse line, exit 0 (test)
- [x] A workflow that is a symlink to a FIFO or device, or points outside the checkout, gives a could-not-parse line and returns at once (done in ticket 22, b087c9e: test_a_fifo_is_could_not_parse_and_does_not_block, test_a_symlink_to_dev_zero_is_could_not_parse, test_a_symlink_to_a_file_outside_the_checkout_is_could_not_parse)
- [ ] A checkout whose .git is empty is not read as "nothing fires" (test)
- [ ] Default output stays byte-identical on monorepo, agentview, sheaf, ~/.claude, thinkingtoo
- [ ] Class c left by ticket 22's reviews (carmen-22-sonnet-5.md, -6.md), in branch_deploys.py:
  - a TimeUp landing between `out.append(...)` and `shown += 1` in main() could print one name twice (a two-bytecode window, never seen in four sweeps);
  - a closed stdout pipe gives a BrokenPipeError traceback, exit 1; a stdout write failure exits 120 (the old script does too);
  - a file where every line contains "deploy" prints every line, so output is as large as the file (at most 1 MB); cap the hint lines per file;
  - a workflow file name containing a newline can add fake lines to the output.
