# 02: Keyword search across all interactive conversations

**What to build:** a search box on the agentview page, next to **⟲ closed N**. You type words and get back one row per matching interactive conversation, from any day, running ones included. Each row shows the conversation's name, Claude's title, the project, the date, and the exchange that matched. Spec: `docs/specs/2026-09-29-conversation-archive.md` (decisions table and measured facts).

This is the tracer bullet: the index, the job that keeps it current, the endpoint and the UI, end to end.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] One piece of the index is one exchange: a prompt the user typed plus the assistant's reply text. `<system-reminder>` blocks, hook injections and tool calls and results are stripped. Unit tests on a fixture transcript cover the stripping.
- [ ] Only `entrypoint: cli` transcripts are indexed. Headless and subagent transcripts are not.
- [ ] The index is one SQLite file (FTS5) under `~/.claude/agentview/`. Nothing is sent off the machine.
- [ ] A timer updates it every few minutes and only reads transcripts that changed (tracked by size and mtime, or by offset). A first run over all ~525 conversations finishes and reports how long it took.
- [ ] The search endpoint groups hits by conversation, ranked by the best passage, and returns name, title, project, date and the matching passage. The title comes from the same `ai-title` reader the closed list already uses.
- [ ] Clicking a result is not wired up here (that is ticket 03). The row says what the conversation is and does not pretend to be clickable.
- [ ] The poll stays fast: search is a separate request, never part of the roster poll.
- [ ] The README has a section on search.
