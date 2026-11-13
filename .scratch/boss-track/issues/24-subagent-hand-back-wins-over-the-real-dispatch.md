# 24: A subagent's hand-back is taken for the dispatch

**Status:** done

**What happened:** On the action-list card at 01:39 a worker (Naya) showed "[Subagent hand-back] The text below is the final report of a subagent...". Ticket 22's `_dispatch` keeps the newest record whose `origin.kind` is `peer`; a subagent's hand-back is also such a record, so it replaced the real dispatch.

**Decision (Tarek, boss of agentview, 2026-11-13):** the dispatch line comes only from a message sent by another session, never from the session's own subagent. Told apart by the record's origin fields, not by the "[Subagent hand-back]" prefix (wording that can change).

**Observed (real transcripts, 2026-11-13, 400 newest, 1079 peer records):** the two kinds never share a field set.

| | message from a session | subagent hand-back |
| --- | --- | --- |
| `origin.from` | `uds:/run/user/1000/cc-socks/<pid>.sock` (915 of 915), or `bridge:session_...` | bare agent id, e.g. `a44e12ae3b804c2f3` (164 of 164) |
| `origin.senderTaskId` | absent | present, equals `from` |
| `origin.fromMode` | `prompting` (all) | absent |
| `origin.verifiedPeerPid`, `msg_id` | present on `uds:` senders, absent on `bridge:` | absent |
| `origin.handback` | absent | `true` (163 of 164; one older record lacks it) |

So `handback` alone is not enough (one record lacks it). **The field that separates them is `origin.senderTaskId`: present on every subagent record, on no session record.** A session's `from` is a `uds:` socket address, or `bridge:session_...` for a session on another machine (Codex review 1 counted 43 such records, all with `fromMode: prompting` and no `senderTaskId`; 36 `bridge:` records, in two transcripts; they carry `body, from, fromMode, kind, name` and no `verifiedPeerPid` or `msg_id`); a subagent's `from` is its agent id. Rule: a record is a session's message when `from` is present and `senderTaskId` is absent. A first version required the `uds:` prefix and dropped bridge senders.

**Part two, display order (amends ticket 21 and 22; revised by Tarek, 2026-11-13, after Codex review 1):** the words shown after a worker's name are, in this order:

1. the worker's own did
2. the roster cell
3. the first line of its newest real dispatch (a session's message, per the rule above)
4. the card title / the first line of the last prompt
5. "working"

Reason (1 line): the cell is the boss's statement of the task and keeping it current is the boss's job, so a dispatch fills in only where no cell exists (a stamped worker without a cell, another boss's worker).

**A dispatch never places a worker (Tarek):** the newest message can be an ack ("GO", "thanks", "slice 2 accepted") that names a ref. Only the cell, or the worker's own did where it already does, places a worker on a ticket or a row. The dispatch is carried by `own_lines` for display only and is not part of the task that `workers` hands to `rows` (`_own_words` no longer reads it). The cell still decides which ticket and row a worker sits on, and an idle cell still keeps it off the card.

An earlier version of this ticket put the dispatch above the cell and let it into `_own_words`; Codex review 1 showed an ack outranking a fresh cell and placing a worker on a row, and the order was reversed.

- [x] A subagent hand-back never becomes the dispatch, whatever its text; the previous session message stays -- evidence: `tests/test_fleet.py` class `Summary`
- [x] A message from a session still gives its first line, as before -- evidence: `test_the_newest_message_from_a_peer_session_gives_its_first_line`
- [x] Order did > cell > dispatch > title/prompt > working -- evidence: `tests/test_objectives.py` `test_the_words_shown_run_did_then_cell_then_dispatch_then_title`
- [x] A dispatch never places a worker on a ticket or row -- evidence: `test_a_dispatch_never_places_a_worker_on_a_ticket_or_a_row`
- [x] The cell still places the worker on its ticket and an idle cell still keeps it off the card -- evidence: the two ticket 21 tests, unchanged

**Known limit (Codex review 1):** the dispatch is the newest message from a session, not the first. Later messages from other workers ("thanks", "slice 2 accepted") replace it, and now rank above the cell, and, for a stamped worker with no cell, above the title; the text of a message that names a `feature/NN` ref can place the worker on that row. Resolved by Tarek's decision above: the dispatch is below the cell and places nobody, so an ack can only show where the worker has no cell.

**Known limit (ticket 21, narrowed by the ruling):** a worker's did stays until it writes another, and for a worker with no cell the dispatch stays until a newer message arrives, so a card can show an old task. A cell, when there is one, beats the dispatch. A dispatch older than the transcript tail is not found (ticket 22).
