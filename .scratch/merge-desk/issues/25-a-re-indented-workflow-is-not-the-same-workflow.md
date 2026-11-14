# 25: A re-indented workflow is not the same workflow

**What to fix:** carried from tickets 18, 21 and 22 (Carmen's recommendation): the desk compares hint lines with their indentation stripped, so a change that only moves a key under another mapping (a step into another job, a branch filter out of `on.push`) compares equal at the press. Keeping indentation on every --full hint line would change every "What ships" line; instead give each workflow one digest of its structure (keys with their nesting) in --full, store it in the ready record, and refuse the press when it changed. Also (pre-existing, Carmen's review): an unlistable `.github/workflows` directory makes branch_deploys.py exit 1, which a push check reads as "nothing fires".
Also from Codex on 21's merged diff (/home/tiroir/Projects/agentview-wt/yara-21-codex-3.md, all in main(), class b): an empty `.git` directory is accepted as a checkout with no workflows (exit 1); a workflow entry that is a FIFO, or a symlink to a FIFO or device (a symlink can be committed in a hostile repo), blocks `read_bytes` for ever. Read only regular files inside the checkout; anything else gives a could-not-parse line.

**Blocked by:** 22

**Status:** ready-for-agent

- [ ] Moving a step under another job between hand-over and press refuses it (test through deskwatch.check_ships)
- [ ] An unchanged workflow keeps the same digest across runs and machines (test)
- [ ] An unlistable workflows directory gives a could-not-parse line, exit 0 (test)
- [ ] A workflow that is a symlink to a FIFO or device, or points outside the checkout, gives a could-not-parse line and returns at once (test)
- [ ] A checkout whose .git is empty is not read as "nothing fires" (test)
- [ ] Default output stays byte-identical on monorepo, agentview, sheaf, ~/.claude, thinkingtoo
