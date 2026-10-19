# 12: Codex sessions and runs

**What to build:** Codex reads the same way as Claude. From the rollout: per-minute writes, busy and idle, Limit and Error from the task-completion error info, and Needs you inferred from an escalated command with no output yet (checked before Hung). A running `codex exec` run shows inside the tile of the Claude session that started it ("waiting on: codex review, 2 min"), found by walking up the process tree; a run with no starter found gets its own tile marked exec. A Codex usage limit shows as one banner with its reset time. No Codex hooks.

**Blocked by:** 09

**Claimed by:** Hugo 2026-10-19 20:41

**Status:** in-progress

- [ ] Rollout facts tested on fixture rollouts (records and fields only, no conversation text)
- [ ] A pending escalated command reads as Needs you, not Hung
- [ ] The starter walk is tested on a fake process tree
- [ ] The usage-limit banner shows until its reset time
