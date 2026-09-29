# 01: Keep interactive transcripts forever, delete headless ones after 30 days

**What to build:** Claude Code stops deleting old transcripts, so every interactive conversation stays reopenable and searchable. Headless (`entrypoint: sdk-cli`) transcripts, which are about three quarters of them, are deleted by a nightly job once they are older than 30 days. That keeps disk growth down to your own sessions. Spec: `docs/specs/2026-09-29-conversation-archive.md` (decisions table and measured facts).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `cleanupPeriodDays` is set in the user settings to a value that works as never (check Claude Code's docs for what it accepts).
- [ ] A nightly systemd user timer deletes top-level transcripts whose first record says `sdk-cli`, last modified more than 30 days ago, along with their subagent folder.
- [ ] A dry-run mode lists what would be deleted and deletes nothing; its output is checked by hand against at least one real old headless transcript before the timer is enabled.
- [ ] Interactive (`cli`) transcripts are never touched. A test covers that choice with fixture transcripts of both kinds.
- [ ] The timer is `enable`d and `systemctl --user is-enabled` prints `enabled`. The README says what is kept and what is deleted.

## Baseline: interactive transcripts before the timer

No record in a transcript's first line carries an `entrypoint` (the first
lines are `queue-operation`, `ai-title`, `last-prompt`, `mode`), so "first
record says" is counted as the first record that names an entrypoint, at
line 2 to 10. Across 2,247 transcripts no file mixes the two values.

```bash
python3 - <<'PY'
import glob, json, os
n = 0
for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
    for line in open(f, errors="replace"):
        try: e = json.loads(line).get("entrypoint")
        except (ValueError, AttributeError): continue
        if e: n += e == "cli"; break
print(n)
PY
```

| When | `cli` transcripts | Note |
|---|---|---|
| 2026-09-29 12:37:37 | 534 | Right after `cleanupPeriodDays` was set. The list of paths is kept outside the repo, so later counts are compared file by file, not only by number. |
| 2026-09-29 13:06:29 | 538 | All 534 from 12:37 still present, 4 new. |
