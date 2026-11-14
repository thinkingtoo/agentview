# 13: "What ships" is compared exactly, not after stripping

**What to fix:** deskships._same normalises more than the page rewrites: `deploy_prod.sh` and `deployprod.sh` compare equal, and so does a command with or without a `<...>` span. A base branch that changed in exactly those characters between hand-over and press would pass the re-check. Unescape only a backslash before punctuation, strip only real tags, and map `_` to `*` (what sheaf writes). Found in 05's round 4 (Chiara, class b, /home/tiroir/Projects/agentview-wt/chiara-05-opus-4.md R4-1).

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] `deploy_prod.sh` changed to `deployprod.sh` between hand-over and press refuses the press
- [ ] A `<...>` span added to a deploy line refuses the press
- [ ] A line the page rewrote (escaped punctuation, `_` → `*`) still compares equal
