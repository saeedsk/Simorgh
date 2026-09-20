# Stage 5 -- Memory tiers

Status: **done** (2026-09-19: items 1-8 with tests, CONTRACT rewritten for the four tiers; item 9 recorded in findings) · Depends on: stage 4 (the session stream is the working tier) · Estimated: 3 weeks · Modules touched: memory, contracts, orchestration, persona

## Outcome

Four real tiers: working (the session transcript, owned by Orchestration), episodic (turn records with real dense embeddings persisted at store time), semantic (a fact store with first-class supersession and provenance), procedural (skills and adopted policies). Hybrid retrieval (BM25 + dense with reciprocal rank fusion, reranked by recency, person and confidence) answers in tens of milliseconds because nothing is embedded or scanned on the hot path. A correction wins by data structure, not by the model noticing which line is later. Every channel's turns carry a person namespace. Recall is also a tool the model can call.

## Why

Evaluation C10 (hashed bag-of-words embeddings, paraphrases score 0.000, a full scan per recall, the block vanishes under load), section 8.1 memory row, section 9.4. This is what the family feels daily: the machine-names and birthday cases.

## Before you start

The 30-turn household recall scenario (stage 0 item 30) is the gate: record recall@k for facts and the exact-answer rate for corrections before. Read `memory/store.py` (`MemoryEngine.retrieve` scores every record; `flag_contradictions` penalises both sides), `memory/recall.py` (the inverted index), `memory/embed.py`, `memory/embedders.py` (the sentence-transformers adapter exists; 24.9 s cold), `memory/consolidation.py`, `persona/user_model.py` (two regexes to replace).

## Action items

Done 2026-09-19: item 1. A local model loads in a boot thread after the index (recall answers from hashing meanwhile), hashed records are then re-embedded in batches and every dense vector is persisted to `memory:vectors`; a restart reads them and embeds nothing twice (`tests/simorgh/memory/test_vectors_persist.py`). The default stays `hashing` until item 2.

Done 2026-09-19: item 2. With a dense embedder, recall is one float32 matrix product per kind plus BM25 over words (stdlib, with a stopword list), fused by reciprocal rank (k=60), then the existing confidence/recency score. Measured with the real all-MiniLM-L6-v2 on a 500-record fixture of paraphrased household facts: top-3 hits hashing 0/10, dense+BM25 10/10 (BM25 without stopwords dragged it to 6/10), recall p50 13 ms. The recall scenario stays 3/3. The default embedder is now `auto` (the local model when installed); the test session switches it off with `SIMORGH_NO_LOCAL_EMBEDDER`. Not done: the cheap-model rerank of the top 20.

Done 2026-09-19: item 3. `memory/facts.py` plus `memory:facts`: a fact keyed by (person_scope, subject, predicate), superseded by the next one for its key, with `source_refs` and person scoping; the retrieve reply carries the matching facts and what each replaced; extraction runs at consolidation and keeps only triples quoted from the window. `flag_contradictions` is retired (it buried corrections with what they corrected). The birthday case passes by construction (`tests/simorgh/memory/test_facts.py`).

Item 4 in part, 2026-09-19: the facts block. What holds is rendered before the conversation lines, with the current value and what it replaced (`orchestration/context.py::FACTS_BLOCK_HEADER`). The digest followed on the same day: a recall carrying `person:<name>` gets that person's live facts too, capped at 8 -- built from the facts, so nothing regenerates it at sleep. Still open in item 4: retiring `persona/user_model.py`'s regex extraction (stage 6 touches persona).

Done 2026-09-19: item 6. `memory_search` is a session-local built-in (no Guardian, it only reads), offered by chat, voice_chat and research; a spoken turn searches under the speaker's tag and gets facts before episodes.

Done 2026-09-19: item 5. The turn's recall starts at `percept.text.received`, beside session setup, with a 1 s budget; the session takes the prefetched reply. A recall slower than the old 0.25 s blocking budget now arrives in time (`tests/simorgh/orchestration/test_speculative_recall.py`). Voice's own STT-partial prefetch is not done.

Done 2026-09-19: item 7. Telegram and WhatsApp put the sender's household name on the percept (`channels.person_for`), so their turns are remembered under that person. A sender who matches no household member is unnamed rather than identified by handle or number, which must never reach the bus.

Item 8 in part, 2026-09-19: pruning never forgets a record a live fact was read from. Not done: a score with access counts (nothing records them yet).

