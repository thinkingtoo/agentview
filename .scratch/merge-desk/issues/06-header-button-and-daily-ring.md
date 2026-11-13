# 06: The Merges header button and the daily ring

**What to build:** a header button "Merges <n>" beside the Pastes button: it lights none of the three counts; a click opens the desk page. Once a day at most, when the oldest item has waited more than 24 h, AgentView rings as for a session that needs the person, naming the desk.

**Blocked by:** 02

**Claimed by:** Suki 2026-11-13 23:33

**Status:** done

- [x] The button shows the number of items waiting, 0 hides it (tests/test_roster_route.py merges count; t-compute screenshot showed "Merges 2"; page test checks the 0-hides template)
- [x] The ring fires once per day, not on every poll round (tests/test_deskring.py once-a-day + restart; tests/test_desk_ring_page.py no second ring, failed stamp)
