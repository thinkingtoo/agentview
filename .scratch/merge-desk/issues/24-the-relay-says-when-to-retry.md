# 24: The relay says when to retry, and its comment ops follow the hub's

**What to fix:** class c left by ticket 11 (Lucas, Sonnet round 1, /home/tiroir/Projects/agentview-wt/lucas-11-reviews-sonnet-1.md):
- The relay's 429 (stream cap) carries no Retry-After header.
- `COMMENT_OPS` in deskrelay.py is a copy of the hub's comment OPS with no guard: a sixth op added in sheaf would be refused by the relay without anyone noticing.
- Check once, on the real `tailscale serve` path, whether X-Forwarded-For reaches the relay (if not, every device shares one stream bucket of 6).
- From Codex on 11 (lucas-11-codex-1.md, finding 2, class c): `client_of` (deskrelay.py:276-283) trusts X-Forwarded-For, so a local program that reaches the relay directly can send a new value per stream and get past the 6-per-client cap (the total of 24 still holds). Trust the header only from the tailscale serve peer, or say in README why not.
  Also from Codex on 11 (lucas-11-codex-2.md, finding 2, class c, accepted by Tarek): the leader of a hub lookup returns its own late answer to its own request after a reset; that one request may use the obsolete port or cookie, gets a 503 at worst and the next one heals.
- From Codex on 11 (lucas-11-codex-3.md, finding 1, class c, Tarek): `SheafHub._locate` (deskrelay.py:219, :230) calls `unquote(errors="strict")` on `sheaf open` output; a malformed answer raises UnicodeDecodeError out of the handler instead of a 503. Catch it and raise `Refused(503)`.

**Blocked by:** 11

**Claimed by:** Anika 2026-11-14 15:22

**Status:** in-progress

- [x] A 429 from the stream cap carries Retry-After (test)
  Evidence: tests/test_desk_relay.py::StreamsThroughTheRelay::test_the_refusal_of_a_stream_past_the_cap_says_when_to_try_again (red before, green: Retry-After 30)
- [x] A test fails when sheaf's comment OPS and the relay's COMMENT_OPS differ
  Evidence: tests/test_desk_relay.py::TheHubsOps (mutation check: dropping `delete` from COMMENT_OPS fails it)
- [x] The X-Forwarded-For question answered with evidence (README)
  Evidence: README, merge desk from the phone, Streams are capped: tailscale serve sets X-Forwarded-For (serve.go addProxyForwardedHeaders, read 2026-11-14)
- [x] A malformed `sheaf open` answer gives a 503, not an exception (test)
  Evidence: tests/test_desk_relay.py::WhereTheHubIs::test_a_malformed_answer_of_sheaf_open_is_a_503_and_not_an_exception (red before, green)
- [x] A direct local client cannot widen the per-client cap with X-Forwarded-For (test), or README says why that is accepted
  Evidence: README: accepted, with the reason (the proxy and a local program both connect from 127.0.0.1; the total of 24 holds)
