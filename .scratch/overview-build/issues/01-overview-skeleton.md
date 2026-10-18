# 01: Overview skeleton

**What to build:** The main page shows one column per project instead of today's blocks. The roster gains a `columns` list beside today's `blocks` (expand: nothing that reads `blocks` changes). Projects use today's grouping for now. Each column has a plain project card (name only) and one tile per session carrying today's data (name, flag, line, jump). Columns keep a 230 px minimum width and scroll sideways. The chime, search, closed and reopen keep working untouched. This is the tracer bullet every other ticket builds on; see the build spec's roster contract.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `roster()` returns `columns` in display order next to the unchanged `blocks`; tested with fake providers
- [ ] The page renders columns from `columns` only, with no grouping or ordering logic in the browser
- [ ] Columns never change each other's height; with more projects than fit, the page scrolls sideways
- [ ] The chime still rings on `waiting`, and search, closed and reopen behave as before (smoke run by hand)
