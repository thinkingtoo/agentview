# 01: Keep interactive transcripts forever, delete headless ones after 30 days

**What to build:** Claude Code stops deleting old transcripts, so every interactive conversation stays reopenable and searchable. Headless (`entrypoint: sdk-cli`) transcripts, which are about three quarters of them, are deleted by a nightly job once they are older than 30 days. That keeps disk growth down to your own sessions. Spec: `docs/specs/2026-09-29-conversation-archive.md` (decisions table and measured facts).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `cleanupPeriodDays` is set in the user settings to a value that works as never (check Claude Code's docs for what it accepts).
- [ ] A nightly systemd user timer deletes top-level transcripts whose first record says `sdk-cli`, last modified more than 30 days ago, along with their subagent folder.
- [ ] A dry-run mode lists what would be deleted and deletes nothing; its output is checked by hand against at least one real old headless transcript before the timer is enabled.
- [ ] Interactive (`cli`) transcripts are never touched. A test covers that choice with fixture transcripts of both kinds.
- [ ] The timer is `enable`d and `systemctl --user is-enabled` prints `enabled`. The README says what is kept and what is deleted.
