# 05: Fixes from the review of the merged Paste code

**What to build:** the four findings of the bug hunt over tickets 01-04 as merged (head 45427d7), in `/home/tiroir/Projects/agentview-wt/reviews/paste-merged-codex-1.md` (Opus fallback, Codex unavailable). Verdict there was GO; finding 1 lets a secret reach the card in the clear, so it is fixed before the work counts as finished. Spec: `docs/specs/2026-10-21-paste.md`.

**Blocked by:** None (can start immediately).

**Claimed by:** Habib 2026-10-22 10:54

**Status:** done, merged as 826c48b

- [x] A token anywhere in a title, also past the clip length, is caught: the secret check runs on the whole title before it is clipped (paste.py:116-121), with a test whose token straddles the clip point (`Secrets.test_a_token_in_a_long_title_is_caught_before_the_title_is_clipped`, four lead lengths, fails on the old code; live: a title with 70 `x` and a fake token was refused, nothing echoed)
- [x] `copied` and `done` read the record patiently inside the lock (paste.py:301, 319): a slow read neither returns a false 404 nor lets a copy bring a done Paste back; a test with a slow first read (`Lifecycle.test_copy_and_done_are_not_fooled_by_a_slow_read_of_the_record` and `..._a_copy_that_joins_an_old_read_...`, both fail without `patient=True`)
- [x] A keyring put whose reply times out leaves no orphan item, or the command names the item so it is not silent (vault.py:124-125, paste.py:158-161); a test with the fake keyring (`vault.Unsure` for a `CreateItem` with no reply; paste takes the item back, else names it and `paste sweep`; tests `..._reply_is_lost_*`, `..._refused_outright_*`, Dbus `..._gets_no_reply_...`, each mutation-checked)
- [x] The possible bus connection leak when OpenSession fails (vault.py:52-63) is checked: fixed with a test, or shown harmless with the evidence (fixed: `_close_bus` in `__enter__`'s failure arm; `Dbus.test_the_connection_is_closed_when_opening_the_session_fails`)
- [x] Review GO on the merged head (Codex through `/codex-review`, Opus fallback at once if Codex is out), full suite on t-compute green, live service restarted and one throwaway secret Paste checked as in ticket 03 (`/home/tiroir/Projects/agentview-wt/reviews/paste-05-review-1.md`: Opus fallback, Codex exit 7, GO on 7e5e39f; suite on t-compute 2244 tests OK, skipped=4; live: restarted, throwaway `sk-test-` secret Paste showed `first: ""`, `secret: true`, text route 200 with `X-Fleet` and 403 without, store scan 0 hits, withdraw left the keyring clean)
