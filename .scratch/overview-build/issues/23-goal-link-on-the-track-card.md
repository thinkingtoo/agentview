# 23: A track's card links to its goal page and shows its Done when list

**What to build:** on the overview, a track's card gets a "goal ↗" link to the sheaf page of `~/.claude/pm/<track>.goal.md` (editable: `sheaf open FILE --no-browser` prints `http://127.0.0.1:<hub port>/claude/pm/<track>.goal.md`, hub port read from `sheaf status`, the hub started when none runs), and, on hover or on a click that unfolds it, the `## Done when` boxes themselves, ticked and unticked, in the goal file's order. The card's text stays as it is: the person's own line first, else the Outcome paragraph, with "N of M" and the ETA (README, "What a project is about").

**Why (Thierry, 2026-11-10):** "op de kaarten van de boss een linkje naar een sheaf met de informatie van de bos track: wat de doelen zijn, een lijstje met de doelen". Today the card shows the Outcome only when no own line overrides it (`project_lines` in `config.json` does for sheaf-v2, ci-fast-feedback, action-list), and never the boxes, and nothing on it jumps to the goal.

**Where:** `context.py` `track_card` (what the server gives the card about a track), `fleet.py` where `track.progress` is built, `index.html` `progressOf` and the card markup; README section "What a project is about".

**Blocked by:** None (can start immediately).

**Claimed by:** none

**Status:** needs-triage

- [ ] The server gives a track's card the goal page URL and the Done when boxes (text, ticked), with a test on a goal file in a temp pm dir -- evidence: the test, red before the change
- [ ] The card shows "goal ↗" that opens that URL in a new tab, and the boxes on hover or unfold; a card whose own line overrides the Outcome still gets both -- evidence: a screenshot of a real track card
- [ ] No hub is started by the page or by the poll; the URL is built from the running hub's port, and without a hub the link says so instead of pointing at nothing -- evidence: test on the no-hub case
- [ ] README "What a project is about" says what the link and the list are
