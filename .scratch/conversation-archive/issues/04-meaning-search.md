# 04: Meaning search with gemma on the tailnet

**What to build:** searches also find conversations by meaning ("the session where the chime did not ring" finds one that never used the word chime). Meaning hits are merged into the same result list as keyword hits. If the embedder cannot be reached, keyword results still come back, and the page says meaning search is off. Spec: `docs/specs/2026-09-29-conversation-archive.md` (decisions table and measured facts).

**Blocked by:** 02: Keyword search across all interactive conversations

**Status:** ready-for-agent

- [ ] The embedder is the EmbeddingGemma-300m int4 service (768 dimensions), not the bge-m3 one. Its URL and API key come from a local config file with mode 600 and never go in this repo, which is public.
- [ ] Stored passages go through the embedder's **document** endpoint (batch, at most 100 texts per call) and queries through its **query** endpoint. A test confirms each path calls the endpoint it should.
- [ ] Vectors are stored in the same SQLite file along with the model identity from the embedder's model endpoint. When that identity changes, every vector is rebuilt; vectors from two models are never mixed.
- [ ] Ranking merges the keyword and meaning lists, for example with reciprocal rank fusion, and results are still grouped by conversation.
- [ ] With the embedder down, a search returns keyword results within the usual time and flags meaning search as off. Tested by pointing at an unreachable URL.
- [ ] The backfill embeds all interactive conversations and reports its duration. A search on a paraphrase of a known conversation finds it: record the query and the result in the ticket's closing note.
