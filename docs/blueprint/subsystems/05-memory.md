# 05 — Memory (`simorgh/memory/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md`, `02-system-architecture.md`,
> `03-contracts-and-messaging.md`. This spec refines them; it may not
> contradict them. Contradictions found while writing are listed in §12.

**Layer:** 1 Cognitive core
**Owner (build):** unassigned
**Status:** built (reconfirmation-tracking in confidence decay not built this pass; decay-from-creation only)
**Depends on (contracts only):** consumes `memory.retrieve`, `memory.store`, `turn.completed`, `task.completed`, `task.failed`, `research.finding.recorded`, `learn.skill.acquired`, `learn.competence.updated`, `system.tick.sleep`, `system.state.changed`; requests `cognition.think` (purpose `consolidate`)
**v1 code that migrates here:** `src/memory/long_term.py` (`MemoryRecord`, `MemoryStore`, `embed_text`, `cosine_similarity`, `semantic_search`, `score_confidence`, `find_contradictions`, `flag_contradiction`, `consolidate_contradictions`, `reconsolidate`, causal links), `src/memory/short_term.py` (`ShortTermMemory`, `save`/`load_and_clear`), `src/orchestrator/consolidation.py` (`run_consolidation`, `_prune_kind`)

## 1. Purpose and responsibilities

Memory is what lets Simorgh be the same agent tomorrow that it was
today. It stores and retrieves information across four timescales and
abstraction levels — working (this session's turns), episodic (what
happened, when, and how it went), semantic (what is known, decoupled
from when it was learned: facts, research findings, distilled lessons),
and procedural (an index of *how* to do things: strategies and skills,
by name, with their track record; the code itself lives in the skill
library) — and it runs the consolidation pathway that turns piles of
episodes into durable general knowledge, while decaying and pruning what
has stopped being reliable. It serves one retrieval API to everyone and
never decides what to *do* with a memory.

**Responsibilities (owns):**
- The four memory kinds as Ledger streams and their projections/indexes.
- `memory.retrieve` scoring: lexical + hashing-trick embedding + recency + confidence; filters; token-budgeted results.
- `memory.store` (idempotent) and the automatic episodic writes from `turn.completed`/`task.*`.
- Confidence: base values, exponential decay by half-life, contradiction halving, reconsolidation on re-access (v1 semantics).
- Consolidation on `system.tick.sleep`: episodic → semantic distillation (one bounded `cognition.think`, purpose `consolidate`), contradiction consolidation, pruning by kind, `memory.consolidated`.
- Forgetting policy and `memory.forgotten` (never a physical delete of the log; a tombstone event and index removal).
- Working memory per session with the relaunch handoff.
- `migrate-v1` import of `~/.simorgh/memory.jsonl`.

**Explicit non-responsibilities (belongs elsewhere):**
- Deciding when to retrieve or how many items to put in a prompt → Orchestration (chat/task loops) and Cognition's compaction.
- The Self Model (what the system knows about *itself*) → World Model; Memory stores the raw observations it is built from only as episodes.
- Skill code and its execution → Learning (library) and Execution (tools); Memory holds the procedural *index* (name, description, applicability, success stats).
- The knowledge base markdown files → Learning writes them via Execution; Memory indexes their distilled content as semantic records.

**Principles this subsystem is the primary enforcer of:** 4.4 (append-only; projections recomputable), 4.5 (honest floor — consolidation without a provider prunes but does not fabricate lessons), 4.12 (transparent stores: every record is readable JSON).

## 2. Position in the architecture

Layer 1. Participates in Flows 1 (retrieve + episodic write), 2 (task
episodes), 6 (research findings as semantic records), 7 (working memory
rehydration), 8 (consolidation). Imports only `simorgh.contracts`,
`simorgh.bus.client`, `simorgh.ledger.client`, stdlib, itself.

## 3. Interfaces

