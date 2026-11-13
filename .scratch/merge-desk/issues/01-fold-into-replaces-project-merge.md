# 01: "Fold into" replaces the project merge

**What to build:** the project action called "merge…" on a project card is renamed **Fold into…** everywhere the person reads it (card menu, the "includes X · undo" line, messages). The API route keeps working under its old path and gains `/api/fold`, so an open page of the old code still works. The word "merge" is then free for pull requests (GLOSSARY.md, already changed in this branch).

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] No visible "merge" left for the project action (UI smoke test reads the card menu)
- [ ] `/api/fold` does what `/api/merge` did; `/api/merge` still answers the same
- [ ] README's section on arranging projects says Fold into
