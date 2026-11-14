# 16: A new hand-over keeps the threads on its item

**What to fix:** `deskfile.put` replaces an item's whole block, so a second `desk ready` (or the install scan re-pinning) on an item already on the page deletes the person's comment threads on it, open ones included. Keep every line inside the block that is not the item's own (sheaf comment threads, a person's text) and replace only the lines AgentView wrote. Found in 08's review round 4 (Rania, R4-4). Data loss of the person's text: sensitive, up to three review rounds.

**Blocked by:** none

**Claimed by:** Alonso 2026-11-14 02:05

**Status:** in-progress

- [ ] A re-hand-over of an item with an open comment thread keeps the thread, word for word (test through deskfile.put)
- [ ] The install scan re-pinning an Install item keeps its thread the same way
- [ ] The item's own lines (pinned, What ships, Recommendation) are the new ones
