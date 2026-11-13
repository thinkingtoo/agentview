# 07: The desk opens and presses from the phone

**What to build:** the desk page reached through AgentView's tailnet origin (`tailscale serve` :8445, the FleetView link in Open WebUI's rail): AgentView relays the page and its `/_/` routes to the laptop's sheaf hub (which answers only on 127.0.0.1), rewriting Host and Origin as the chat box's ticket 03 relay did. Presses from the phone work like presses on the laptop.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] The relay serves only the desk page and the routes it needs, not every sheaf document
- [ ] Checked by Thierry on his phone (the box below is his)
- [ ] Thierry: a press on the phone merged a PR
