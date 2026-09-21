# memory -- contract

One-line status: layer 2 · 1,901 lines · 12 test files · lock: `memory` in docs/modules/locks.toml

## Purpose

Memory owns what Sim remembers across turns, in four tiers that differ in
how long they live and what they are for -- **working** (this
conversation), **episodic** (what happened), **semantic** (what holds),
**procedural** (how to do a thing). The tiers are described one section
down; everything else here is the machinery under them.

One Ledger event per record on `memory:<kind>`; the in-process
conversation window (`WorkingMemory`) keyed per (channel, person). It
answers `memory.retrieve` by scoring every live record of the requested
kinds and returning the facts the query touches alongside them, writes a
record for every chat `turn.completed`, and consolidates on the sleep
tick (extract facts, prune each kind, optionally distil a summary through
Cognition).

It must never physically delete or rewrite a record: forgetting and
pruning are tombstone events on `memory:tombstones`, a correction is a new
fact that supersedes the old one on `memory:facts`, and a contradiction is
an event on `memory:contradictions` -- never an edit. It must never store
something nobody said: a distillation that names specifics absent from its
transcript is dropped whole (`consolidation.py::untraceable`), and a fact
triple whose quote is not in its window is dropped the same way.

The shaping decision is that the Ledger is the store and the index is a
cache: `recall.py` keeps a per-kind cursor and in-memory index so a recall
does not re-read or re-embed the store, and the default embedder is
`auto` -- a local model when installed (warmed in a thread, vectors
persisted to `memory:vectors`, dense scores fused with BM25 by reciprocal
rank), the dependency-free hashing trick otherwise, which matches
vocabulary rather than meaning.

## The four tiers

| Tier | Where it lives | Written by | Recalled by | Forgotten by |
|---|---|---|---|---|
| **working** -- the conversation in front of Sim | `WorkingMemory._sessions`, keyed `conversation_key(channel, speaker)`; in process only | every chat `turn.completed` | Orchestration's memory block, under the same key | the process ending, or `working_max_turns` / `working_max_chars` pushing the oldest turn out |
| **episodic** -- what happened, with when and who | `memory:episodic` | every stored chat turn (not task turns, not QUIET replies), tagged `session:` and `person:<name>` | `memory.retrieve` with `kinds` containing `episodic` | `prune`, by the forgetting score below |
| **semantic** -- what holds now | `memory:facts` (`Fact{subject, predicate, object, person_scope, valid_from, valid_to, superseded_by, source_refs}`) and `memory:semantic` records | consolidation's fact pass; `store_fact` | returned with every `memory.retrieve.reply` as `facts` -- the facts the query mentions plus the asking person's digest | superseded, never deleted: a new fact for the same normalised `(person_scope, subject, predicate)` closes the old one with `valid_to` |
| **procedural** -- how to do a thing here | `memory:procedural` | Reflection's critiques, skills and learned habits | `memory.retrieve` with `kinds` containing `procedural`; chat does not ask for it | `prune`, by the same score |

A fact is not an episode and does not decay: "the wifi password is on the
fridge" was true before it was said and stays true after the conversation
that mentioned it is forgotten. That is why a correction is structural
(supersession by key) rather than a scoring contest between two records,
and why `prune` never tombstones an episodic record a live fact cites --
a fact whose source is gone asserts something nothing can check.

## Files

| File | For |
|---|---|
| `simorgh/memory/__init__.py` | re-exports `Service` |
| `simorgh/memory/api.py` | value types (`MemoryItem`, `Turn`), confidence decay, contradiction-subject helpers |
| `simorgh/memory/config.py` | `[memory]` dataclass |
| `simorgh/memory/consolidation.py` | `run_consolidation`: contradictions, prune, guarded distillation via `cognition.think` |
| `simorgh/memory/embed.py` | hashing-trick embedding (256 buckets), dense and sparse cosine |
| `simorgh/memory/embedders.py` | pluggable embedders (hashing, local sentence-transformers, OpenAI/Voyage/Gemini) and provider choice |
| `simorgh/memory/recall.py` | incremental per-kind recall index over the Ledger, tombstone and penalty folds |
| `simorgh/memory/service.py` | the bus subsystem: handlers, first consolidation after boot, metrics tick |
| `simorgh/memory/store.py` | `MemoryEngine` (store, retrieve, forget, prune, contradictions) and `WorkingMemory` |

