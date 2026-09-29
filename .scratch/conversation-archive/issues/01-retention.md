# 01: Keep interactive transcripts forever, delete headless ones after 30 days

**What to build:** Claude Code stops deleting old transcripts, so every interactive conversation stays reopenable and searchable. Headless (`entrypoint: sdk-cli`) transcripts, which are about three quarters of them, are deleted by a nightly job once they are older than 30 days. That keeps disk growth down to your own sessions. Spec: `docs/specs/2026-09-29-conversation-archive.md` (decisions table and measured facts).

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] `cleanupPeriodDays` is set in the user settings to a value that works as never (check Claude Code's docs for what it accepts).
- [x] A nightly systemd user timer deletes top-level transcripts whose first record says `sdk-cli`, last modified more than 30 days ago, along with their subagent folder.
- [x] A dry-run mode lists what would be deleted and deletes nothing; its output is checked by hand against at least one real old headless transcript before the timer is enabled.
- [x] Interactive (`cli`) transcripts are never touched. A test covers that choice with fixture transcripts of both kinds.
- [x] The timer is `enable`d and `systemctl --user is-enabled` prints `enabled`. The README says what is kept and what is deleted.

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
| 2026-09-29 13:33:43 | 541 | Right before the first real run. |
| 2026-09-29 13:34:01 | 542 | Right after it. All 534 baseline paths present, none lost since 13:33:43, 1 new. |

## Comments

**Closing note (2026-09-29).** Built on `feat/01-retention`. The code is `retention.py`, `agentview-retention.{service,timer}` and `tests/test_retention.py`; the README has a section, `## Which transcripts are kept`. Evidence per checkbox. Real conversation names, titles and paths are left out of this note because the repo is public; they are in the private evidence file kept by the boss session.

1. **`cleanupPeriodDays`.** The settings reference says "Setting `0` fails validation, so pick a large value such as `3650` for long retention", with a minimum of 1. There is no "never". Set to `36500` (a hundred years). The change to `~/.claude/settings.json` is one line and nothing else:
   ```
   $ git -C ~/.claude diff --stat settings.json
    settings.json | 1 +
   +  "cleanupPeriodDays": 36500,
   ```
2. **Nightly timer.** `agentview-retention.timer`: `OnCalendar=*-*-* 03:30`, `Persistent=true`, `RandomizedDelaySec=10min`, running `retention.py --delete`. It deletes a top-level transcript with its session folder when it is 30 days old and every record that names an entrypoint says `sdk-cli`. It reads the whole file, not only the first record, because no record in a transcript's first lines carries an entrypoint (see the baseline above).
3. **Dry run, checked by hand before the timer.** `python3 retention.py --dry-run` on 2026-09-29 13:33 listed 5 transcripts and deleted nothing:
   ```
   2026-08-30       0.3 MB  <transcript>
   2026-08-30       0.2 MB  <transcript>
   2026-08-30       0.2 MB  <transcript>
   2026-08-30       0.4 MB  <transcript>
   2026-08-30       0.2 MB  <transcript>
   would delete 5 headless transcripts older than 30 days, 1.3 MB
   ```
   Each was opened and read: 5 headless routine transcripts, last written 2026-08-30 (between 11:58 and 13:20), every entrypoint record `sdk-cli` (51 to 83 of them, no other value), two with a session folder. The first hand check was on the first three, before anything was enabled.
4. **`cli` never touched.** `tests/test_retention.py` builds fixture transcripts of both kinds. `test_an_old_headless_transcript_goes_with_its_folder_and_an_old_interactive_one_stays` is the base case; around it are a transcript that is interactive and later carried on headless, one naming no entrypoint, one with a line that does not parse, one with a line too large or nested too deep to read, and one rewritten in place with the same size and mtime. All stay. 344 tests pass on `dev` (the one that failed before this work was fixed by ticket 06).
5. **Timer enabled, first run.**
   ```
   $ systemctl --user is-enabled agentview-retention.timer
   enabled
   $ systemctl --user list-timers agentview-retention.timer
   NEXT                         LEFT LAST PASSED UNIT                      ACTIVATES
   Wed 2026-09-30 03:34:44 CEST  14h -         - agentview-retention.timer agentview-retention.service
   $ systemctl --user start agentview-retention.service     # the timer's first run is tonight; this is the same unit, once, now
   $ journalctl --user -u agentview-retention.service
   Starting agentview-retention.service ...
   2026-08-30       0.3 MB  <transcript>          (5 lines, as in the dry run)
   deleted 5 headless transcripts older than 30 days, 1.3 MB
   Finished agentview-retention.service ...        Result=success ExecMainStatus=0
   ```
   Afterwards: the 5 transcripts and their folders are gone, `find ~/.claude/projects -name '*.retention-*'` finds nothing, and a dry run says `would delete 0 headless transcripts older than 30 days`.

**The count.** The command is in the baseline section. Before the first real run: 541. After it: 542. The 534 paths listed at 12:37 are all still present (534 of 534), none was lost between the two counts, and one conversation is new. The number must not fall below 534 after tonight's 03:34 run either; recount then.

**Codex review.** Nine rounds (`codex exec -s read-only`, output in `~/.claude/pm/reviews/codex-review-01*.md`). Rounds 1 to 5 were NO-GO and every finding was fixed: a line that does not parse now keeps the transcript, the file is renamed aside and read again before it is deleted, projects are worked on through directory handles opened without following links, a transcript is put back without overwriting anything, a session folder is checked for a mounted filesystem. Round 6 found a `MemoryError` from `readline()` and round 7 found exceptions that could stop the run; both fixed, the second by handling every transcript on its own. Round 8 found that `rmtree` can stop halfway on a healthy disk and lose files it had already deleted; fixed by looking over the whole session folder before deleting any of it. No round found a path to a deleted interactive transcript that needed no attacker.

Round 9 (`~/.claude/pm/reviews/codex-review-01-round9.md`) ended `VERDICT: NO-GO`, on one finding: a file marked immutable (`chattr +i`) inside a session folder passes the preflight, and the delete stops there. The declared scope, given for rounds 8 and 9:

> The verdict counts only (a) any path by which an interactive (cli) transcript, or anything outside a session folder, could be deleted, and (b) any crash or data loss under normal conditions: a healthy disk, normal memory, an ordinary laptop. Findings that need a same-user attacker, memory exhaustion, or a disk failing twice go in a separate section and do not count toward the verdict.

The boss session's ruling, verbatim (the address line and the instructions that follow it are left out):

> option 1. My reasoning, for the record: setting chattr +i needs root or CAP_LINUX_IMMUTABLE, so it is not a "normal condition" under (b). Codex put it in the wrong section. Under the declared scope, round 9 has no finding that counts, so I treat it as GO under scope. What would be lost are only files of a headless session over 30 days old, which the job deletes anyway, and your count is 0 of 6,572 entries.

The 6,572 is the number of entries under `~/.claude/projects` checked with `lsattr -R` on 2026-09-29; none had an `i` or `a` flag.

**Limits accepted under that ruling**, all in the README: an immutable file in a session folder (the delete stops there, the transcript is put back, the next night tries again); an empty read-only directory (refused although it could go, so the session is kept); a filesystem mounted inside a session folder between the preflight and the delete, and a transcript rewritten through a descriptor a process of yours kept open (both need a process of yours doing it on purpose); and a disk that fails during the delete and again during the put-back (leaves the session under a `.retention-` name, and the warning names it).

**Merged.** `dev` fast-forwarded from `3d87362` to `9035858` (12 commits) and pushed; the repo has no CI, so GitHub reports 0 check runs for the commit and nothing ran.