### 3.1 Messages consumed
| Type | Pattern | Semantics | What this subsystem does with it |
|---|---|---|---|
| `memory.retrieve` | exact | request | Score and return top-k across requested kinds |
| `memory.store` | exact | command | Append to the kind's stream (idempotent on `idempotency_key`), index, emit `memory.stored` |
| `turn.completed` | exact | event | Append working turn (`memory:working:<session>`) and an episodic record `{kind:"turn", request, response_preview, mood, task_ref}` |
| `task.completed` / `task.failed` / `task.blocked` | exact | event | Episodic record `{kind:"task_outcome", task_id, task_type, succeeded, verdict, note}`; causal link to the task's `task.created` episode |
| `research.finding.recorded` | exact | event | Semantic record `{kind:"research_finding", topic, finding_ref, confidence:0.7}` |
| `learn.skill.acquired` | exact | event | Procedural record `{name, description, path, tests}` |
| `learn.competence.updated` | exact | event | Update the procedural record's `success_rate` for that task_type/strategy |
| `system.tick.sleep` | exact | event | Run consolidation (§5) |
| `system.state.changed` | exact | event | `paused`: finish in-flight append, refuse new consolidation; `stopping`: flush, save working memory handoff |
| `system.started` | exact | event | Rebuild indexes from streams (or snapshots); load relaunch handoff |

### 3.2 Messages produced
| Type | Semantics | Payload summary | Consumers |
|---|---|---|---|
| `memory.retrieve.reply` | reply | `{ok, items:[{ref, kind, content, score, confidence, ts, tags, source_ref}], truncated: bool}` | requester |
| `memory.stored` | event | `{ref, kind, tags}` | interface (vitals: record count), reflection |
| `memory.consolidated` | event | `{window_seconds, distilled: n, pruned: n, contradictions_resolved: n, floor: bool}` | interface, reflection, worldmodel |
| `memory.forgotten` | event | `{refs, reason: pruned|contradicted|expired|requested}` | reflection |
| `memory.contradiction.flagged` | event (proposed) | `{ref_a, ref_b, similarity}` | reflection |
| `system.health` | event | degraded if index rebuild fails or a stream is unreadable | kernel |

### 3.3 Request/reply APIs served
- `memory.retrieve` → `memory.retrieve.reply`. Payload:
  `{query: str, kinds: [working|episodic|semantic|procedural], k: int (≤50),
  filters?: {tags?: [str], since?: ts, until?: ts, min_confidence?: float, session_id?: str, task_type?: str},
  budget_tokens?: int}`. Timeout expectation ≤ 2 s (in-process index).
  Failure: `ok:false, error:{code: invalid_request|index_unavailable, retryable}`. Never calls a model.

### 3.4 Python protocol (`api.py`)

```python
@dataclass(frozen=True)
class MemoryRecord:                      # ported from v1 with stream fields
    ref: str                              # "<stream>#<seq>"
    kind: Kind                            # working|episodic|semantic|procedural
    subkind: str                          # turn|task_outcome|research_finding|lesson|fact|skill|strategy|...
    content: str                          # or content_ref for > 8 KB
    ts: float
    confidence: float                     # base, before decay
    last_accessed: float
    tags: tuple[str, ...]
    source_ref: str | None                # trace/task/finding that produced it
    metadata: dict
    embedding: tuple[float, ...] | None   # 256-dim hashing-trick, computed at store time

class Index(Protocol):                    # one per kind; rebuilt from the stream
    def add(self, rec: MemoryRecord) -> None
    def remove(self, ref: str) -> None
    def candidates(self, query_tokens: list[str], query_vec: tuple[float, ...], filters: Filters, limit: int) -> list[MemoryRecord]

class Scorer:
    def score(self, rec: MemoryRecord, q: Query, now: float) -> float   # §5 formula

class Confidence:                          # port of v1 score_confidence / halving / reconsolidate
    def current(self, rec: MemoryRecord, now: float) -> float
    def contradict(self, a: str, b: str) -> tuple[MemoryRecord, MemoryRecord]
    def touch(self, ref: str, now: float) -> None

class Consolidator:
    async def run(self, window_seconds: float, *, allow_model: bool) -> ConsolidationReport

class WorkingMemory:                       # port of ShortTermMemory
    def add(self, session_id: str, request: str, response: str) -> Turn
    def recent(self, session_id: str, limit: int | None) -> list[Turn]
    def as_context(self, session_id: str, limit: int | None) -> str
    def save_handoff(self, path: Path) -> None
    def load_handoff(self, path: Path) -> None
```

