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

**Status:** needs-triage