## Consumes

Authority: `Service.consumes` in `service.py:24-29` (pinned by `tests/simorgh/test_manifests_match_the_code.py`).

| Topic | Schema | Where | Does |
|---|---|---|---|
| `memory.retrieve` | `messages/memory.py::MemoryRetrieve` | simorgh/memory/service.py | ranks records of the requested kinds and replies `memory.retrieve.reply` |
| `memory.store` | `messages/memory.py::MemoryStore` | simorgh/memory/service.py | appends a durable record (or, for `kind="working"`, adds to the window keyed by `tags[0]`) |
| `memory.forget` | `messages/memory.py::MemoryForget` | simorgh/memory/service.py | tombstones records in a time window (optionally filtered by kind and substring); replies `memory.forget.reply` |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/memory/service.py | runs a consolidation pass over `window_seconds` |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/memory/service.py | every 30th tick publishes record counts as `system.metrics` |
| `turn.completed` | `messages/task.py::TurnCompleted` | simorgh/memory/service.py | for a chat turn: feeds the conversation window and stores an episodic record tagged with session and `person:<name>` |

Requests it makes: `cognition.think` (`purpose="consolidate"`, 30 s timeout) from `consolidation.py:137`; a missing, failed or `floor:true` reply means no distillation this cycle.

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `memory.retrieve.reply` | `messages/memory.py::MemoryRetrieveReply` | simorgh/memory/service.py | reply to every `memory.retrieve`: items with `score`, `confidence_now`, `confidence`, plus `truncated` |
| `memory.forget.reply` | `messages/memory.py::MemoryForgetReply` | simorgh/memory/service.py | reply to every `memory.forget`: count and refs forgotten |
| `memory.stored` | `messages/memory.py::MemoryStored` | simorgh/memory/service.py | after each durable store (not for `working`) |
| `memory.consolidated` | `messages/memory.py::MemoryConsolidated` | simorgh/memory/service.py | after every consolidation pass (distilled 0/1, pruned, refused counts) |
| `memory.contradiction.flagged` | `messages/memory.py::MemoryContradictionFlagged` | simorgh/memory/service.py | once per pair flagged during a pass |
| `memory.forgotten` | `messages/memory.py::MemoryForgotten` | simorgh/memory/service.py | after a `memory.forget` that removed anything, and after a pass that pruned (with `refs: []`) |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/memory/service.py | every 30 s: `gauges.records` per kind |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/memory/consolidation.py | request, once per pass, when the window has episodic records |

`memory.stored`, `memory.consolidated`, `memory.contradiction.flagged` and `memory.forgotten` have no subscriber; they are on the allow-list in `tests/simorgh/contracts/test_topics_have_both_sides.py` as announcements for the Ledger and dashboard.

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `memory:{kind}` (`episodic`, `semantic`, `procedural`) | simorgh/memory/store.py:35 | none directly (others go through `memory.retrieve`); tools/bench_recall.py | forever (no `memory:` entry in DEFAULT_RETENTION) |
| `memory:tombstones` | simorgh/memory/store.py:31 | - | forever |
| `memory:contradictions` | simorgh/memory/store.py:32 | - | forever |
| `memory:facts` | simorgh/memory/store.py `store_fact` (stage 5 item 3) | `facts.FactIndex`; `memory.retrieve.reply.facts` | forever; `fact.stored{id, subject, predicate, object, person_scope, valid_from, confidence, source_refs}` and `fact.superseded{id, valid_to, superseded_by}`; never rewritten |
| `memory:vectors` | simorgh/memory/store.py `write_vector` (stage 5 item 1) | `recall.py` at sync | forever; `vector.stored{ref, provider, v}`, `v` the float32 vector in base64; one per record per embedder, written only for a dense embedder |

