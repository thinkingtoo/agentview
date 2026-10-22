# 08: POST routes accept an Origin by prefix and skip the Host check

**What to build:** finding 2 of `/home/tiroir/Projects/agentview-wt/reviews/paste-codex-followup-2.md` (Codex, head 99d586f, VERIFIED). `_local()` (server.py:256-265) lets through any Origin that starts with `http://localhost` or `http://127.0.0.1`, e.g. `http://localhost.attacker.example`, and checks no Host; `_local_get` (server.py:267-273) has the Host check but only the Paste text GET uses it. With DNS rebinding a hostile page is same-origin, reads `/api/roster` and calls `paste_done` (and any other POST route in `ROUTES`, pre-existing). Compare the Origin host exactly (scheme, host, this server's port) and apply the Host check to POST; tests with `localhost.attacker.example` and a foreign Host.

**Blocked by:** None (can start immediately).

**Claimed by:** Habib 2026-10-22 13:20

**Status:** done (merged as dd3dbd4)

- [x] POST with Origin `http://localhost.attacker.example` and with a foreign Host is refused; tests fail on 99d586f (tests/test_local_guard.py: 24 failed before, 9 pass after)
- [x] The dashboard's own calls (127.0.0.1 and localhost, right port) still pass; live check after restart (see the report to the boss; filled in below)
- [x] Review GO on the fix (Codex round 3 on 5dc73ce, reviews/paste-08-codex-3.md), suite on t-compute green (2253 OK, 4 skipped)
