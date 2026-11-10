# 23: A track's card links to its goal page and shows its Done when list

**What to build:** on the overview, a track's card gets a "goal ↗" link to the sheaf page of `~/.claude/pm/<track>.goal.md` (editable: `sheaf open FILE --no-browser` prints `http://127.0.0.1:<hub port>/claude/pm/<track>.goal.md`, hub port read from `sheaf status`, the hub started when none runs), and, on hover or on a click that unfolds it, the `## Done when` boxes themselves, ticked and unticked, in the goal file's order. The card's text stays as it is: the person's own line first, else the Outcome paragraph, with "N of M" and the ETA (README, "What a project is about").

**Why (Thierry, 2026-11-10):** "op de kaarten van de boss een linkje naar een sheaf met de informatie van de bos track: wat de doelen zijn, een lijstje met de doelen". Today the card shows the Outcome only when no own line overrides it (`project_lines` in `config.json` does for sheaf-v2, ci-fast-feedback, action-list), and never the boxes, and nothing on it jumps to the goal.

**Where:** `context.py` `track_card` (what the server gives the card about a track), `fleet.py` where `track.progress` is built, `index.html` `progressOf` and the card markup; README section "What a project is about".

**Blocked by:** None (can start immediately).

**Claimed by:** Leire 2026-11-10

**Status:** needs-triage

- [ ] The server gives a track's card the goal page URL and the Done when boxes (text, ticked), with a test on a goal file in a temp pm dir -- evidence: the test, red before the change
- [ ] The card shows "goal ↗" that opens that URL in a new tab, and the boxes on hover or unfold; a card whose own line overrides the Outcome still gets both -- evidence: a screenshot of a real track card
- [ ] No hub is started by the page or by the poll; the URL is built from the running hub's port, and without a hub the link says so instead of pointing at nothing -- evidence: test on the no-hub case
- [ ] README "What a project is about" says what the link and the list are

## Comments

**Leire 2026-11-11, decisions:**

- **On the phone.** The sheaf hub listens on the laptop's 127.0.0.1 only, so the link would open nothing on the phone (tailscale serve) or on any page not served from loopback. There the card shows a greyed "goal on the laptop" with the reason on hover, the same way a tile with no terminal shows "no terminal". The boxes come from the server and show everywhere. The test is the page's own host (`location.hostname` is 127.0.0.1, localhost or [::1]), not the phone check `onPhone()`: a laptop browser reaching the dashboard over tailscale cannot open the hub either.
- **No hub started.** `sheaf open` starts a hub when none runs, so `goal_page.py` runs it only right after a `sheaf status`, in the same refresh, that said one runs, and only for a goal `sheaf list` does not show (an open records the page's settings anew, so a goal already rendered is read from the list). A hub that stops in the moment between those calls is started again by that open: the window is one subprocess wide. Closing it fully would mean speaking sheaf's private HTTP API with its key; not done.
- **The poll never waits for sheaf.** `sheaf status` took 1.4–1.8 s at load 20; all sheaf calls run in one background thread at a time, and the card says "asking sheaf" until the first answer.
- **Fixtures.** Every goal text in the tests is invented; no real goal file is copied into the repo.