Not streams: `working:{session_id}:{i}` is the ref of a window item (never persisted; the window resets with the process); `contradiction:{ref_a}:{ref_b}` is the idempotency key of a contradiction event; `person:{name}` is a record tag. Long content (over 3,500 chars) goes to a Ledger blob with a preview inline (`store.py:138-173`).

## Config

`[memory]` in simorgh.toml; dataclass in `simorgh/memory/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `half_life_seconds` | `DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS` | yes |
| `working_max_turns` | `20` | yes |
| `working_max_chars` | `8000` | yes |
| `default_k` | `5` | yes |
| `embedder` | `'auto'` (local sentence-transformers when installed, else hashing; since 2026-09-19; tests get hashing via `SIMORGH_NO_LOCAL_EMBEDDER`) | yes |
| `recency_weight` | `0.1` | yes |
| `consolidate_after_start_s` | `120.0` | yes |

`default_k` is read only as a fallback when a `memory.retrieve` payload omits `k`, and the schema makes `k` required, so it never takes effect; `kernel/configcheck.py:66-67` lists it in `KNOWN_DEAD_FIELDS`. The keep-per-kind counts (2,000 / 2,000 / 500) are a constructor argument (`service.py:19`), not config.

## Public Python surface

- `simorgh.memory.Service` (name `memory`, `VERSION = "0.1.0"`): constructed by `kernel/registry.py:130` with no arguments; `Service(config=..., keep_per_kind=...)` in tests.
- `simorgh.memory.config.Config`: imported by `kernel/configcheck.py:220`.
- `simorgh.memory.store.MemoryEngine`, `stream_for`: imported by `tools/bench_recall.py` (dev tool only).
- Nothing in `simorgh/contracts` is memory-owned; the conversation key the window is fed under is `contracts/settings.py::conversation_key`, shared with Orchestration.
- `simorgh.memory.embedders.hush_model_progress()` and `QuietEncoder`: turn the model libraries' progress bars off before loading `sentence-transformers`, and keep them off around `encode`. `hush_model_progress` sets `HF_HUB_DISABLE_PROGRESS_BARS=1` in `os.environ` when it is blank (a deliberate `0` is left alone) and calls the two `disable_progress_bar` functions; it is a library switch, not a redirect, so no error or traceback is swallowed.
- Module-level state: `embed.embed_text` has an `lru_cache(maxsize=4096)` (process-wide, pure function, harmless). No mutable singletons. Per-instance state that is lost at restart: `WorkingMemory._sessions` and the recall index (rebuilt from the Ledger on `warm()`).

## Invariants

Consolidation records what somebody says they care about with the predicate `interest`, from their own words only (stage 10 item 7). It is a fact like any other and is stored like one; it is NOT permission to raise the subject -- Initiative proposes `people add_interest` at tier 3 and the person confirms.

- A record is never mutated or deleted: `forget`, `forget_window` and `prune` append to `memory:tombstones`; a tombstoned ref is never returned by `retrieve` and is not counted by `counts()`.
- `prune` never re-tombstones an already-forgotten ref, and ranks by the forgetting score -- confidence decayed from the last time the record was *recalled* (not from when it was written), times the contradiction penalty, lifted by `1 + 0.5 * ln(1 + recalls)`. Insertion order is not in it, and neither is anything a writer claimed about importance.
- `prune` never tombstones a record cited by a live fact's `source_refs`, whatever its score; what it spared is in `MemoryEngine._kept_back`.
- Recall counts its own uses: every record `retrieve` actually returns has its count and last-read time recorded (`_reads`, `_last_read`, in process). A record nobody has asked for since a restart is scored from its own timestamp, so a lost count can only make forgetting more likely, never less.
- A `turn.completed` is stored as episodic only when all hold: some text on either side, not `cancelled`, not a QUIET reply (`contracts.settings.is_quiet_reply`), and `kind` is `chat` (`service.py:204-225`). Task sessions' turns are never episodic memory.
- Every stored chat turn is also added to `WorkingMemory` under `conversation_key(channel, speaker)`, and Orchestration reads it back under the same key (pinned from the other side by `tests/simorgh/orchestration/test_the_memory_block_remembers_recent_turns.py`).
- A spoken turn is tagged `person:<speaker>` for every named voice, and the tone tag is stripped from Sim's reply before storing.
- Retrieve never shortlists or samples: every live record of every requested kind is scored; `score = similarity * confidence_now + recency_weight / (1 + age_days)`; vectors from different embedders are never compared (`store.py:363`).
- No library's progress bar reaches the terminal: the local model is wrapped in `QuietEncoder`, which passes `show_progress_bar=False` (the wrapper exists because every injected fake encoder implements `encode(text)` alone), and `hush_model_progress()` runs before the import. Reported live 2026-09-20 -- `Batches: 100%|...| 1/1` in the middle of the TUI, and `Loading weights: 100%|...| 103/103` at boot -- and already forbidden by `evals/house/script.py::tui_is_sane`.
- The indexed recall returns the same ranking, bit for bit, as the dense path (`embed.py::sparse_embed_text` docstring).
- Content longer than the inline limit is kept (blob plus preview); a partially recovered item carries a truncation notice as a prefix.
- Consolidation never stores a distillation from a floor or failed reply, never stores `NOTHING`, and drops a distillation that names anything `untraceable` in its window.
- Two records whose shared first tag is only provenance (`consolidation`, `distilled`) are never flagged as contradicting (`api.py::NOT_A_SUBJECT`).
- A consolidation pass runs `consolidate_after_start_s` after start (not only on the 6-hourly sleep tick).
- No entry in `contracts/topics.py` SUBSCRIBE_ONLY_BY, PUBLISH_ONLY_BY or PUBLISH_PAYLOAD_CONSTRAINTS names memory.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract memory`.