### 3.5 Configuration (`simorgh.toml [memory]`)

| Key | Type | Default | Controls |
|---|---|---|---|
| `working.max_turns` / `working.max_chars` | int/int | 20 / 8000 | Per-session window (v1 values) |
| `working.handoff_path` | path | `<data_dir>/relaunch_context.json` | Relaunch handoff |
| `embedding.dim` | int | 256 | Hashing-trick dimension |
| `scoring.weights` | table | lexical 0.35, embedding 0.35, recency 0.15, confidence 0.15 | Retrieval formula |
| `scoring.recency_half_life_seconds` | float | 604800 (7 d) | Recency decay |
| `confidence.half_life_seconds` | float | 2592000 (30 d) | v1 default |
| `confidence.contradiction_factor` | float | 0.5 | Halving |
| `confidence.similarity_threshold` | float | 0.82 | Contradiction candidate cutoff (cosine) |
| `consolidation.window_seconds` | float | 86400 | Episodes considered per sleep |
| `consolidation.max_episodes_per_pass` | int | 200 | Bounds the distillation prompt |
| `consolidation.prune.keep_per_subkind` | table | turn 500, task_outcome 1000, tool_call 300, … | v1 `_prune_kind` keeps |
| `consolidation.prune_below_confidence` | float | 0.15 | Tombstone threshold |
| `retrieval.max_k` | int | 50 | Hard cap |
| `blob_threshold_bytes` | int | 8192 | Content → blob ref |

## 4. Data model and Ledger streams

| Stream | Events | Notes |
|---|---|---|
| `memory:working:<session_id>` | `turn.added`, `session.cleared` | Rebuilt into the window; expires 7 days after last event |
| `memory:episodic` | `record.stored`, `record.accessed` (batched, at most one per record per hour), `record.confidence.changed {reason}`, `record.tombstoned {reason}`, `link.causal {consequence, antecedent}` | The v1 `JSONFileMemoryStore` semantics, made append-only: no `_rewrite`; deletions are tombstones; the index skips tombstoned refs |
| `memory:semantic` | same event set | Facts, lessons, research findings, KB distillations |
| `memory:procedural` | `record.stored`, `record.stats.updated {task_type, success_rate, samples}` | Skills/strategies index |
| `memory:consolidation` | `pass.started`, `pass.completed {report}` | Audit trail of every sleep |

Projections (all rebuildable): per-kind `Index` (token postings +
embedding matrix + tag map + ref→record), `Confidence` state (base +
last_accessed + contradiction count), working windows. Snapshots every
1,000 events per stream. Blobs for content > 8 KB. Files owned:
`<data_dir>/relaunch_context.json` (handoff). No other non-Ledger state.

## 5. Internal design

```
memory/
  service.py          handlers, lifecycle, index rebuild
  api.py
  config.py
  records.py          MemoryRecord, canonicalization, blob refs
  embedding.py        embed_text (hashing trick), cosine_similarity  (v1 verbatim)
  index.py            InvertedIndex + EmbeddingIndex + TagIndex per kind
  scoring.py          Scorer; Query normalization/tokenization
  confidence.py       decay, contradiction, reconsolidation, causal links
  working.py          WorkingMemory (port of ShortTermMemory)
  consolidation.py    Consolidator
  migrate_v1.py       memory.jsonl importer (called by kernel `migrate-v1`)
```

**Retrieval scoring** (per candidate, all in [0,1]):

```
lexical    = BM25-lite: Σ_terms tf·idf / (len_norm)             (stdlib; postings from InvertedIndex)
embedding  = cosine(embed(query), rec.embedding)                 (v1 hashing trick)
recency    = 2^(-(now - rec.ts) / recency_half_life)
confidence = Confidence.current(rec, now)                        (v1 score_confidence)
score      = w_l·lexical + w_e·embedding + w_r·recency + w_c·confidence
```

