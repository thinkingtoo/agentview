# 07: The desk opens and presses from the phone

**What to build:** the desk page reached through AgentView's tailnet origin (`tailscale serve` :8445, the FleetView link in Open WebUI's rail): AgentView relays the page and its `/_/` routes to the laptop's sheaf hub (which answers only on 127.0.0.1), rewriting Host and Origin as the chat box's ticket 03 relay did. Presses from the phone work like presses on the laptop.

**Blocked by:** 02

**Claimed by:** Sigrid 2026-11-13 23:56

**Status:** done

- [x] The relay serves only the desk page and the routes it needs, not every sheaf document
  Branch `sigrid/07-desk-from-phone` (80cbbb2, not merged). `deskrelay.plan` allows the desk document, `GET /_/doc` and `/_/live`, `POST /_/tick`, `/_/comment`, `/_/seen`, each only with the desk's address; a comment with `tell` is refused. Proof: `tests/test_desk_relay.py` (26 tests, nine guard mutations tried: seven caught at once, one tightened test caught the eighth, the ninth (Host rewrite) is equivalent because http.client sets the same Host), and a private sheaf hub (46421) with its own server: page, doc, stream and a press ticked the box; other document, `/_/index.json`, `/_/save` answered 404; no Origin or a foreign one answered 403. Reviews: Opus rounds 1-3, files in /home/tiroir/Projects/agentview-wt/sigrid-07-reviews.md.
- [x] Checked by Thierry on his phone (the box below is his)
  - Evidence: Thierry via the concierge, 2026-11-14: q1 "Im on mobile, where can I click on agentview?", q3 answered after opening https://tiroir-xps-15-7590.tail23d36e.ts.net:8445/desk (tailnet relay, verified 302 → 200), addendum "There were 2 merge buttons. First one 274 returned GitHub conflict, second one 151 merged"
- [x] Thierry: a press on the phone merged a PR
  - Evidence: merge-desk.log 01:25:28 pressing sweatshop-ai/claude-boss#151 (pinned 8587d12) → 01:25:33 merged as 2cb8cb4; the refusal path also ran from the phone (sheaf#274 01:25:07 and 01:25:42, GitHub says CONFLICTING)
