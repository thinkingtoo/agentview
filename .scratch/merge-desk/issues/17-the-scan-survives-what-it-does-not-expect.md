# 17: The scan survives what it does not expect

**What to fix:** two follow-ups from ticket 12's review (Wanda, class c). (F3) deskscan catches only `Failed`/`OSError`; any other exception from gh output (bad JSON, a missing field) stops that day's scan. Catch per repo and per PR, log it, go on. (F4) found items written before ticket 12 carry no ships record and refuse for ever ("hand it over again"); none are live now, but tidy or the next scan should replace such a found item rather than leave it stuck.

**Also (Wanda, 12 round 2):** the press tells a found item by `by == deskscan.BY` exactly; rewording BY would make old found items pressable on any repo. Pin the string with a test (or store a `found: true` field in the ready record).

**Blocked by:** 12

**Claimed by:** Xavier 2026-11-14 02:47

**Status:** done

- [x] A gh answer with malformed JSON for one repo leaves the other repos' found items written (test with fake gh) — tests/test_deskscan.py Survives: malformed_json, unexpected error per PR (KeyError) and per repo (AttributeError); 201 pass with test_deskwatch
- [x] Changing deskscan.BY fails a test (or found items are told apart by a field, not by wording) — `found: true` on the ready record, plus test_the_wording_of_by_is_pinned; the by==BY fallback stays for ticket-12 records and is pinned too
- [x] A found item without a ships record is rewritten by the next scan with one — Survives.test_a_found_item_with_no_ships_record_is_rewritten...; only while unticked, no thread, no other log event
