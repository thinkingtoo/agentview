# 02: Keyword search across all interactive conversations

**What to build:** a search box on the agentview page, next to **⟲ closed N**. You type words and get back one row per matching interactive conversation, from any day, running ones included. Each row shows the conversation's name, Claude's title, the project, the date, and the exchange that matched. Spec: `docs/specs/2026-09-29-conversation-archive.md` (decisions table and measured facts).

This is the tracer bullet: the index, the job that keeps it current, the endpoint and the UI, end to end.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] One piece of the index is one exchange: a prompt the user typed plus the assistant's reply text. `<system-reminder>` blocks, hook injections and tool calls and results are stripped. Unit tests on a fixture transcript cover the stripping.
- [x] Only `entrypoint: cli` transcripts are indexed. Headless and subagent transcripts are not.
- [x] The index is one SQLite file (FTS5) under `~/.claude/agentview/`. Nothing is sent off the machine.
- [x] A timer updates it every few minutes and only reads transcripts that changed (tracked by size and mtime, or by offset). A first run over all ~525 conversations finishes and reports how long it took.
- [x] The search endpoint groups hits by conversation, ranked by the best passage, and returns name, title, project, date and the matching passage. The title comes from the same `ai-title` reader the closed list already uses.
- [x] Clicking a result is not wired up here (that is ticket 03). The row says what the conversation is and does not pretend to be clickable.
- [x] The poll stays fast: search is a separate request, never part of the roster poll.
- [x] The README has a section on search.

## Comments

**Closing note (Ronja, 2026-09-29).** Built on `feat/02-keyword-search`; the code is `archive.py`, the `/api/search` route in `server.py`, the search box in `index.html`, and `agentview-archive.{service,timer}`. Evidence per box:

1. **Exchanges, stripped.** `tests/test_archive.py` runs on a made-up transcript with one of every record kind. `test_machine_text_never_reaches_the_index` checks that hook output, `<system-reminder>`, thinking, tool calls and results, skill bodies, peer messages, local-command output, sidechain and synthetic text never reach a passage. On the real index: `0` passages contain `<system-reminder>`, `tool_use_id`, `<command-name>` or `pasted_content`. What is kept is all 15.88 MB of assistant text and 0.44 MB of typed prompts. The spec's 41 MB also counted 13.3 MB of peer and task-notification messages and 11.8 MB of skill bodies and meta records, which the ticket leaves out.
2. **`cli` only.** `test_only_interactive_transcripts_are_indexed`: an `sdk-cli` transcript lands in `skipped`, and a `subagents/` transcript is never listed. Live: `2,250` transcript files, `534` indexed.
3. **One local file.** `~/.claude/agentview/archive.db`, SQLite FTS5, mode `600` (`test_the_index_is_as_private_as_the_transcripts`); no network code anywhere in `archive.py`.
4. **Timer, changed files only, first run timed.** Unchanged `(size, mtime)` is skipped (`test_an_unchanged_transcript_is_not_read_again`); a growing file is read from the start of its last exchange (`test_a_growing_conversation_is_read_from_its_last_exchange`, `test_a_small_file_that_grows_is_appended_to_not_rebuilt`); a rewrite is read from scratch (three tests). First full run, 2026-09-29 12:47: `534 of 534 conversations read, 7629 passages, 18.97s`, peak 73 MB. A rebuild at load 1.7 took 19.12 s; a run with nothing new, about 0.15 s.
5. **Grouped, ranked, fields, same title reader.** `test_one_row_per_conversation_best_passage_first`, `test_one_conversation_with_many_hits_cannot_crowd_out_the_rest`, `test_a_row_says_what_the_conversation_is`. The title comes from `claude.last_title`, the closed list's reader moved out of `server.py` so both call the same function (`test_the_title_is_the_closed_lists_title`).
6. **Not clickable.** The rows are `div.hit`, with no button and no hover state. Playwright on the page reads `cursor: default`.
7. **Separate request.** `/api/search` is its own GET route; `/api/roster` does not touch the index. `test_search_answers_with_rows_and_the_state_of_the_index` goes through the real route over HTTP.
8. **README.** New section `## Search`, plus the timer in `## Run it`.

Tested before the merge on a second server from the worktree (port 8766, its own log directory), leaving the live one alone: `curl 'http://127.0.0.1:8766/api/search?q=processori'` returned `Ansgar | Processori a 800Mhz`, last active `2026-09-22T07:26`.

Codex (`codex exec -s read-only` over the diff against `dev`): review 1 said NO-GO with three findings, fixed in `0717bbf`. Review 2 said NO-GO with four, fixed in the next commit. Both reviews and the verdict that let this merge are named in the report to the boss.

Left out on purpose: peer and task-notification messages are not indexed (the reply to them is). Names come from peer files, then agentview's own log, then the transcript's `agent-name` record. On 2026-09-29 the log named all 532 interactive conversations, and the transcripts alone named 18. The index keeps a name once it is found, so it outlives the log's rotation.
