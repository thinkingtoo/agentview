# Conversation archive: search old conversations and reopen them

**2026-09-29 · design agreed in a grilling session, not implemented**

**⟲ closed N** only covers the current boot. Once you reboot, or a day has passed, the page
has no way to find an older conversation. This adds a search over every interactive
conversation you have had. A click reopens the one you found, or jumps to it if it is still
running.

## Decisions

| # | Question | Decision |
|---|---|---|
| 1 | What it is for | Finding a conversation and reopening it. A result is a conversation; the matching passage only says why it was found. |
| 2 | Retention | Keep every transcript where it is. Set `cleanupPeriodDays` in `~/.claude/settings.json` so Claude Code never deletes. |
| 3 | Where you search | On the agentview page, a search box next to **⟲ closed N**. No CLI. |
| 4 | Which conversations | Interactive only: transcripts whose `entrypoint` is `cli`. Headless (`sdk-cli`) runs and subagent transcripts stay out. |
| 5 | Archiving | Automatic. Every interactive conversation is in the index. The **×** on the closed list only removes it from today's list, as it does now. |
| 6 | Matching | By meaning, with EmbeddingGemma, plus a keyword index (see 10). |
| 7 | Headless transcripts | Since 2 applies to all transcripts, a nightly job deletes `sdk-cli` transcripts older than 30 days. |
| 8 | A hit that is still running | A click jumps to its pane, like a live row. It is never resumed a second time. |
| 9 | Where the index lives | One SQLite file under `~/.claude/agentview/` on this laptop. The transcripts are stored nowhere else. |
| 10 | t-compute unreachable | Hybrid search. The local keyword index (FTS5) always answers, and meaning hits are merged in when the embedder responds. When it doesn't, the page says meaning search is off. |
| 12 | When indexing runs | A timer every few minutes, on transcripts that changed. Running conversations are included. |
| 13 | What a result shows | Name, Claude's title, project, date, a two-line summary (what it was about, where it ended), and the passage that matched. |
| 14 | Who writes the summary | `claude -p --model haiku`, through the CLI, not the API. |

## Facts measured on 2026-09-29

- `~/.claude/projects` holds 2,240 top-level transcripts, 3.0 GB. Of those, 527 are `entrypoint: cli` and 1,713 are `sdk-cli`. A further 261 subagent transcripts sit under `subagents/`.
- The interactive transcripts hold about 41 MB of prompt and reply text. The median transcript is 570 KB, mostly tool output.
- `cleanupPeriodDays` is not set in `~/.claude/settings.json`. The oldest transcript is from 2026-08-07.
- **Embedder:** `tiroir-embedder-gpu.service` on t-compute, `http://100.117.2.45:8771`. It serves `google/embeddinggemma-300m` int4 ONNX, 768 dimensions, L2-normalised, with `GEMMA_MAX_LEN=2048`. It needs an `X-API-Key` (`EMBEDDER_API_KEY` in `/home/tcompute/tiroir-embedder/embedder.env` on t-compute). Its README is in `/home/tcompute/tiroir-embedder/README.md` on that box.
  - The model is **asymmetric**. A search query goes through `POST /api/v1/embed/text` (query prompt), and a stored passage through `POST /api/v1/embed/batch` (document prompt, at most 100 texts per call). Using the wrong one does not fail, it just ranks worse: the separation between right and wrong documents drops by 36% (measured in its README).
  - Vectors are tied to their model. t-compute's other service on `:8080` defaults to bge-m3 (1024 dimensions). It also serves `embeddinggemma-300m`, but that is not the int4 build. Never mix vectors from two services in one index; record the model identity from `GET /api/v1/model` and re-index when it changes.
- SQLite 3.45.1 with FTS5 is available locally. `sqlite_vec` is not installed. At this size, a brute-force cosine scan over the vectors in numpy is enough.
- Every transcript already carries Claude's short title as `{"type":"ai-title","aiTitle":...}` lines.

## Design

**One passage = one exchange.** A passage is one question you typed plus the text of the
assistant's reply, cut into more than one piece when it is longer than 2,048 tokens. Before
indexing, strip hook injections, `<system-reminder>` blocks and tool calls and results. A
hit points at a moment in the conversation, and the result row quotes it.

**Results are grouped by conversation.** Each row is a conversation, ranked by its best
passage. Keyword and meaning scores are merged, for example with reciprocal rank fusion.

**Summaries.** A conversation that has been quiet for 10 minutes, and has changed since its
last summary, gets a two-line summary: what it was about, and where it stood when it stopped
(done, waiting on you, half-way). The summary comes from `claude -p --model haiku`, run with
hooks off. Otherwise each run would appear on the page as a session and fire the team-line
hooks. These runs are `sdk-cli`, so rule 4 keeps them out of the index and rule 7 deletes
them. The backfill covers about 525 conversations and uses the plan's quota; pace it.

**Reopening** reuses the closed list's revive path (`server.py` `_revive`): `claude --resume
<id>` with the conversation's old flags and directory, in a new WezTerm tab, and its name
back through `agent-name set`. When the directory no longer exists (a removed worktree),
the page says so rather than launching something that fails.

## Build order

1. The keyword index, the search box, reopen and jump, and the retention change (2 and 7). This is usable on its own.
2. Gemma meaning search merged into the same results.
3. The Haiku summaries.

After step 1, check whether keywords alone already find what you are looking for, before
building step 2.
