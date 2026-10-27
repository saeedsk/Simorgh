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
| **semantic** -- what holds now | `memory:facts` (`Fact{subject, predicate, object, person_scope, valid_from, valid_to, superseded_by, source_refs}`) and `memory:semantic` records | consolidation's fact pass; `store_fact` | returned with every `memory.retrieve.reply` as `facts` -- the facts the query mentions plus the asking person's digest | superseded, never deleted: a new fact for the same normalised `(person_scope, subject, predicate)` closes the old one with `valid_to`; with `entities = true`, also a live fact about the same subject entity in the same scope that the reconcile decision (stage 15 item 7) says the new one UPDATEs or DELETEs |
| **procedural** -- how to do a thing here | `memory:procedural` | Growth's critiques (the monitors part), skills and learned habits | `memory.retrieve` with `kinds` containing `procedural`; chat does not ask for it | `prune`, by the same score |

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
| `simorgh/memory/core.py` | core memory blocks (stage 15 item 8): `CoreIndex` (the fold of `memory:core`), the replace rule, whose block an edit may touch |
| `simorgh/memory/consolidation.py` | `run_consolidation`: contradictions, prune, guarded distillation via `cognition.think` |
| `simorgh/memory/embed.py` | hashing-trick embedding (256 buckets), dense and sparse cosine |
| `simorgh/memory/entities.py` | `Entity`, `EntityIndex` (the fold of `memory:entities`), resolution string -> entity id (stage 15) |
| `simorgh/memory/embedders.py` | pluggable embedders (hashing, local sentence-transformers, OpenAI/Voyage/Gemini) and provider choice |
| `simorgh/memory/recall.py` | incremental per-kind recall index over the Ledger, tombstone and penalty folds |
| `simorgh/memory/service.py` | the bus subsystem: handlers, first consolidation after boot, metrics tick |
| `simorgh/memory/store.py` | `MemoryEngine` (store, retrieve, forget, prune, contradictions) and `WorkingMemory` |

## Consumes

Authority: `Service.consumes` in `service.py:24-29` (pinned by `tests/simorgh/test_manifests_match_the_code.py`).

| Topic | Schema | Where | Does |
|---|---|---|---|
| `memory.retrieve` | `messages/memory.py::MemoryRetrieve` | simorgh/memory/service.py | ranks records of the requested kinds and replies `memory.retrieve.reply`; with `core_edit` (undeclared, additional property) it is instead `memory_core_edit`'s edit of a core block, answered with no items and `core_edit{ok, block, text, error}` |
| `memory.store` | `messages/memory.py::MemoryStore` | simorgh/memory/service.py | appends a durable record (or, for `kind="working"`, adds to the window keyed by `tags[0]`) |
| `memory.forget` | `messages/memory.py::MemoryForget` | simorgh/memory/service.py | tombstones records in a time window (optionally filtered by kind and substring); replies `memory.forget.reply` |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/memory/service.py | runs a consolidation pass over `window_seconds` |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/memory/service.py | every 30th tick publishes record counts as `system.metrics` |
| `turn.completed` | `messages/task.py::TurnCompleted` | simorgh/memory/service.py | for a chat turn: feeds the conversation window and stores an episodic record tagged with session and `person:<name>` |

