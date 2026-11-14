# 24: The relay says when to retry, and its comment ops follow the hub's

**What to fix:** class c left by ticket 11 (Lucas, Sonnet round 1, /home/tiroir/Projects/agentview-wt/lucas-11-reviews-sonnet-1.md):
- The relay's 429 (stream cap) carries no Retry-After header.
- `COMMENT_OPS` in deskrelay.py is a copy of the hub's comment OPS with no guard: a sixth op added in sheaf would be refused by the relay without anyone noticing.
- Check once, on the real `tailscale serve` path, whether X-Forwarded-For reaches the relay (if not, every device shares one stream bucket of 6).
- From Codex on 11 (lucas-11-codex-1.md, finding 2, class c): `client_of` (deskrelay.py:276-283) trusts X-Forwarded-For, so a local program that reaches the relay directly can send a new value per stream and get past the 6-per-client cap (the total of 24 still holds). Trust the header only from the tailscale serve peer, or say in README why not.

**Blocked by:** 11

**Status:** ready-for-agent

- [ ] A 429 from the stream cap carries Retry-After (test)
- [ ] A test fails when sheaf's comment OPS and the relay's COMMENT_OPS differ
- [ ] The X-Forwarded-For question answered with evidence (README)
- [ ] A direct local client cannot widen the per-client cap with X-Forwarded-For (test), or README says why that is accepted
