# 21: The concierge test reaches no concierge logic

**What to fix:** `test_a_concierge_holding_a_bosss_question_offers_its_command` patches `fleet._pane_roles` and asserts `tags == ["concierge"]`, but `guessed_commands_of` (`fleet.py:1278`) never reads tags or roles. It runs the same path as `test_an_open_question_still_offers_the_command_in_the_line`. Ticket paste/12's open point (a boss's command reached from the boss's card or the concierge's) is untested. Either test that point, or rename the test to what it shows (a concierge's own line is read like any other).

**Failing lines:** `tests/test_guessed_commands.py:174-182`:

```python
        fleet._pane_roles = lambda now=None: frozenset({"%2"})
        tile = self.question_open("Copy the key to the notes box. $ bash ~/notes/copy-key.sh",
                                  tmux="main:@1.%2")
```

**Class:** c.

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Claimed by:** Anton 2026-11-11

**Status:** done

- [x] Paste/12's open point is tested: one roster with a boss and its concierge holding the question, and the command on both cards
  The test is `test_a_bosss_command_is_on_its_card_and_on_its_concierges_holding_the_question` (case A of paste/12's sandbox table, as a unit test). It replaces `test_a_concierge_holding_a_bosss_question_offers_its_command`. No code changed: `guessed_commands_of` has no concierge path and needs none, so the new test is green on dev.
  Evidence, red (t-compute, mutation `if m["boss"]: return []` in `guessed_commands_of`, then reverted): the new test `FAIL`s with `(['boss'], 'line', [])`, and the old test (from origin/dev) passes against the same mutation.
  Evidence, green (t-compute): the same 297-test run as turn-hook-budget 07, "OK".

