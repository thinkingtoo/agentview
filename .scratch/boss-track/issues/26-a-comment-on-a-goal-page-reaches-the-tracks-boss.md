# 26: A comment or Tell on a track's goal page reaches that track's boss

**Status:** in review

**What happened (Thierry, 2026-11-13, relayed by Petra):** he opened the goal page of a client track from the "goal ↗" link on that track's card, left a comment and pressed Tell. No session was linked to the page, so nobody answered. He wants a comment or Tell on `~/.claude/pm/<track>.goal.md` to reach the boss of that track (here Ignacio).

## Part A: diagnosis

**How a sheaf page gets its session (sheaf `origin/main`, `cli.py` `_open`/`_target`, `agents/claude_code.py` `detect`).** Only a render records one. `sheaf open FILE` posts `/_/render` with `target = detect_target(os.environ, --agent, --session)`; the hub keeps it in `docs.json` under the document (`target`: agent, session, pid, socket, config_dir, proc_start). A Tell goes to that session. `sheaf open FILE --no-browser --agent claude-code --session ID` attaches the page to session `ID` of the agent instead of the one running the command; its pid and socket come from that session's record under `config_dir_of(env)`. The hub serves any markdown file of a registered root without a render, with default settings and **no target**.

**How the goal link opens the page (agentview `goal_page.py`, `fleet.py` `_column`, `index.html` `goalLinkOf`).** `goal_page.of(track, now)` works the page's path out from `roots.json` and `sheaf status`'s port. It never runs `sheaf open` (it would start a hub and record the page's settings anew). The page opens on a hub path nobody rendered.

**Observed (2026-11-13, `~/.local/state/sheaf/docs.json`, 200 entries):**
- the goal page of one client track has **no entry at all**: no target, so the Tell has nowhere to go. That is Thierry's case.
- The other goal pages that have an entry (six tracks, among them `action-list` and `agentview`) are bound to session `a9a9a529-…` ("Leire", config dir `/dev/shm/leire-23-…/claude`), the session that rendered them on 2026-11-11. They are bound to the wrong session too: not their track's boss.

**Where the binding belongs.** On the sheaf side nothing is missing: `--session` already attaches a page to any session. The missing party is whoever knows track → boss session, and that is agentview: the boss marker `~/.claude/pm/.boss-sessions/<session id>` names the track (`providers/claude.boss_marker`), and `_column` already holds the boss row (`projects.boss_tracks(rows)`) next to the call that builds the goal link. The boss itself could run `sheaf open` at registration (claude-boss, other team), but that leaves a boss already running (Ignacio) unbound, and a boss that restarts has a new session id while the page keeps the old one. agentview sees both.

**Decision:** agentview binds. For each track that has a goal file and a boss row, when a hub runs and the page has a root, `goal_page` reads `docs.json` (read-only, like `roots.json`); if the page's entry holds no target, or one whose session is not the boss's, it runs `sheaf open GOAL --no-browser --agent claude-code --session <boss id>`, with `CLAUDE_CONFIG_DIR` = the config folder agentview reads sessions from, and the page's stored settings passed back (title, toc, max image width, by, for, theme, credit) so a re-render wipes nothing. Once per (goal, boss session); a failure is tried again after `RETRY` seconds, not on every poll. No boss running: the page is left as it is (never bound to nobody, never wiped).

The sheaf repo is not edited. No change is asked of it.

## Part B: does `boss-goal` keep the sheaf comment blocks?

Proved on a copy in a temp dir, `CLAUDE_CONFIG_DIR` pointed there, claude-boss 0.23.0 (`skills/boss/bin/boss-goal`, `objective.py`), file = a copy of the live goal file of that track (one block, `c1`, inside `## Done when`).

| Command | `sheaf-comment` blocks after |
| --- | --- |
| `boss-goal status … paused`, then `open` | 1 (kept) |
| `objective.py tick` with a criterion that matches (ticked 1) | 1 (kept) |
| `boss-goal next` (live file, heading `## Next`) | 1 (kept, but see below) |
| `boss-goal set` fed `boss-goal show` back unchanged | 1 (kept: the block is in stdin) |
| `boss-goal set` with a body written by hand | **0 (lost)** |
| `objective.py set-next` on `## Next, in priority order` holding a block | **0 (lost)** |

**Verdict: comments are lost by two commands.** `set` (`with_body`) keeps only the `# ` heading and the status line and replaces the rest with stdin, so every block not in stdin goes. `next` (`set_next`) replaces everything between its heading and the next `##`, so a block that sheaf anchored inside that section goes. `status` and `tick` edit single lines and keep every block.

Two side findings for the claude-boss owner:
- The live goal file names its section `## Next`; `set_next` looks for `## Next, in priority order`, finds none and, by the code, **appends a second section** instead of replacing the first (read, not run on the live copy). `next_items`/`next_count` read the same way, so the pulse sees no queue.
- Ignacio's rewrite this morning that kept `c1` proves nothing about `boss-goal` (Petra's note); the table above is the proof.

Not edited: claude-boss. Suggested change for Chiara: `with_body` and `set_next` carry over every `<!-- sheaf-comment … -->` line (and any line between a block's opening and its closing ` -->`) of the text they drop, at the end of the section that now holds the quoted text, or refuse when the stdin lacks a block the file has.

## Done when

- [x] A goal page whose track has a running boss and no target is bound to that boss's session; a Tell on it reaches the boss -- evidence: tests in `tests/test_goal_page.py`,; the live page is checked once after the merge, by restarting agentview and reading `docs.json` (not done: nothing was run against the live hub)
- [x] A page bound to another session is rebound to the boss; one already bound to the boss is left alone (no `sheaf open`) -- evidence: tests
- [x] The page's settings survive the bind -- evidence: test passing stored settings back
- [x] No boss, no hub, no root, or a failing `sheaf`: nothing runs or nothing breaks, the card as before -- evidence: tests
- [x] The poll never waits for it -- evidence: the bind runs in the refresh thread

**Known limit:** the bind is checked with a fake `sheaf`; `sheaf open --session` from agentview's environment is not run against the live hub before merge (it would write sheaf's real `docs.json`). The flags exist in the installed sheaf 1.0.3 (`sheaf open --help`).

**Known limit:** a page re-rendered by another session is taken back after `RETRY` (5 min) at the next look; in between, a Tell on it goes to that session.

**Known limit:** a boss session whose config folder is not agentview's (`CLAUDE_CONFIG_DIR`) is not found by `sheaf open`; boss markers live under agentview's own `pm/`, so a boss that registered there is in its registry.
