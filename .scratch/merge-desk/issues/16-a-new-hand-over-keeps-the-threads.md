# 16: A new hand-over keeps the threads on its item

**What to fix:** `deskfile.put` replaces an item's whole block, so a second `desk ready` (or the install scan re-pinning) on an item already on the page deletes the person's comment threads on it, open ones included. Keep every line inside the block that is not the item's own (sheaf comment threads, a person's text) and replace only the lines AgentView wrote. Found in 08's review round 4 (Rania, R4-4). Data loss of the person's text: sensitive, up to three review rounds.

**Blocked by:** none

**Claimed by:** Alonso 2026-11-14 02:05

**Status:** done

- [x] A re-hand-over of an item with an open comment thread keeps the thread, word for word (test through deskfile.put): tests/test_desk.py class RehandOver, 17 tests, fail on the old put, pass now
- [x] The install scan re-pinning an Install item keeps its thread the same way: tests/test_deskinstall.py test_main_moving_keeps_the_thread_on_the_item (through deskinstall.scan), fails without the fix
- [x] The item's own lines (pinned, What ships, Recommendation) are the new ones: test_the_items_own_lines_are_the_new_ones, test_what_ships_lines_are_the_new_ones
