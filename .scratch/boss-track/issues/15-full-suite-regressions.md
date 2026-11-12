# 15: five tests red on dev that no PR's own run showed

**What to build:** make the full suite green again at `26b4c99`. Bisected on t-compute (the three files at each merge): green at `271228c` (before PR 33) and `b35dff1`; `test_context` red from PR 35 (`b62c706`), which added `elsewhere: []` to the track dict without updating two expectations; `test_attach` / `test_finished_route` red from PR 40 (`6300a68`), whose `fleet._read_panes` runs `tmux list-panes` and trips the click servers' `subprocess.run` guard (which test hits it first depends on the 5 s cache, so the named errors vary by run).
- the two `test_context` expectations carry `"elsewhere": []`;
- `ClickServer` patches `fleet._read_panes` like it patches the other real readers; the guard stays.

**Blocked by:** none

**Status:** ready-for-agent

- [x] The five tests are red before the fix and green after -- evidence: t-compute runs
- [x] Full suite green at the PR head -- evidence: summary line in the PR
