# 20: The answered-question check does not cover a turn that ends on the old line

**What to decide, then pin:** `guessed_commands_of` drops a line older than the last answer only under an open question (source `"question"`). paste/13 left source `"line"` unchanged on purpose. No test pins that choice, and it offers a stale command in two real cases:

1. The session writes `team-line --n 1 --ask 'Type this here: $ bash push.sh'`, opens Q1, the person rejects Q1 with Esc. A rejected question gets no Stop hook, so the line stays; the turn ends idle, source `"line"`, `guessedCommands == ['bash push.sh']` for a refused question.
2. Q1 is answered and the turn ends without a new line.

Either extend the `lineAt <= answeredAt` check to source `"line"`, or add a test that pins today's behaviour as intended.

**Failing lines:** `fleet.py:1294-1296`:

```python
    if (stuck["source"] == "question" and m["answeredAt"]
            and (m["lineAt"] or 0) <= m["answeredAt"]):
        return []
```

**Class:** c (traced, not run on a live session).

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Claimed by:** Nia 2026-11-11

**Status:** done

## Answer (Nia, 2026-11-11)

### Decision: today's behaviour is the intended one, now pinned

The answered-question check stays on source `"question"` only. Case 1 is the reason the rule exists: the turn hook asks for the line right before an AskUserQuestion because "a rejected question gets no Stop hook" (`hooks/turn_line.py`, `ASK`). The line written before Q1 is meant to be the turn's last line, so that a rejected question still leaves a card that says what is left. A command in it (`bash push.sh`) is still left for the owner after an Esc; dropping it would empty the copy button the rule was written to fill. Case 2 is the same line seen after an answer, with no new line to replace it: the card already says "1 thing left for you" with that ask as its text, so dropping only the command would leave a card that names a command it does not offer. paste/13 changed nothing here on purpose: "The `"line"` source (turn over, no dialog) is unchanged; the ticket was about the question."

### Evidence

- **Test** (`tests/test_guessed_commands.py`): `test_a_turn_over_after_an_answered_or_rejected_question_keeps_its_command`. A line with `n` 1 and `$ bash ~/notes/push-maple.sh`, a session with no open dialog and `answeredAt` after the line: `("line", ["bash ~/notes/push-maple.sh"])`. Green on the current code, as a pin is.
- **It bites:** with the check widened to every source (`if (m["answeredAt"]` at `fleet.py:1294`, on a copy on t-compute) it fails with `- ('line', [])` / `+ ('line', ['bash ~/notes/push-maple.sh'])`.
- `test_guessed_commands` + `test_ask` on t-compute: 155 OK, `fleet.py` and `ask_commands.py` resolved to the clone.
