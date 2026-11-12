# 01: An open overview tab keeps running the script it loaded

**What to fix:** `index.html` has no self-reload. A tab opened before an `agentview.service` restart keeps the old script for ever and never shows what shipped since. The page learns the version of the page the server serves (`build` in `/api/roster`, a hash of `index.html`) and reloads itself once when it differs from the one baked into the running script. It does not reload while the person has a field open, text in the filter or search box, or a focused input.

**Found in:** Thierry, 2026-11-12 19:2x: no hammers on any other project, while a fresh tab (Wilma, 19:22) showed them; her tab opened after the 19:12:19 restart. Notes: `handoff-Wilma-2026-11-12.md`.

**State that survives a reload:** the folded cards (`agentview.folded-tracks`, localStorage), the server-side marks and pins. State that does not: the filter and search boxes, an open inline field. The reload waits for those to be empty.

**Class:** b.

**Blocked by:** None.

**Status:** done