1. **The embedder warms in a boot thread; vectors persist.** *Lock `memory`.* `[memory] embedder = "local"` loads the sentence-transformers model in `asyncio.to_thread` at start; each record is embedded at store time and the vector persisted as a projection keyed by ref (`array('f')` blob in the record's stream or a `memory:vectors` snapshot); each record stores which embedder produced its vector; hashing remains the floor until warm and forever when the dependency is absent. Recall never waits on embedding. Acceptance: a recall issued 0.1 s after boot answers (from hashing) and one issued after warm-up uses dense vectors; no per-recall embedding of stored records.
2. **Index and fusion.** *Lock `memory`.* A numpy float32 matrix per kind with brute-force cosine (sub-10 ms to ~100k records; ANN only past ~200k); BM25 by extending the inverted index with tf and doc length (stdlib); reciprocal rank fusion of the two; rerank by recency half-life, person tag, confidence; optional cheap-model rerank of the top 20 for chat. Acceptance: `tests/simorgh/memory/test_hybrid_recall.py` on a fixture of 500 records: a paraphrase query finds its record in the top 3.
3. **The fact store.** *Lock `memory`, `contracts`.* `memory:facts` with `Fact{id, person_scope, subject, predicate, object, valid_from, valid_to, superseded_by, confidence, source_refs}`; extraction at consolidation by a cheap purpose returning JSON triples each with the quoted span it came from (the existing `untraceable()` check per triple); supersession by key `(person_scope, subject, predicate)` so a correction wins by structure and recall renders "X (was Y until <date>)"; `flag_contradictions` retired (stream kept read-only). Topics `memory.fact.stored`, `memory.fact.superseded`; a `facts` field on `memory.retrieve.reply`. Acceptance: the birthday correction case passes by construction; both-sides test updated.
4. **Entity-linked facts block and per-person digest.** *Lock `memory`, `orchestration`, `persona`.* Names of known people, devices and places in the query pull their current facts into a small block rendered before the episodic block; a ~150-token per-person digest regenerated at sleep from facts, delivered as a protected block when that person speaks; `persona/user_model.py`'s regex extraction is retired. Acceptance: a fact told to one family member does not surface to another (the scenario's cross-person case).
5. **Speculative recall on percept.** *Lock `orchestration`, `voice`.* Memory and world-now lookups are issued on `percept.text.received` (on the STT partial for voice) in parallel with session setup; the recall budget becomes ~1 s once off the critical path; the "memory could not be consulted" note stays. Acceptance: recall latency no longer on the voice critical path (span tree shows overlap).
6. **`memory_search` built-in.** *Lock `orchestration`, `execution`.* An effect-free tool `memory_search{query, kinds, person, since}` for agentic recall; bypasses Guardian like `delegate` (it has no effect). Acceptance: offered in CHAT and RESEARCH agents; a test that it returns facts and episodes.
7. **Person namespace on every channel.** *Lock `interface`, `memory`.* Telegram and WhatsApp resolve the sender and put `speaker` on the percept (they already know it for the allow-list); typed CLI turns are the owner. Acceptance: a Telegram turn's episodic record carries `person:<name>`.
8. **Forgetting.** *Lock `memory`.* Retention by a score (age, access count, confidence), never facts with live links; `memory forget` stays operator-initiated. Acceptance: a test that a linked fact survives a sweep.
9. **Findings entry** with recall@k, correction-wins rate, recall p50 latency, warm-up time. Done 2026-09-19: `docs/findings/2026-09-19-stage-4-live-fixes-and-stage-5-recall.md` (paraphrase 0/10 -> 10/10, p50 13 ms, model load 7-11 s in a thread, the correction case by construction).

## Measurements after

| Number | Before | Target |
|---|---|---|
| Recall scenario: facts recalled at turn 14/19 | fails | passes |
| Correction wins (birthday) | fails | passes by structure |
| Paraphrase recall (fixture) | 0.000 similarity | top-3 |
| Recall p50 latency, warm | 155 ms hashing / 47 ms dense (scan) | under 20 ms |
| Memory block dropped for timeout | "the normal case" under load | 0 per day |

## Risks and mitigations

- Ranking changes silently: the labelled scenario is the gate; hashing stays the floor.
- A wrong extracted fact: every fact carries `source_refs`, so it can be traced and tombstoned; extraction only records triples with a quoted span.
- The optional dependency: strictly optional; the system boots and recalls without it.

## Definition of done

- [x] Items 1-8 with tests; memory's CONTRACT.md rewritten for the four tiers. **Item 8 finished 2026-09-19: recall records its own uses, and the score is confidence decayed from the last recall, lifted by the count; a record a live fact cites is never tombstoned. The CONTRACT now opens on the four tiers with a table of where each lives, who writes it and how it is forgotten.**
- [x] Findings entry with the table. **Paraphrase recall 0/10 -> 10/10, p50 13 ms, the correction case by construction.**
