# 05: Two-line summaries under each result

**What to build:** each search result carries a two-line summary: what the conversation was about, and where it stood when it stopped (done, waiting on the user, half-way). That way you can tell which of several similar conversations is the one to reopen. Spec: `docs/specs/2026-09-29-conversation-archive.md` (decisions table and measured facts).

**Blocked by:** 02: Keyword search across all interactive conversations

**Status:** ready-for-agent

- [ ] Summaries are written by `claude -p --model haiku` through the CLI, not the API.
- [ ] These runs execute with hooks off, so they never appear as sessions on the page and never write team lines. Verified by watching the page during a run.
- [ ] A conversation is summarised again once it has been quiet for 10 minutes and has changed since its last summary.
- [ ] The backfill of ~525 conversations is paced (a limited number per run) so it does not eat the plan's quota in one go; the pace is written down.
- [ ] The summary runs are `sdk-cli` transcripts, so they are left out of the index (02) and deleted after 30 days (01).
- [ ] Summaries are stored in the index file and shown in the result row. A conversation that has no summary yet shows only its title.
