# 03: A click on a search result reopens or jumps

**What to build:** clicking a search result brings that conversation to the front. If it is running, the page focuses its pane or tab, the same as a click on a live row. If it is closed, it is resumed in a new WezTerm tab, in its old directory, with its old permission mode and name. That works even for conversations older than any snapshot: only the last 60 snapshots are kept, currently going back to 2026-09-27. Spec: `docs/specs/2026-09-29-conversation-archive.md` (decisions table and measured facts).

**Blocked by:** 02: Keyword search across all interactive conversations

**Status:** ready-for-agent

- [ ] A running conversation is never resumed a second time. Its row jumps.
- [ ] For a closed conversation, the revive record comes from its latest snapshot when there is one. Otherwise it is built from the transcript: the `cwd` and the last `permissionMode` (mapped to the matching `claude` flag). Unit tests cover both paths.
- [ ] The conversation's name comes back through the same name-seeding the closed list uses, when a name is known.
- [ ] When the directory no longer exists, the row says so and nothing is launched.
- [ ] Each revive is logged as the closed list's revives are.