Candidates come from the union of the top-200 lexical and top-200
embedding hits (filters applied first), scored, sorted, truncated to
`k`, then to `budget_tokens` if given (`truncated:true`). Accessing a
record emits a batched `record.accessed` so `reconsolidate` can reset
its decay clock (v1 semantics: touched memories keep confidence).

**Confidence** (v1 `score_confidence`): `base · 2^(-(now - last_accessed)/half_life)`;
a contradiction halves both records' base and emits
`record.confidence.changed{reason:"contradiction"}`, idempotent per pair;
`find_contradictions` compares new semantic records against existing
ones by cosine ≥ threshold *and* a negation/antonym heuristic (v1's
`find_contradictions`), emitting `memory.contradiction.flagged` for
Reflection rather than deciding truth itself.

**Consolidation state machine** (on `system.tick.sleep`):

```
IDLE ─tick─▶ COLLECT (episodic records in window, not yet distilled, ≤ max_episodes)
      ─▶ DISTILL: if a real provider is available → cognition.think{purpose:"consolidate", messages:[episodes as compact lines],
                   expected:{kind:"json"}} → lessons[{content, confidence, supports:[refs], tags}]
                   else floor → skip distillation (floor:true in report), never invent lessons
      ─▶ WRITE lessons to memory:semantic with causal links to supporting episodes; mark episodes distilled
      ─▶ CONTRADICT: run find_contradictions over new lessons; halve; flag
      ─▶ PRUNE: per-subkind keep counts (v1 _prune_kind) + tombstone anything below prune_below_confidence
      ─▶ REPORT: memory:consolidation pass.completed; emit memory.consolidated
      ─▶ IDLE
```

A pass is interruptible between stages by `system.pause`; a crash
mid-pass leaves `pass.started` without `pass.completed`, and the next
tick resumes from COLLECT (episodes already marked distilled are
skipped — idempotent).

**Concurrency:** appends serialized per stream through the Ledger's
CAS; indexes updated by a single writer task fed from `ledger.tail`;
retrieval reads a consistent snapshot of the index (copy-on-write
swap). `start()` rebuilds indexes from snapshots + tail, loads the
handoff; `stop()` writes the handoff, cancels the tail; `health()`
reports index freshness (seq lag) and rebuild errors.

## 6. Key behaviors — worked scenarios

**S1 — Retrieval for a chat turn (Flow 1).** Orchestration sends
`memory.retrieve {query:"how does the task queue pick the next task", kinds:["episodic","semantic","procedural"], k:8, budget_tokens:1200}`.
Lexical hits `_next_task`, `queue`, `pending`; embedding hits a
research finding on project rollups; recency favors yesterday's task
outcomes; confidence demotes a contradicted old note. Reply in 6 ms
with 8 items (two truncated to the budget, `truncated:true`),
`record.accessed` batched for the returned refs. Orchestration places
them in the `memory` elastic block.

**S2 — Task outcome becomes an episode with a causal link (Flow 2).**
`task.completed {task_id:"a1", result_summary:"…", verification_ref:"…"}` →
Memory appends `record.stored` to `memory:episodic`
`{subkind:"task_outcome", succeeded:true, task_type:"patch", tags:["task:a1","subject:src/x.py"]}`
and `link.causal {consequence:<this>, antecedent:<the task.created episode ref>}`;
emits `memory.stored`. Later `learn.competence.updated{task_type:"patch", success_rate:0.72}`
updates the procedural record `strategy:patch-default`'s stats.

**S3 — Sleep with a real provider (Flow 8).** `system.tick.sleep{window_seconds:86400}`:
COLLECT finds 143 undistilled episodes; DISTILL sends one 9 k-token
`consolidate` request; the model returns 6 lessons, e.g.
`{"content":"SEARCH/REPLACE drafts succeed far more often than full rewrites on files over 100 lines","confidence":0.8,"supports":["memory:episodic#4411","#4419","#4433"],"tags":["self_patch","lesson"]}`;
WRITE appends them to `memory:semantic` with causal links; CONTRADICT
finds one lesson at cosine 0.86 with an older note claiming the
opposite → both halved, `memory.contradiction.flagged` to Reflection;
PRUNE tombstones 212 old `turn` episodes over the keep count and 9
records under 0.15 confidence; `memory.consolidated{distilled:6, pruned:221, contradictions_resolved:1, floor:false}`.

