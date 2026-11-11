# 06: A long id that SAFE accepts puts the instruction over its 2150 ceiling

**What to fix:** the id is formatted into `ASK` three times and `lines.SAFE` allows 80 characters, so the ceiling holds only for ids up to 70. Either the ceiling test uses the longest id `SAFE` accepts, or the text names the id fewer times.

**Input:** `{"session_id": "x"*71}` with the live hooks path `/home/tiroir/Projects/agentview/hooks`.

**Measured at 17386f1:** UUID (36) 2050; 71 chars 2155; 80 chars 2182.

**Failing lines:** `hooks/turn_line.py:72` `ASK.format(writer=WRITER, paste=PASTE, sid=sid)` with `lines.py:42` `SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")`.

**Class:** b (only a non-UUID id gets there).

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Claimed by:** Nadia 2026-11-11

**Status:** done

- [x] The ceiling test measures the longest id `SAFE` accepts, and the text fits under 2150 with it; the ceiling stays 2150 and every rule stays
  Evidence, red (t-compute, before the fix): `FAIL: test_the_ceiling_holds_for_the_longest_id_the_store_accepts`, `AssertionError: 2179 not less than 2150 : 2179`.
  Evidence, green (t-compute, after): `tests.test_turn_hook` "Ran 28 tests in 2.736s" / "OK".
  Sizes after the fix (id length: test path / live path `/home/tiroir/Projects/agentview/hooks`): 36: 2009 / 2012; 71: 2114 / 2117; 80: 2141 / 2144.
  Cut, no rule dropped: "a command for them to run, a mail for them to send" became "a command to type, a mail to send"; "the clipboard in so many words" became "the clipboard by name"; "else a mktemp -d directory" became "else mktemp -d". The new test also fails if `SAFE` ever accepts an 81st character, so it keeps measuring the longest id.