- `tests/simorgh/memory/test_service.py` -- the bus surface: store/retrieve/forget round trips, reply fields, `turn.completed` records, metrics tick, consolidation events.
- `tests/simorgh/memory/test_store.py` -- `MemoryEngine` scoring, decay, contradiction flagging and tombstone-only forgetting.
- `tests/simorgh/memory/test_consolidation.py` -- consolidation's three steps and that a floor or unreachable Cognition never yields a distillation.
- `tests/simorgh/memory/test_consolidation_never_invents_a_specific.py` -- the `untraceable` check drops a distillation naming things its window never said.
- `tests/simorgh/memory/test_quiet_is_not_remembered.py` -- a QUIET turn is not stored.
- `tests/simorgh/memory/test_long_content.py` -- long content survives via a blob, with the truncation notice on partial recovery.
- `tests/simorgh/memory/test_recall_scaling.py` -- the index does no repeated reads or embeddings and returns the identical ranking.
- `tests/simorgh/memory/test_first_consolidation.py` -- a pass runs shortly after start, not only on the sleep tick.
- `tests/simorgh/memory/test_embedders.py` -- provider choice, the hashing fallback, and that no progress bar can reach the screen (`ProgressBarsStayOffTheScreenTestCase`).

## Known issues (2026-09-18 evaluation)

