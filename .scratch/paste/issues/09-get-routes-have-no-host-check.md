# 09: GET /api/roster (and the other GETs) have no Host check, so a rebinding page can read the roster

**What to build:** found while fixing ticket 08. `_host_ok` now guards every POST and the Paste text GET, but `do_GET` serves `/api/roster`, `/api/search` and the rest with no Host check. With DNS rebinding a hostile page is same-origin with the server and can read the roster (session names, folders, titles). Apply the Host check to every `/api/` GET and to the page itself, a foreign Host answered 403. The dashboard's own polls (127.0.0.1 and localhost, right port, and the portless Host on port 80) must keep working. The `X-Fleet` header is not required on GETs: the page's own polls do not send it.

**Blocked by:** None (can start immediately).

**Claimed by:** Habib 2026-10-22 13:22

**Status:** done

- [x] A test that a GET of `/api/roster` with a foreign Host is refused, failing on dd3dbd4; the same GET with a 127.0.0.1 or localhost Host still answers 200. Evidence: tests/test_get_host_guard.py, 27 failures on ea806ef's tree before the fix, all pass after.
- [x] Review GO on the fix, suite on t-compute green. Evidence: Codex GO on 1891709 (reviews/paste-09-codex-1.md); merged as cfb6943, suite on the merge tree 2262 OK, skipped 4.
- [ ] Live check on the restarted service: the dashboard loads and polls; a curl GET of `/api/roster` with a foreign Host gets 403
