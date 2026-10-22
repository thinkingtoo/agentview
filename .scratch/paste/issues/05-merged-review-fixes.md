# 05: Fixes from the review of the merged Paste code

**What to build:** the four findings of the bug hunt over tickets 01-04 as merged (head 45427d7), in `/home/tiroir/Projects/agentview-wt/reviews/paste-merged-codex-1.md` (Opus fallback, Codex unavailable). Verdict there was GO; finding 1 lets a secret reach the card in the clear, so it is fixed before the work counts as finished. Spec: `docs/specs/2026-10-21-paste.md`.

**Blocked by:** None (can start immediately).

**Claimed by:** Habib 2026-10-22 10:54

**Status:** in-progress

- [ ] A token anywhere in a title, also past the clip length, is caught: the secret check runs on the whole title before it is clipped (paste.py:116-121), with a test whose token straddles the clip point
- [ ] `copied` and `done` read the record patiently inside the lock (paste.py:301, 319): a slow read neither returns a false 404 nor lets a copy bring a done Paste back; a test with a slow first read
- [ ] A keyring put whose reply times out leaves no orphan item, or the command names the item so it is not silent (vault.py:124-125, paste.py:158-161); a test with the fake keyring
- [ ] The possible bus connection leak when OpenSession fails (vault.py:52-63) is checked: fixed with a test, or shown harmless with the evidence
- [ ] Review GO on the merged head (Codex through `/codex-review`, Opus fallback at once if Codex is out), full suite on t-compute green, live service restarted and one throwaway secret Paste checked as in ticket 03
