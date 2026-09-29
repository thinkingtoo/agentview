# 03: A click on a search result reopens or jumps

**What to build:** clicking a search result brings that conversation to the front. If it is running, the page focuses its pane or tab, the same as a click on a live row. If it is closed, it is resumed in a new WezTerm tab, in its old directory, with its old permission mode and name. That works even for conversations older than any snapshot: only the last 60 snapshots are kept, currently going back to 2026-09-27. Spec: `docs/specs/2026-09-29-conversation-archive.md` (decisions table and measured facts).

**Blocked by:** 02: Keyword search across all interactive conversations

**Status:** resolved

- [x] A running conversation is never resumed a second time. Its row jumps.
- [x] For a closed conversation, the revive record comes from its latest snapshot when there is one. Otherwise it is built from the transcript: the `cwd` and the last `permissionMode` (mapped to the matching `claude` flag). Unit tests cover both paths.
- [x] The conversation's name comes back through the same name-seeding the closed list uses, when a name is known.
- [x] When the directory no longer exists, the row says so and nothing is launched.
- [x] Each revive is logged as the closed list's revives are.
- [x] Clicking a result for a conversation that is already running focuses its existing tab and opens no second one. Tabs are counted before and after.
- [x] A conversation last active before 2026-09-27 (older than every snapshot) reopens under its old name.

## Comments

**Closing note (2026-09-29).** Built on `feat/03-reopen`. The code is `snapshot.py` (`revive_record`, `transcript_facts`, `starting`), the `/api/reopen` route and `reopen()` in `server.py`, `archive.name_of`, and the clickable rows in `index.html`. Evidence per box:

1. **Never twice.** A click asks the same registry a live row's jump uses. If the conversation runs, the row jumps (`fleet.jump_to`) and nothing is opened. Three things keep a second click from opening it again: clicks are answered one at a time under a lock, a claude launched with `--resume <id>` that has no peer file yet counts as starting (`snapshot.starting`; one that has a peer file is the registry's to answer for, so a session that moved on with `/resume` does not block the old id), and a 30 s grace covers the moment before the new process exists. Tests: `test_a_running_conversation_jumps_and_is_never_resumed_again`, `test_two_clicks_at_the_same_moment_open_one_tab` (two threads, a slow launch), `test_a_second_click_while_the_first_is_starting_opens_nothing_more`, `test_a_claude_launched_for_it_that_is_still_starting_is_not_resumed_again`, and three `Starting` tests over a fake `/proc`.
2. **Snapshot, else transcript.** `snapshot.revive_record` takes the newest snapshot that had the conversation, from whichever boot. Without one, `transcript_facts` reads the transcript: the directory it is filed under (`--resume` looks under that one, and a conversation that moved is filed under the directory it started in) and the last `permissionMode`, asked for as `--permission-mode <mode>`. `default` is asked for by name, `manual` (the cli's other spelling) maps to `default`, and a mode the cli does not accept adds no flag. Tests: `FromSnapshot` (2), `FromTranscript` (6), and the endpoint tests for a closed conversation from a transcript alone and from a snapshot.
3. **Name.** `snapshot.revive` seeds it through `seed_name`, the closed list's path. The name is the snapshot's, else the one the index holds (`archive.name_of`). Tests check the `(id, name)` pair handed to `seed_name` in both cases.
4. **Directory gone.** `snapshot.revive` refuses and `reopen` answers `ok: false` with `its directory is gone: <path>`; the page shows it in red on the row. `test_when_the_directory_is_gone_nothing_is_launched`.
5. **Logged.** A launch or a refusal is a `revived` event with `id`, `name`, `source` (`snapshot` or `transcript`) and the launcher's answer; a jump is a `jumped` event with `source: search`. `test_each_reopen_is_logged_like_the_closed_lists_revives`, `test_a_refusal_is_logged_too`.
6. **A running conversation focuses its own tab.** On the real desktop, page click on a running conversation's result: 9 WezTerm tabs before and 9 after, WezTerm's focused pane moved to that conversation's own pane, one `claude --resume` process before and after. Again on a conversation that had just been reopened: 10 tabs before and after, logged as `jumped`. The tab count moves by itself while other sessions run, so each run also lists which panes appeared.
7. **Older than every snapshot.** Two conversations last active on 2026-09-26, older than the first snapshot (2026-09-27), reopened with their old session id, their old directory, `--permission-mode auto` taken from the transcript, and the name the index held. The first by a page click (7 tabs before, 9 after: the pane list shows one is the tab this click opened and the other a plain shell tab another session opened at the same moment), the second by two simultaneous requests to `/api/reopen`, which answered `opened` and `opening` (9 tabs before, 10 after). One `claude --resume` process each, `CLAUDE_CODE_CHILD_SESSION` absent from the process environment, no "Transcript saving is off" on the screen. The tabs opened for the test were closed afterwards. Names and ids stay out of this note because the repo is public; the private record is `~/.claude/pm/evidence/03.md`.

Tested on a second server from the worktree (its own port), leaving the live one alone.

**Found on the way.** The results box from ticket 02 is `position: fixed` with `max-height: 75vh`, and `vh` grows with the page's zoom (1.5): in a 1000 px window it was 1125 px tall and ran off the bottom, so the last rows could not be scrolled to, and so not clicked. `fitFound()` in `index.html` now caps it by the room left below the header, and refits on resize. Measured in windows of 1000, 600 and 500 px: the box ends inside the window and the last row is reachable. The closed list (`#closedlist`, `max-height: 70vh`) has the same shape and was not touched.

**Also on the branch.** The click handler repaints the list, which detaches the element that was clicked before the document-level "click outside closes it" handler runs; that handler now reads the click's `composedPath()`, or the error line on a row would vanish with the list.

Codex (`codex exec -s read-only` over the diff against `dev`): review 1 said NO-GO with three findings (a check-then-act race in `reopen`, `manual` dropped, tests that did not prove "never twice"), all fixed. Review 2: "No merge-blocking findings ... VERDICT: GO". Review 3 said NO-GO with one finding on the height cap (a 160 px floor, no refit on resize), fixed. Review 4, over the final rebased diff: "No findings. VERDICT: GO". The four reviews are kept in `~/.claude/pm/reviews/` (`codex-review-03*.md`).

Before the push, `git log -p origin/dev..HEAD` against the archive index (400 conversation titles, 2,117 prompt openings, 179 conversation names): 0 title matches, 0 prompt-opening matches, 0 name matches.

`python3 -m pytest tests`: 417 passed.

**Not live yet.** The server on 8765 was started before this change and still serves the old page and has no `/api/reopen`. Loading it means restarting `agentview.service`, which ticket 06 says kills every session in its cgroup; that restart is not done here.