**S4 — Degradation: sleep with no provider, then a crash.** Same tick
with Claude Code and Gemini exhausted: DISTILL gets `floor:true`, so no
lessons are written and the report says `floor:true, distilled:0`
(principle 4.5 — no fabricated lessons); CONTRADICT/PRUNE still run.
Midway through PRUNE the process dies: `pass.started` exists without
`pass.completed`; on restart, indexes rebuild from snapshot + tail
(tombstones already appended are honored), the next tick resumes
COLLECT and finds nothing new to distill — the pass completes cleanly.
Duplicate `memory.store` commands (same `idempotency_key`) during the
replay window return `memory.stored` for the existing ref without
appending.

## 7. Design considerations and tradeoffs

- **Four kinds, one API.** `AGI-03` §4 and `AGI-04` §3: the working/
  episodic/semantic/procedural split is the consensus taxonomy; exposing
  one `retrieve` with a `kinds` filter keeps callers simple while letting
  each kind keep its own index and lifecycle.
- **Hybrid scoring without dependencies.** A hashing-trick embedding is
  crude next to a learned model, but it is stdlib, deterministic, and
  already proven in v1; BM25-lite lexical recall covers exact
  identifiers (file paths, function names) the embedding misses.
  Weights are config so a real embedding adapter can be added later
  behind the same `Index` protocol (principle 4.14).
- **Consolidation is where learning actually happens for an LLM
  system** (`AGI-04` §3, §6: "much of what looks like learning… is
  happening in the memory subsystem"). Bounding each pass (window,
  episode cap, one model call) keeps it affordable; refusing to
  distill on the floor keeps it honest.
- **Tombstones, not deletes** (principle 4.4; `harness-05` §7): v1's
  `_rewrite` compaction of the JSONL file is replaced by append-only
  tombstones plus periodic snapshots; the log grows, but truth is never
  lost and Reflection can audit why something was forgotten.
- **Contradiction as a flag, not a verdict.** Memory halves confidence
  (v1 behavior) and *tells Reflection*; deciding which side is true is
  meta-cognition (`AGI-03` §9), not storage.
- **Working memory stays tiny and separate.** It is the LLM's context
  proxy (`AGI-03` §4); making it a Ledger stream gives crash-resume
  (`02` Flow 7) without turning every keystroke into a semantic record.
- **Alternatives rejected:** a vector database (dependency; unnecessary
  at this scale); letting Cognition retrieve automatically (hides
  retrieval cost/policy from the loop owner); physical deletes (breaks
  replay and audit).

## 8. Safety, degradation, and failure modes

| Condition | Behavior |
|---|---|
| Provider down during sleep | Distillation skipped, `floor:true`; prune/contradiction still run |
| Ledger unavailable | Retrieval keeps serving from the in-memory index (stale-ok, `health` degraded); stores are refused with `index_unavailable`; nothing is buffered unbounded |
| Malformed `memory.store` | Validation failure at publisher; if received, error reply/nack, no append |
| Handler crash | Kernel marks degraded; index writer task restarts and re-tails from last applied seq |
| Restart mid-pass | Resumes idempotently (§5) |
| Duplicate messages | `idempotency_key` → existing ref; `record.accessed` batching is naturally idempotent |
| Oversized content | Blob ref; the index stores only the first 4 KB of tokens for lexical matching |
| Prompt-injection content stored | Stored verbatim (it is data); retrieval returns it inside a labeled block; never executed |
| `system.pause` | In-flight append completes; consolidation pauses between stages; retrieval continues (read-only) |
| `system.stop` | Handoff saved; tail cancelled; snapshot written |

Guaranteed floor: retrieval and storage work with no provider; the
index rebuilds from the log alone.

## 9. Testing strategy