- C8 -- the conversation window had no producer. **Fixed 2026-09-18** (`1e486f1`): fed from every chat `turn.completed` under `conversation_key`.
- C7 -- Reflection's critiques landed as episodic memory in chat prompts. **Fixed 2026-09-18** (`aa05475`): filed as procedural; chat does not recall procedural.
- C10 -- recall was a 256-bucket hashed bag of words (paraphrases scored 0.000), vectors were not persisted, and a local model cost ~25 s cold. **Fixed 2026-09-19** (stage 5 items 1-2): local embedder warmed in a thread, vectors persisted to `memory:vectors`, dense fused with BM25. The paraphrase set went 0/10 to 10/10 at p50 13 ms (`docs/findings/2026-09-19-stage-4-live-fixes-and-stage-5-recall.md`).
- W7 -- four memory announcements have no subscriber. Accepted and allow-listed with reasons (`b5c2671`).
- B7 -- the Ledger client is unbound; any subsystem can append to `memory:*`. Open; stage 1.

## Planned changes (roadmap)

- Stage 4 (session stream): the `session:<id>` stream becomes the working tier; `WorkingMemory` as fed today is the stopgap it replaces.
- Stage 5 item 1 done 2026-09-19: a local embedder loads in a thread after the index is built (`MemoryEngine.warm_embedder`); until then `Embedder.embed` answers from hashing at once, and afterwards the hashed records are re-embedded in batches (`RecallIndex.upgrade`, `Embedder.embed_many`) and persisted to `memory:vectors`, which a restart reads instead of re-embedding. The default embedder stays `hashing` until item 2's matrix makes a dense recall cheap.
- Stage 5 item 4 in part, 2026-09-19: a `memory.retrieve` carrying a `person:<name>` tag gets that person's live facts back as well as the query's, up to `_DIGEST_FACTS` (8, about 150 tokens) -- the per-person digest, built from the facts themselves, so it is current with no sleep job to regenerate it. Facts scoped to the household are not repeated in it.
- Stage 5 item 8 done 2026-09-19: the forgetting score. `prune` never tombstones a record a live fact cites (`Fact.source_refs`); what it spared is in `MemoryEngine._kept_back`. The score is confidence decayed from the last recall rather than from the write, times the contradiction penalty, times `1 + 0.5 * ln(1 + recalls)`: age and confidence alone forget the thing the household asks for every week, because being old is not the same as being finished with. `memory forget` stays operator-initiated.
- Stage 5 item 3 done 2026-09-19: the fact store. A fact is keyed by `(person_scope, subject, predicate)` normalised, so storing a new one supersedes the old (`fact.superseded`, with `valid_to`) and a correction wins by structure rather than by score; `memory.retrieve.reply` carries the facts the query mentions, each with `was`/`was_until` when it replaced one; a fact scoped to a person is never recalled for another; `memory.fact.stored`/`.superseded` are published. Facts are extracted at consolidation by a second `consolidate` call returning JSON triples, each with the sentence it came from -- a triple whose quote is not in the window is dropped (`consolidation.parse_facts`), the per-triple form of the `untraceable` rule. `flag_contradictions` is no longer called (it halved both sides and buried corrections); the method and `memory:contradictions` remain, read-only.
- Stage 5 item 2 done 2026-09-19: with a dense embedder `retrieve` scores a kind with one float32 matrix product (`KindIndex.dense_scores`) and BM25 over words (`KindIndex.bm25`, stopwords dropped), fused by reciprocal rank (`recall.fused`, k=60, scaled 0..1) as the similarity in the existing score. The hashing path is unchanged (indexed score = full-scan score).
- Stage 5 (memory tiers), all under the `memory` lock: items 1-2 (above); item 2 a float32 matrix plus BM25 fused by reciprocal rank; item 3 a `memory:facts` store (`Fact{subject, predicate, object, valid_from, valid_to, superseded_by, ...}`) extracted at consolidation, replacing `memory.contradiction.flagged`; item 4 an entity-linked facts block and per-person digest; item 7 person namespaces on every channel; item 8 forgetting by score, never a linked fact. Items 1-8 are done; this file was rewritten for the four tiers on 2026-09-19.

## Working on this module

Lock it first (`python tools/modlock.py claim memory --by <you> --task "..."`), commit the lock, edit only `simorgh/memory/`, `tests/simorgh/memory/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py memory` before committing; commit subject `memory: <what changed>`.