Requests it makes: `cognition.think` (`purpose="consolidate"`, `consolidate_timeout_s`) from `consolidation.py` -- the distillation, the fact extraction and (stage 15, `entities = true`) `review_uncertain`'s YES/NO question about a close name pair, at most `MAX_SAME_QUESTIONS` (5) a pass, `summarise_entities`' 1-3 sentence summary of an entity with new facts, at most `MAX_SUMMARIES` (8) a pass, and `reconcile_fact`'s ADD/UPDATE/DELETE/NOOP decision for each extracted fact that has live candidates, at most `MAX_FACTS` (12) a pass (stage 15 item 7; the plan names purposes `memory.summary` and `memory.reconcile`; the `contracts` enum lacks both, so these use `consolidate`); a missing, failed or `floor:true` reply means none of these this cycle -- for the reconcile decision, the fact is stored by the exact-key rule alone.

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `memory.retrieve.reply` | `messages/memory.py::MemoryRetrieveReply` | simorgh/memory/service.py | reply to every `memory.retrieve`: items with `score`, `confidence_now`, `confidence`, plus `truncated`; `facts` when any hold (each may carry `was`/`was_until`, and -- stage 15, `entities = true`, `graph_hops > 0` -- `hop: 1 | 2` on a fact the entity walk added) |
| `memory.retrieve.reply` + `core` | (undeclared, additional property) | simorgh/memory/service.py `_core_for` | stage 15 item 8, with `[memory] core_blocks = true` and `core_for` in the request: `core: [{block, label, text}]`, the `household` block then the asker's own, each only when it has text -- `[]` when none, which still tells Orchestration the blocks are on. Off, or not asked: no `core` key at all |
| `memory.forget.reply` | `messages/memory.py::MemoryForgetReply` | simorgh/memory/service.py | reply to every `memory.forget`: count and refs forgotten |
| `memory.stored` | `messages/memory.py::MemoryStored` | simorgh/memory/service.py | after each durable store (not for `working`) |
| `memory.consolidated` | `messages/memory.py::MemoryConsolidated` | simorgh/memory/service.py | after every consolidation pass (distilled 0/1, pruned, refused counts) |
| `memory.fact.stored` / `memory.fact.superseded` | `messages/memory.py` | simorgh/memory/service.py `_announce_fact` | per fact stored, and per fact it ended -- the key's predecessor and (stage 15 item 7) each fact the reconcile decision ended with it, one `superseded` each |
| `memory.contradiction.flagged` | `messages/memory.py::MemoryContradictionFlagged` | simorgh/memory/service.py | once per pair flagged during a pass |
| `memory.forgotten` | `messages/memory.py::MemoryForgotten` | simorgh/memory/service.py | after a `memory.forget` that removed anything, and after a pass that pruned (with `refs: []`) |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/memory/service.py | every 30 s: `gauges.records` per kind |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/memory/consolidation.py | request, once per pass, when the window has episodic records |

A summary line (stage 15 item 3) rides in the same `facts` list as `{id: "<entity>#summary", subject: <name>, predicate: "in short:", object: <summary>, person_scope: "*", confidence: 1.0, summary: true, entity: <id>}`, one per entity the query names that has one, with `entities = true` and `graph_hops > 0`. `hop`, `summary` and `entity` are not declared in `contracts/messages/memory.py::MemoryRetrieveReply`; the `facts` objects admit additional properties, so it validates, and declaring it is a `contracts` change. Orchestration (`orchestration/context.py::_fact_lines`) renders the first 8 facts and does not read `hop`.

