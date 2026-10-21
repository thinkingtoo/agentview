# 02: Pastes stay, header count

**What to build:** a Paste survives its session: when the session finishes or is closed, its Pastes stay visible under that session's finished card until the person ticks them done. A count of waiting Pastes in the page header takes the person to the first one. No new sound. Spec: `docs/specs/2026-10-21-paste.md`.

**Blocked by:** 01 (One Paste end to end).


**Claimed by:** Bruno 2026-10-21 23:27

**Status:** in-progress

- [ ] Pruning finished or closed sessions never removes their Pastes; only done or withdrawn ones go
- [ ] A Paste of a closed session still shows, with copy and done working
- [ ] The header shows how many Pastes are waiting, and a click takes you to the first one
- [ ] The announce/chime logic is unchanged (existing sound tests stay green)
- [ ] Tests: through the roster seam (a session goes from live to finished, its Paste is still listed) and the UI smoke test (header count)
