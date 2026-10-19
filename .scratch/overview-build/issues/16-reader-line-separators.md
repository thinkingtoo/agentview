# 16: The reader keeps records that hold a Unicode line separator

**What to build:** the transcript readers cut a transcript into records with `str.splitlines()`. Besides `\n`, that function also cuts at a raw U+2028, U+2029 or U+0085 inside a JSON string. The cut record no longer parses and is dropped. Places this happens: `providers/claude.py` (the record loops and the first-line helper), `providers/codex.py`, and any incremental reader that shares the cut. Cut only at `\n`, as JSON Lines defines it, everywhere a transcript or rollout is read, including the incremental tail reader and its cache. Found by ticket 08's worker on 2026-10-19, read-only count over the main transcripts: 52 transcripts hold one, 140 records are invisible to the reader (131 U+2028, 7 U+2029, 2 U+0085), 63 of them tool calls.

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] Tests on invented records whose strings hold U+2028, U+2029 and U+0085: each record is read whole, in the one-pass reader and in the incremental reader cut at every record boundary, for the Claude and the Codex reader
- [ ] Counts on the real transcripts before and after, counts only: records read, records dropped, tool calls seen; after the change none is dropped for a line separator
- [ ] Movement, stuck kinds and the chime flags differ from origin/dev only on the sessions that hold such a record (differential, counts per field)
- [ ] A record's text that holds a line separator renders as text on the page (R7) and no transcript text reaches the evidence (R6)