- Contract tests for every produced type; `retrieve`/`store` handlers with valid and invalid payloads.
- Unit: `embedding.py` (v1 tests), `InvertedIndex` (postings, filters), `Scorer` (each term, weights, budget truncation), `Confidence` (decay math, halving idempotence, reconsolidation on access — port v1 tests), `find_contradictions`, `WorkingMemory` (window trimming, `save/load_handoff` — port v1 `short_term` tests), `Consolidator` stages (collect bounds, distill parse incl. floor, write links, prune keeps, resume after crash), `migrate_v1` mapping (each v1 kind → stream, idempotent re-run).
- Integration: `test_flow_1_retrieval_feeds_turn`, `test_flow_8_sleep_distills_and_prunes` (memory bus + `FakeProvider` via a fake cognition), `test_flow_8_sleep_on_floor_writes_no_lessons`, `test_flow_7_working_memory_survives_restart` (sqlite ledger).
- Property: index rebuilt from the log equals the incrementally-maintained index; `score` ∈ [0,1]; tombstoned refs never returned.
- Mocks: fake cognition responder on the bus; `FakeClock` for decay.

## 10. Build steps (an agent picks this up here)

Size: **M**. Parallelizable within: (records/embedding/index/scoring) ∥ (confidence/consolidation) ∥ (working/migrate).

1. Skeleton, config, registry, boundary/contracts tests. *Accept:* self-check boots.
2. `records.py`, `embedding.py` (v1 port + tests), blob refs. *Accept:* round-trip tests.
3. Streams + `index.py` with rebuild from snapshot/tail; property test. *Accept:* rebuild equality.
4. `scoring.py` + `memory.retrieve` handler + reply; budget truncation. *Accept:* S1 test.
5. `confidence.py` port (decay, halving, reconsolidate, causal links) + `record.accessed` batching. *Accept:* v1 tests pass.
6. Event handlers for `turn.completed`, `task.*`, `research.finding.recorded`, `learn.*`. *Accept:* S2 test.
7. `working.py` port + handoff + `system.started/stopping`. *Accept:* restart test.
8. `consolidation.py` with stages, resume, floor behavior, `memory.consolidated`. *Accept:* S3/S4 tests.
9. `migrate_v1.py` + kernel hook. *Accept:* import of a fixture `memory.jsonl` is idempotent.
10. `src/memory/*` and `consolidation.py` adapters; v1 suite green; README, EVOLUTION milestone.

## 11. Migration notes

- `MemoryStore.add/get/query/delete/remember` → `memory.store` + streams; `delete` → tombstone. `JSONFileMemoryStore._rewrite` is dropped (append-only).
- `semantic_search`, `score_confidence`, `find_contradictions`, `flag_contradiction`, `consolidate_contradictions`, `reconsolidate`, `link_causal/causes_of/consequences_of` → `scoring.py`/`confidence.py` with the same math; tests moved.
- `ShortTermMemory` → `working.py`; `save/load_and_clear` → handoff (path unchanged so a v1→v2 relaunch hands off).
- `run_consolidation(store, reflection_agent, …)` split: pruning/distillation here; the "reflect on the window" half → Reflection (`reflect.patterns.found`), triggered by the same `system.tick.sleep`.
- v1 records with `kind` in `{turn, outcome, takeaway, interest, task_event, llm_spend, applied_*, research_finding, rejected_proposal, autonomous_action, …}` map per `06` §5; unknown kinds → episodic with `subkind=kind`.
- Behavior change: retrieval adds lexical + recency terms (v1 was cosine × confidence only); default weights are config.

## 12. Open questions

1. **Contract gap:** `03` §4.9 has no `memory.contradiction.flagged`; proposed here. *Default:* add (event, non-breaking).
2. **Contract gap:** `memory.retrieve` payload needs `budget_tokens`, `filters.session_id/task_type`; reply needs `truncated`. *Default:* optional fields.
3. `turn.completed` is referenced in `02` Flow 1 but absent from the `03` catalog (§4.4 lists only `task.*`). *Default:* Orchestration emits `turn.completed {session_id, request, response, task_ref?, mood}`; add to contracts.
4. Should `record.accessed` be emitted at all (log growth)? *Default:* yes, batched hourly per record; it is what makes reconsolidation replayable.
5. Semantic lesson confidence from the model is self-reported; *Default:* cap at 0.8 at write time; only repeated support raises it (Reflection's calibration decides later).
