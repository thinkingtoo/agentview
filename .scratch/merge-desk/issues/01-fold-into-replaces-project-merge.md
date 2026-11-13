# 01: "Fold into" replaces the project merge

**What to build:** the project action called "merge…" on a project card is renamed **Fold into…** everywhere the person reads it (card menu, the "includes X · undo" line, messages). The API route keeps working under its old path and gains `/api/fold`, so an open page of the old code still works. The word "merge" is then free for pull requests (GLOSSARY.md, already changed in this branch).

**Blocked by:** 02 (merged into dev first: both edit the same page code; boss brief, 2026-11-13)

**Claimed by:** Idris 2026-11-13 23:46

**Status:** done

- [x] No visible "merge" left for the project action (UI smoke test reads the card menu) — hand/picker/e2e/stale passes on t-compute: all OK incl. new "card menu says Fold into" check; Opus review round 1
- [x] `/api/fold` does what `/api/merge` did; `/api/merge` still answers the same
- [x] README's section on arranging projects says Fold into
