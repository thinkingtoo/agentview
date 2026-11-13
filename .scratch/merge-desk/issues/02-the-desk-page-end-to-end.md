# 02: A handed-over PR appears on the merge desk page

**What to build:** `hooks/desk ready <owner/repo> <n> --what … --rec merge|wait|dont --why … [--after N]` pins the PR's current head and adds a desk item to `~/.local/state/agentview/merge-desk.md`, which AgentView renders with the laptop's sheaf hub. The item is a list item whose first line is `- [ ] Merge <owner/repo>#<n>: <what>`, with the recommendation, the evidence, who handed it over and how long it has waited on indented lines (spec, "The page"). `desk status` and `desk withdraw` as in the spec. Handing the same PR over again replaces the item and re-pins.

**Blocked by:** None (can start immediately).


**Claimed by:** Ciro 2026-11-13 22:47

**Status:** in-progress

- [ ] `desk ready` refuses a PR that is not open, and says why
- [ ] The page is edited one item at a time: a comment on another item survives an add, a replace and a withdraw
- [ ] `desk status` reads waiting / merged as <sha> / refused and why, from the log
- [ ] The file lives under `~/.local/state/agentview/`, never under `~/.claude` or anything brain-sync carries
