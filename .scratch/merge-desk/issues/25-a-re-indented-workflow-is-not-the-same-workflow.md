# 25: A re-indented workflow is not the same workflow

**What to fix:** carried from tickets 18, 21 and 22 (Carmen's recommendation): the desk compares hint lines with their indentation stripped, so a change that only moves a key under another mapping (a step into another job, a branch filter out of `on.push`) compares equal at the press. Keeping indentation on every --full hint line would change every "What ships" line; instead give each workflow one digest of its structure (keys with their nesting) in --full, store it in the ready record, and refuse the press when it changed. Also (pre-existing, Carmen's review): an unlistable `.github/workflows` directory makes branch_deploys.py exit 1, which a push check reads as "nothing fires".

**Blocked by:** 22

**Status:** ready-for-agent

- [ ] Moving a step under another job between hand-over and press refuses it (test through deskwatch.check_ships)
- [ ] An unchanged workflow keeps the same digest across runs and machines (test)
- [ ] An unlistable workflows directory gives a could-not-parse line, exit 0 (test)
- [ ] Default output stays byte-identical on monorepo, agentview, sheaf, ~/.claude, thinkingtoo
