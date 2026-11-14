# 26: A person's exact copy of AgentView's line is not taken for ours

**What to fix:** class b left by ticket 19 (Codex on ae1df80, /home/tiroir/Projects/agentview-wt/nuno-19-codex-4.md, finding 4). Ownership is matched by line text, first occurrence: when the person pastes a byte-identical copy of AgentView's current line (a pin, a recommendation) above the recorded one, `_kinds()` takes the copy for ours and the real line for theirs. A later hand-over replaces the person's copy and keeps the stale line, and `parse()` can then read the stale pin. The record stores no positions, so the fix needs a record format change: store each owned line's ordinal among identical lines in the block (or its index), and match by that.

**Same class (Sonnet review nuno-19-sonnet-5.md, b1):** a person line with the same text as a recorded line (an identical `Recommendation:` line, say) is taken for ours, first match wins; ticket 19's `desk adopt` avoids it on the live desk only because that page holds no person-written line.

**Blocked by:** 19

**Status:** ready-for-agent

- [ ] A person's byte-identical copy of the pin line above ours: the next hand-over replaces ours and keeps theirs (test)
- [ ] parse().pinned reads the recorded occurrence, not the first (test)
- [ ] A record written before this change is still read (no item loses its pin on upgrade) (test)