`memory.stored`, `memory.consolidated`, `memory.contradiction.flagged` and `memory.forgotten` have no subscriber; they are on the allow-list in `tests/simorgh/contracts/test_topics_have_both_sides.py` as announcements for the Ledger and dashboard.

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `memory:{kind}` (`episodic`, `semantic`, `procedural`) | simorgh/memory/store.py:35 | none directly (others go through `memory.retrieve`); tools/bench_recall.py | forever (no `memory:` entry in DEFAULT_RETENTION) |
| `memory:tombstones` | simorgh/memory/store.py:31 | - | forever |
| `memory:contradictions` | simorgh/memory/store.py:32 | - | forever |
| `memory:facts` | simorgh/memory/store.py `store_fact` (stage 5 item 3) | `facts.FactIndex`; `memory.retrieve.reply.facts` | forever; `fact.stored{id, subject, predicate, object, person_scope, valid_from, confidence, source_refs, subject_id?, object_id?}` (the ids only with `[memory] entities = true`), `fact.superseded{id, valid_to, superseded_by}` (by the exact key, or -- stage 15 item 7, `entities = true` -- by the reconcile decision, the same event naming the new fact) and `fact.linked{id, subject_id, object_id}` (stage 15: the sleep tick's one-off backfill of facts written before entities, at most one per fact); never rewritten |
| `memory:entities` | simorgh/memory/entities.py `ENTITY_STREAM` (stage 15 item 1; covered by the `memory:` prefix in `contracts/streamnames.py`) | `entities.EntityIndex` | forever; `entity.created{id, type, name, aliases, person_scope, source_refs}`, `entity.alias_added{id, alias}`, `entity.merged{id, into, reason}` (the survivor; every old id keeps resolving to it), `entity.summary{id, summary, person_scope, fact_ids}`; never rewritten. Written only with `[memory] entities = true` |
| `memory:core` | simorgh/memory/core.py `CORE_STREAM` (stage 15 item 8; covered by the `memory:` prefix) | `core.CoreIndex` | forever; `core.edited{block, text, previous, old, new, by, source_ref, action_id}` -- the whole new text and the text it replaced, who edited it (the requester's name), and the turn (`source_ref`, the chat turn's task id) and Guardian action it came from; never rewritten. Written only with `[memory] core_blocks = true` |
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
| `entities` | `false` (stage 15; becomes `true` once the memory eval, stage 15 item 4, shows no regression) | yes -- facts record `subject_id`/`object_id`, the sleep tick links old facts and asks about close name pairs, and `memory.retrieve` adds the facts about every entity the query names |
| `graph_hops` | `2` | yes, with `entities = true` (stage 15 item 2): how far recall walks from the entities a query names; `0` turns the walk off and the facts block is byte for byte what it was without entities |
| `graph_max_facts` | `12` | yes: the most facts the walk may add to one reply, hop 1 first |
| `core_blocks` | `false` (stage 15 item 8; the plan keeps them only if the memory suite, item 4, run with them on and off, shows accuracy up or level at fewer injected tokens) | yes -- a recall asking `core_for` gets `core`, and `memory_core_edit` writes `memory:core`; off, neither, and an edit is refused by name |
| `core_block_chars` | `600` | yes: the longest a core block may be; an edit that would pass it is refused whole, never cut |
| `consolidate_timeout_s` | `120.0` | yes -- consolidation's wait on Cognition, which IS the deadline the providers share (each gets `remaining / (still to try + 1)`). At 30 s over four providers each got ~8 s: Gemini's answer arrived after it was abandoned and the floor "consolidated" nothing (live, 2026-09-22) |

`default_k` is read only as a fallback when a `memory.retrieve` payload omits `k`, and the schema makes `k` required, so it never takes effect; `kernel/configcheck.py:66-67` lists it in `KNOWN_DEAD_FIELDS`. The keep-per-kind counts (2,000 / 2,000 / 500) are a constructor argument (`service.py:19`), not config.

## Public Python surface

- `simorgh.memory.Service` (name `memory`, `VERSION = "0.1.0"`): constructed by `kernel/registry.py:130` with no arguments; `Service(config=..., keep_per_kind=...)` in tests.
- `simorgh.memory.entities` (stage 15): `Entity`, `EntityIndex`, `ENTITY_STREAM` and the event names, `normalise`, `kinship_word`, `speakers_own`, `relational`, `name_like`; `MemoryEngine.entity_for`, `add_alias`, `merge_entities`, `link_facts`, `query_entities`, `entity_facts`, `graph_facts`, `entity_summaries`, and the settable `MemoryEngine.people`; `recall.hop_facts`; `consolidation.review_uncertain`, `summarise_entities`, `SummaryReport`; (item 7) `MemoryEngine.fact_candidates`, `store_fact(..., supersedes=)`, `consolidation.reconcile_fact`, `parse_decisions`, `RECONCILE_INSTRUCTION`, `RECONCILE_K`, `DECISIONS`, `ConsolidationReport.reconciled`. `Service._announce_fact` takes `also=` (the extra ids ended); `MemoryEngine._on_fact` is called with it only when there are any. Nothing outside memory imports them yet; stage 15 item 4's eval will.
- `simorgh.memory.core` (stage 15 item 8): `CORE_STREAM`, `EDITED`, `HOUSEHOLD`, `UNPLACED`, `CoreIndex`, `apply_edit`, `block_for`, `person_block`, `owner_name`, `requester_name`; `MemoryEngine.core_blocks`, `edit_core`; `Service._core_for`, `_on_core_edit`. Nothing outside memory imports them.
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
- A spoken turn with no named voice is tagged `person:unknown` (`UNPLACED_VOICE_TAG`): untagged turns are shared with every speaker as typed ones are, and a stranger's refusal was recalled for Saeed (2026-09-27).
- Retrieve never shortlists or samples: every live record of every requested kind is scored; `score = similarity * confidence_now + recency_weight / (1 + age_days)`; vectors from different embedders are never compared (`store.py:363`).
- No library's progress bar reaches the terminal: the local model is wrapped in `QuietEncoder`, which passes `show_progress_bar=False` (the wrapper exists because every injected fake encoder implements `encode(text)` alone), and `hush_model_progress()` runs before the import. Reported live 2026-09-20 -- `Batches: 100%|...| 1/1` in the middle of the TUI, and `Loading weights: 100%|...| 103/103` at boot -- and already forbidden by `evals/house/script.py::tui_is_sane`.
- The indexed recall returns the same ranking, bit for bit, as the dense path (`embed.py::sparse_embed_text` docstring).
- Content longer than the inline limit is kept (blob plus preview); a partially recovered item carries a truncation notice as a prefix.
- Consolidation never stores a distillation from a floor or failed reply, never stores `NOTHING`, and drops a distillation that names anything `untraceable` in its window.
- Two records whose shared first tag is only provenance (`consolidation`, `distilled`) are never flagged as contradicting (`api.py::NOT_A_SUBJECT`).
- A consolidation pass runs `consolidate_after_start_s` after start (not only on the 6-hourly sleep tick).
- Entities (stage 15, with `entities = true`): resolution is, in order, an exact alias; the People registry (`contracts.people.household_people()` unless `MemoryEngine.people` is set); a fuzzy match at edit distance <= 1 for names of five or more characters, accepted only when exactly one entity is that close; otherwise a new entity. A model is asked about identity only on the sleep tick, only for the ambiguous pairs, and only a plain YES from a real provider merges. A kinship word resolves through the speaker's People `relations` only when it is the speaker's own ("my wife", "our son", a bare "son"); anybody else's ("his son", "your wife") resolves to nothing, and neither it nor a phrase built on one ("my wife's sister") ever becomes an entity. Asking (`query_entities`) never creates one. A value object (digits, more than four words, over 40 chars) gets no entity.
- Multi-hop recall (`recall.hop_facts`, stage 15 item 2): hop 1 is every live fact whose subject or object is an entity the query names; hop 2 every live fact touching the entity at the other end of a hop-1 fact. Only the facts the asking person may see are walked, so a fact private to somebody else is neither returned nor a bridge to one that is not (pinned by `test_multi_hop_recall.py::HopsNeverCrossPersonScopeTestCase`). The walk adds after the matched facts and the digest, never instead of them, skips what is already in the block, and marks each fact it added with `hop`.
- An entity summary (stage 15 item 3, sleep tick) is written only from household-scoped (`*`) facts and stored with that scope, so a private fact never reaches one; it is dropped whole when it names a specific (`untraceable`) or a digit run its facts do not contain, or runs over `SUMMARY_MAX_CHARS` (400). A floor or failed reply writes nothing and is counted `skipped`; an entity whose live household facts are exactly the ones last summarised is not asked about again. Recall shows a summary only while every fact it was written from is still live, so a corrected or forgotten value never comes back through one; the next pass rewrites it from what is left.
- The reconcile decision (stage 15 item 7, consolidation's fact pass, `entities = true`): each extracted fact is shown at most `RECONCILE_K` (5) live facts with the SAME `person_scope` (not merely visible: a household fact never meets a private one, nor one person's another's) and the same canonical subject entity, ranked by the recall score (BM25 fused with dense, or the hashing cosine). Per candidate the model answers ADD | UPDATE | DELETE | NOOP as a JSON array; UPDATE and DELETE end the candidate with `fact.superseded` naming the new fact, nothing is deleted. `store_fact(supersedes=)` checks the scope and the subject entity again itself, so no caller can end a fact across a scope or about another entity, and with entities off it ends nothing; only a live fact is ended, so a chain of supersessions never closes on itself. A decision naming a fact it was not shown is ignored and counted (`reconciled["ignored"]`). A floor, failed or unparseable reply, or one with no usable decision, stores the fact by the exact-key rule alone. The decision only adds to the key rule: a NOOP skips the write only when no live fact under the same key holds a different value. A subject with no candidates asks nothing. With `entities = false` the fact pass is what it was: no question, no candidates, the same events.
- Core blocks (stage 15 item 8, `core_blocks = true`): one block per person (`person:<slug>`) and one `household`, each at most `core_block_chars`. An edit is Letta's replace: `old` must occur in the block exactly once and becomes `new`; `old` empty appends `new` as a line, `new` empty removes `old`; a result over the limit, an absent or repeated `old`, or no change is refused with the reason and writes nothing. A person edits only `household` and their own block (by `me` or their name); the requester is who Guardian recorded asking (execution's tool reads it from `action:<id>`), "" is the console and so the owner (`role == "owner"` in the People registry), and a voice nobody placed (`unknown`) edits nothing. A recall shows the asker the `household` block and their own, never anybody else's. Every edit is a `core.edited` event keeping the previous text; an edit is undone by another.
- A merge never rewrites a fact: facts keep the ids they recorded and `EntityIndex.canonical` maps every old id to the survivor.
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
- `tests/simorgh/memory/test_entities.py` -- each resolution rule, a merge leaving old ids resolvable, the Soo/Soodeh case, the backfill, and the sleep tick's model check (stage 15 item 1).
- `tests/simorgh/memory/test_multi_hop_recall.py` -- the boiler -> Reza -> phone join, `graph_hops = 0` reproducing the block byte for byte, the cap, and hops never crossing `person_scope` (stage 15 item 2).
- `tests/simorgh/memory/test_fact_reconcile.py` -- Shiraz -> Tehran leaving one live and one superseded, a different Reza untouched, private facts never compared across scope, the floor and an unparseable reply falling back to the exact key, a decision about an unshown fact ignored, NOOP, the k cap, `store_fact(supersedes=)` refusing another scope or entity, no supersession loop, the dense ranking, entities off asking nothing (stage 15 item 7).
- `tests/simorgh/memory/test_entity_summaries.py` -- a summary written and recalled, an untraceable one dropped, the floor writing none and reporting skipped, a private fact never summarised (stage 15 item 3).
- `tests/simorgh/memory/test_core_blocks.py` -- off by default with no `core` and edits refused; on, `[]` with no block, the edit event with its source turn and previous text, a turn seeing `household` and its own block only, the console as the owner, nobody editing another's block, an unplaced voice editing nothing, the size limit, an edit undone by another, edits made at once each starting from the last (`MemoryEngine.edit_core` holds a lock across read, replace and append), the blocks surviving a restart, and the replace rules (stage 15 item 8).
- `tests/simorgh/memory/test_embedders.py` -- provider choice, the hashing fallback, and that no progress bar can reach the screen (`ProgressBarsStayOffTheScreenTestCase`).

## Known issues (2026-09-18 evaluation)

- C8 -- the conversation window had no producer. **Fixed 2026-09-18** (`1e486f1`): fed from every chat `turn.completed` under `conversation_key`.
- C7 -- Reflection's critiques landed as episodic memory in chat prompts. **Fixed 2026-09-18** (`aa05475`): filed as procedural; chat does not recall procedural.
- C10 -- recall was a 256-bucket hashed bag of words (paraphrases scored 0.000), vectors were not persisted, and a local model cost ~25 s cold. **Fixed 2026-09-19** (stage 5 items 1-2): local embedder warmed in a thread, vectors persisted to `memory:vectors`, dense fused with BM25. The paraphrase set went 0/10 to 10/10 at p50 13 ms (`docs/findings/2026-09-19-stage-4-live-fixes-and-stage-5-recall.md`).
- W7 -- four memory announcements have no subscriber. Accepted and allow-listed with reasons (`b5c2671`).
- B7 -- the Ledger client is unbound; any subsystem can append to `memory:*`. Open; stage 1.

## Planned changes (roadmap)

- Stage 15 item 8 built 2026-10-27, behind `[memory] core_blocks = false`: Letta's core memory blocks (`core.py`, `memory:core`, `memory_core_edit` in execution). The plan's acceptance run -- the memory suite with the blocks on and off -- waits for item 4's suite; until then they stay off. Open, outside this lock: the edit rides on `memory.retrieve` (`core_edit`) and the blocks on its reply (`core`), both undeclared, because the catalogue has no core topic: a `contracts` change adds `memory.core.edit` / `.reply` and declares `core`/`core_for` on `MemoryRetrieve`/`Reply`. The person check is made by the tool (from Guardian's record of the requester) and again here; a Guardian rule checking a `memory_core_edit`'s `block` against the requester itself needs the `guardian` lock. The Interface has no narration verb for the tool.
- Stage 15 item 7 built 2026-10-27, behind the same `entities` switch: Mem0's update decision in consolidation's fact pass (`reconcile_fact`). The plan's third acceptance check, "the memory suite's temporal-now category does not regress", waits for item 4's suite.
- Stage 15 items 1-3 built 2026-10-27, behind `[memory] entities = false`: entities and resolution (`entities.py`, `memory:entities`), multi-hop recall (`recall.hop_facts`, `graph_hops`, `graph_max_facts`, the `hop` field) and entity summaries on the sleep tick. Items 4-6 (the memory eval against Graphiti as a sidecar) decide whether `entities` defaults to true. Open, outside this lock: `contracts.people.Person` has no `relations`, so kinship words resolve only when `MemoryEngine.people` is given records that carry one; `cognition.think` has no `memory.summary` or `memory.reconcile` purpose (both ride on `consolidate`: a `contracts` change adds them to `messages/cognition.py`'s purpose enum and a budget row in `cognition/config.py`); `memory.fact.superseded` carries no reason, so a reconcile supersession and a key supersession look alike on the bus (the ledger event says which fact replaced it); `hop`/`summary`/`entity` are undeclared in `MemoryRetrieveReply`; Orchestration shows 8 fact lines.

- Stage 4 (session stream): the `session:<id>` stream becomes the working tier; `WorkingMemory` as fed today is the stopgap it replaces.
- Stage 5 item 1 done 2026-09-19: a local embedder loads in a thread after the index is built (`MemoryEngine.warm_embedder`); until then `Embedder.embed` answers from hashing at once, and afterwards the hashed records are re-embedded in batches (`RecallIndex.upgrade`, `Embedder.embed_many`) and persisted to `memory:vectors`, which a restart reads instead of re-embedding. The default embedder stays `hashing` until item 2's matrix makes a dense recall cheap.
- Stage 5 item 4 in part, 2026-09-19: a `memory.retrieve` carrying a `person:<name>` tag gets that person's live facts back as well as the query's, up to `_DIGEST_FACTS` (8, about 150 tokens) -- the per-person digest, built from the facts themselves, so it is current with no sleep job to regenerate it. Facts scoped to the household are not repeated in it.
- Stage 5 item 8 done 2026-09-19: the forgetting score. `prune` never tombstones a record a live fact cites (`Fact.source_refs`); what it spared is in `MemoryEngine._kept_back`. The score is confidence decayed from the last recall rather than from the write, times the contradiction penalty, times `1 + 0.5 * ln(1 + recalls)`: age and confidence alone forget the thing the household asks for every week, because being old is not the same as being finished with. `memory forget` stays operator-initiated.
- Stage 5 item 3 done 2026-09-19: the fact store. A fact is keyed by `(person_scope, subject, predicate)` normalised, so storing a new one supersedes the old (`fact.superseded`, with `valid_to`) and a correction wins by structure rather than by score; `memory.retrieve.reply` carries the facts the query mentions, each with `was`/`was_until` when it replaced one; a fact scoped to a person is never recalled for another; `memory.fact.stored`/`.superseded` are published. Facts are extracted at consolidation by a second `consolidate` call returning JSON triples, each with the sentence it came from -- a triple whose quote is not in the window is dropped (`consolidation.parse_facts`), the per-triple form of the `untraceable` rule. `flag_contradictions` is no longer called (it halved both sides and buried corrections); the method and `memory:contradictions` remain, read-only.
- Stage 5 item 2 done 2026-09-19: with a dense embedder `retrieve` scores a kind with one float32 matrix product (`KindIndex.dense_scores`) and BM25 over words (`KindIndex.bm25`, stopwords dropped), fused by reciprocal rank (`recall.fused`, k=60, scaled 0..1) as the similarity in the existing score. The hashing path is unchanged (indexed score = full-scan score).
- Stage 5 (memory tiers), all under the `memory` lock: items 1-2 (above); item 2 a float32 matrix plus BM25 fused by reciprocal rank; item 3 a `memory:facts` store (`Fact{subject, predicate, object, valid_from, valid_to, superseded_by, ...}`) extracted at consolidation, replacing `memory.contradiction.flagged`; item 4 an entity-linked facts block and per-person digest; item 7 person namespaces on every channel; item 8 forgetting by score, never a linked fact. Items 1-8 are done; this file was rewritten for the four tiers on 2026-09-19.

## Working on this module

Lock it first (`python tools/modlock.py claim memory --by <you> --task "..."`), commit the lock, edit only `simorgh/memory/`, `tests/simorgh/memory/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py memory` before committing; commit subject `memory: <what changed>`.
- 2026-09-27: `memory.forget` with kind `facts` ends each live fact recorded in the window (and containing the words, matched against subject, predicate and object): a `fact.superseded` with nothing superseding it, since the fact index does not read tombstones. `containing` matches a fact's subject/predicate/object -- a fact has no `content` (`store._searchable`).
