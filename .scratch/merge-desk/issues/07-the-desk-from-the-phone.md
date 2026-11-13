# 07: The desk opens and presses from the phone

**What to build:** the desk page reached through AgentView's tailnet origin (`tailscale serve` :8445, the FleetView link in Open WebUI's rail): AgentView relays the page and its `/_/` routes to the laptop's sheaf hub (which answers only on 127.0.0.1), rewriting Host and Origin as the chat box's ticket 03 relay did. Presses from the phone work like presses on the laptop.

**Blocked by:** 02

**Claimed by:** Sigrid 2026-11-13 23:56

**Status:** in-progress

- [x] The relay serves only the desk page and the routes it needs, not every sheaf document
  Branch `sigrid/07-desk-from-phone` (80cbbb2, not merged). `deskrelay.plan` allows the desk document, `GET /_/doc` and `/_/live`, `POST /_/tick`, `/_/comment`, `/_/seen`, each only with the desk's address; a comment with `tell` is refused. Proof: `tests/test_desk_relay.py` (26 tests, nine guard mutations tried: seven caught at once, one tightened test caught the eighth, the ninth (Host rewrite) is equivalent because http.client sets the same Host), and a private sheaf hub (46421) with its own server: page, doc, stream and a press ticked the box; other document, `/_/index.json`, `/_/save` answered 404; no Origin or a foreign one answered 403. Reviews: Opus rounds 1-3, files in /home/tiroir/Projects/agentview-wt/sigrid-07-reviews.md.
- [ ] Checked by Thierry on his phone (the box below is his)
- [ ] Thierry: a press on the phone merged a PR
