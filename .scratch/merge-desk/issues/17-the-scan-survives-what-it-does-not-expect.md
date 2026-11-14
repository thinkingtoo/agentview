# 17: The scan survives what it does not expect

**What to fix:** two follow-ups from ticket 12's review (Wanda, class c). (F3) deskscan catches only `Failed`/`OSError`; any other exception from gh output (bad JSON, a missing field) stops that day's scan. Catch per repo and per PR, log it, go on. (F4) found items written before ticket 12 carry no ships record and refuse for ever ("hand it over again"); none are live now, but tidy or the next scan should replace such a found item rather than leave it stuck.

**Blocked by:** 12

**Status:** ready-for-agent

- [ ] A gh answer with malformed JSON for one repo leaves the other repos' found items written (test with fake gh)
- [ ] A found item without a ships record is rewritten by the next scan with one
