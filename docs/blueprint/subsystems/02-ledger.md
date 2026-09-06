# 02 — Ledger (`simorgh/ledger/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). This spec refines those; it may not
> contradict them.

**Layer:** 0 Substrate
**Owner (build):** built, Phase 0 (2026-09-06)
**Status:** built
**Depends on (contracts only):** `contracts.protocols.Ledger/Clock`, `contracts.envelope` (canonical JSON), `contracts.messages.system` (for `system.health`)
**v1 code that migrates here:** `src/memory/long_term.py` (`JSONFileMemoryStore` file format, fsync/atomic-rewrite discipline, `MemoryRecord` shape — the *storage* half; retrieval/embedding/confidence logic migrates to `memory`), `src/orchestrator/activity_log.py` (durable activity record → `activity` stream), the event-sourcing discipline of `src/orchestrator/tasks.py` (`_fold` → `Projection`).

## 1. Purpose and responsibilities

The Ledger is the system's memory of everything that ever happened:
an append-only store of typed events organized into named streams, with
compare-and-swap appends for single-writer coordination, snapshots so
projections need not replay from the beginning of time, a
content-addressed blob store for large payloads, tailing so subsystems
can react to appends, idempotent writes so at-least-once delivery never
double-records, and a retention/compaction policy for the *record
itself*. Every durable fact in Simorgh v2 — a task's status, a
project's rollup, a memory, a competence estimate, the Self Model, a
trace of a decision — is a projection over Ledger streams. Nothing is
overwritten; current state is always reconstructible by replay.

**Responsibilities (owns):**
- The `Ledger` protocol and its backends: `memory` (tests), `jsonl` (default, v1-compatible), `sqlite`, `dynamodb` (optional).
- Stream naming conventions and the stream registry.
- CAS appends (`expected_seq`), idempotency-key dedupe per stream.
- Snapshots (`snapshot`/`load_snapshot`) and the `Projection` helper.
- The blob store (`blob:sha256:<hex>` refs), local `blobs/` and S3 on `aws`.
- Record compaction/retention per stream prefix, done atomically.
- `tail()` subscriptions to new events on a stream (or prefix).
- Durability guarantees (fsync on append for `jsonl`; WAL for `sqlite`).
- The v1 record format compatibility that makes `migrate-v1` a replay.

**Explicit non-responsibilities (belongs elsewhere):**
- Semantics of any stream's events (what `task.completed` means) — the owning subsystem.
- Retrieval/ranking/embeddings/confidence decay over memories — `memory`.
- Deciding retention policy values — configuration (Kernel); the Ledger executes it.
- Transport of messages — the Bus (which *uses* the Ledger for `trace:*`).

**Principles this subsystem is the primary enforcer of:** 4.4 (append-only, derived views recomputable), 4.12 (transparent file-based state), 4.14 (stdlib core).

## 2. Position in the architecture

Layer 0, created by the Kernel immediately after config and before the
Bus (the Bus's trace writer needs a Ledger client). It appears in every
flow of `02` §5 as the sink of `task:*`, `project:*`, `trace:*`,
`memory:*`, `self:model`, `action:*` events, and is the mechanism behind
Flow 7 (resume-from-ledger). Imports: `simorgh.contracts.*` and stdlib
only; `dynamodb.py`/`s3` code lazily imports `boto3`.

## 3. Interfaces

### 3.1 Messages consumed
None. Subsystems call the Ledger client directly (it is substrate, like
the Bus). Compaction is triggered by the Kernel's `system.tick.sleep`
via a direct call from the Ledger's own `Service`, which subscribes to:

| Type | Pattern | Semantics | What this subsystem does with it |
|---|---|---|---|
| `system.tick.sleep` | exact | event | Runs retention/compaction per policy; emits `system.metrics` with sizes |

### 3.2 Messages produced
| Type | Semantics | Payload summary | Consumers |
|---|---|---|---|
| `system.health` | event | `{subsystem:"ledger", status, detail}` — fsync failures, disk pressure, CAS conflict storms, backend errors | kernel, interface |
| `system.metrics` | event | `{subsystem:"ledger", counters:{appends, conflicts, dedupes, blobs_put}, gauges:{streams, bytes_total, bytes_by_prefix.*, snapshots}}` | kernel, interface |

### 3.3 Request/reply APIs served
None at the message level.

### 3.4 Python protocol (`api.py`)

```python
# simorgh/ledger/api.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol
from simorgh.contracts.protocols import Ledger, Subscription     # re-export

@dataclass(frozen=True)
class Event:
    stream: str                 # "task:abc123"
    seq: int                    # 1-based, dense per stream; 0 = unassigned (before append)
    id: str                     # uuid4 (or the originating Message.id)
    type: str                   # catalog type, e.g. "task.completed"; v1 kinds allowed under "v1.<kind>"
    ts: float
    trace_id: str | None
    causation_id: str | None
    idempotency_key: str | None
    payload: dict[str, Any]

    @staticmethod
    def new(stream: str, type: str, payload: dict, *, trace_id=None, causation_id=None,
            idempotency_key=None, ts: float | None = None) -> "Event": ...

class ConflictError(Exception):          # CAS failed: expected_seq != head
    def __init__(self, stream: str, expected: int, actual: int): ...

class LedgerBackend(Protocol):
    async def start(self) -> None
    async def stop(self) -> None
    async def head(self, stream: str) -> int                                   # 0 if empty
    async def append(self, event: Event, *, expected_seq: int | None) -> int  # assigns seq; raises ConflictError
    async def find_by_idempotency(self, stream: str, key: str) -> int | None
    async def read(self, stream: str, *, from_seq: int, limit: int | None) -> list[Event]
    async def streams(self, prefix: str) -> list[str]
    async def write_snapshot(self, stream: str, state: dict, at_seq: int) -> None
    async def read_snapshot(self, stream: str) -> tuple[dict, int] | None
    async def truncate_below(self, stream: str, seq: int) -> int              # compaction primitive
    async def delete_stream(self, stream: str) -> None
    async def put_blob(self, data: bytes, *, content_type: str) -> str        # "blob:sha256:<hex>"
    async def get_blob(self, ref: str) -> bytes
    async def stat(self) -> dict                                              # sizes for metrics

class Projection(Protocol):
    """Base for derived views. Subsystems subclass; the helper handles snapshot+replay."""
    stream_prefix: str
    snapshot_every: int = 200
    def apply(self, event: Event) -> None
    def state(self) -> dict                    # serializable, for snapshot
    def load(self, state: dict) -> None
```

Public client `simorgh.ledger.client.LedgerClient(backend, *, clock,
source)` implements `contracts.protocols.Ledger`:

```python
class LedgerClient(Ledger):
    async def append(self, stream, event, *, expected_seq=None) -> int
    async def read(self, stream, *, from_seq=0, limit=None) -> list[Event]
    async def tail(self, stream_or_prefix, handler) -> Subscription
    async def snapshot(self, stream, state, at_seq) -> None
    async def load_snapshot(self, stream) -> tuple[dict, int] | None
    async def streams(self, prefix) -> list[str]
    # additions this spec proposes for the protocol (see §12):
    async def put_blob(self, data: bytes, *, content_type="application/octet-stream") -> str
    async def get_blob(self, ref: str) -> bytes
    async def rebuild(self, projection: Projection, stream: str) -> int   # load snapshot, replay tail, returns seq
    async def materialize(self, projection: Projection, stream: str) -> None  # rebuild + snapshot if due
```

`append` semantics: validates the event (stream name grammar, canonical
JSON payload, no NaN), applies idempotency dedupe (returns the existing
seq without writing), then CAS. Returns the assigned `seq`.

### 3.5 Configuration

```toml
[ledger]
backend = "jsonl"                        # memory | jsonl | sqlite | dynamodb
data_dir = "${runtime.data_dir}/ledger"  # jsonl/sqlite location; blobs under ${data_dir}/blobs
fsync = true                             # jsonl: fsync every append
snapshot_every = 200                     # default Projection cadence (events since last snapshot)
blob_inline_threshold = 4096             # payload strings above this MUST be refs (validated)
tail_poll_ms = 100                       # sqlite/dynamodb tail polling

[ledger.retention]                       # per stream prefix; "forever" or a duration
"trace:" = "7d"
"dead:" = "30d"
"activity" = "90d"
"task:" = "forever"                      # compaction = snapshot + truncate_below(snapshot_seq - keep_tail)
"memory:" = "forever"                    # memory subsystem prunes semantically via its own events
keep_tail = 50                           # events kept below a snapshot for debugging

[ledger.dynamodb]
table = "simorgh-${deployment}-ledger"
bucket = "simorgh-${deployment}-blobs"   # S3 for blobs and payloads > 350 KB
```

Environment overrides: `SIMORGH_LEDGER_BACKEND`, `SIMORGH_LEDGER_DIR`.

## 4. Data model and Ledger streams

### 4.1 Stream naming
`<kind>[:<id>]`, lowercase, `[a-z0-9_.:-]`, max 128 chars. Registry
(`streams.py`) of known prefixes with the owning subsystem:

| Prefix | Owner | Contents |
|---|---|---|
| `trace:<trace_id>` | bus | every message in one causal chain |
| `dead:<type>` | bus | dead-lettered messages |
| `activity` | orchestration/interface | conversation turns, tool invocations (v1 `ActivityLog`) |
| `task:<task_id>` | planning | task lifecycle events; the Worker's step log |
| `project:<project_id>` | planning | plan proposed/reviewed/approved/revised, rollups |
| `action:<action_id>` | guardian/execution | proposed → approved/denied → result |
| `verify:<verification_id>` | verification | checklists, verdicts |
| `memory:episodic`, `memory:semantic`, `memory:procedural` | memory | records + confidence/link events |
| `self:model` | worldmodel/reflection | Self Model revisions |
| `world:<facet>` | worldmodel | observations |
| `learn:outcomes`, `learn:competence`, `learn:patches`, `learn:skills` | learning | |
| `reflect:<window_id>` | reflection | |
| `curiosity:interests`, `curiosity:candidates` | curiosity | |
| `persona:state`, `persona:user_model` | persona | |
| `cognition:budget:<provider>` | cognition | spend records (v1 `llm_spend`) |
| `schedule` | kernel | durable reminders/schedules |
| `system` | kernel | started/stopped/state changes |

### 4.2 On-disk layout (`jsonl` backend)

```
${data_dir}/ledger/
  streams/<escaped-stream-name>.jsonl     one file per stream; one canonical-JSON Event per line
  index.json                              {stream: {head, bytes, last_ts}} rebuilt on start if missing/stale
  snapshots/<escaped-stream-name>.json    {"at_seq": N, "state": {...}, "ts": ...}
  idem/<escaped-stream-name>.idx          append-only "key\tseq" lines (rebuildable from the stream)
  blobs/<aa>/<sha256>                     content-addressed; a sidecar .meta with content_type/size
  LOCK                                    advisory lock (fcntl on POSIX; msvcrt on Windows) — single writer
```

Line format (matches `Event` field order; strict canonical JSON):

```json
{"stream":"task:abc123","seq":7,"id":"…","type":"task.completed","ts":1788700000.1,"trace_id":"…","causation_id":"…","idempotency_key":null,"payload":{…}}
```

**v1 compatibility.** v1's `~/.simorgh/memory.jsonl` lines are
`{"id","kind","content","created_at","metadata"}`. The `jsonl` backend's
`read_v1(path)` iterator maps each to
`Event(stream=route(kind, metadata), type=f"v1.{kind}", ts=created_at,
payload={"content":…, **metadata}, idempotency_key=f"v1:{id}")`, where
`route` is the table in `06-migration-from-v1.md` §5. `migrate-v1` is
therefore a plain replay through `append`, idempotent by key.

### 4.3 `sqlite` schema
```
events(stream TEXT, seq INTEGER, id TEXT, type TEXT, ts REAL, trace_id, causation_id,
       idempotency_key, payload TEXT, PRIMARY KEY(stream, seq))            -- CAS = PK uniqueness
idempotency(stream, key, seq, PRIMARY KEY(stream, key))
snapshots(stream PK, at_seq INT, state TEXT, ts REAL)
blobs(sha256 PK, content_type, size INT, data BLOB)                       -- or path if > 1 MB
```
CAS is a single `INSERT` with `seq = expected_seq + 1` (or `head+1` when
`expected_seq` is `None`, inside `BEGIN IMMEDIATE`); a PK violation maps
to `ConflictError`.

### 4.4 `dynamodb` schema
Table PK `stream` (S), SK `seq` (N); attributes = event fields; conditional
`attribute_not_exists(seq)` implements CAS; GSI `idem` on
`(stream, idempotency_key)`; item payloads > 350 KB spill to S3
(`payload_ref`). Snapshots are items with SK `-1`. Blobs in S3 under
`blobs/<sha256>`.

### 4.5 Projections
`Projection` subclasses live in the owning subsystems (e.g.
`planning.projections.TaskView`). The Ledger provides `rebuild()`:
load snapshot (if any) → replay `read(stream, from_seq=at_seq+1)` →
return head; and `materialize()` which snapshots when `head -
at_seq >= snapshot_every`. Replay is deterministic because events are
immutable and totally ordered per stream.

## 5. Internal design

```
simorgh/ledger/
  api.py         Event, ConflictError, LedgerBackend, Projection
  client.py      LedgerClient (validation, idempotency, blobs threshold check, rebuild/materialize, tail)
  streams.py     name grammar, escape/unescape for filenames, prefix registry
  memory.py      InMemoryBackend (dict[str, list[Event]]; deterministic; for tests)
  jsonl.py       JsonlBackend (per-stream files, fsync, index, lock, atomic rewrite)
  sqlite.py      SqliteBackend (WAL)
  dynamodb.py    DynamoBackend (lazy boto3; S3 blobs)
  blobs.py       LocalBlobStore, S3BlobStore; sha256 addressing; sidecar meta
  compaction.py  RetentionPolicy parsing; plan → execute (snapshot, truncate, rewrite, delete)
  migrate_v1.py  read_v1(path) iterator + route table (used by kernel's migrate-v1 command)
  service.py     Service: subscribes system.tick.sleep; runs compaction; emits health/metrics
  config.py
```

### 5.1 Append path (`jsonl`)
```
append(stream, ev, expected_seq):
  validate name/payload; if any string field > inline_threshold and not a blob ref → ValidationError
  with stream_lock(stream):                      # asyncio.Lock per stream in-process; file LOCK across processes
    if ev.idempotency_key and (seq := idem.get(stream, key)) is not None: return seq   # dedupe
    head = index[stream].head
    if expected_seq is not None and expected_seq != head: raise ConflictError
    ev = replace(ev, seq=head+1)
    line = canonical_json(ev) + "\n"
    f.write(line); f.flush(); os.fsync(f.fileno())   # if config.fsync
    idem.record(...); index.update(...)
    notify_tailers(ev)
  return ev.seq
```
Reads use the index for byte offsets per seq (built lazily; a corrupt
trailing partial line — a crash mid-write — is detected by JSON parse
failure at EOF and truncated on start with a `system.health` warning,
mirroring v1's "loses at most the record that was mid-write").

### 5.2 Compaction (record, not context)
On `system.tick.sleep` (or `simorgh ledger compact`): for each stream,
find its prefix policy. Duration policies delete whole streams whose
`last_ts` is older than the window (`trace:*`, `dead:*`), or truncate
events older than the window for singleton streams (`activity`).
`forever` streams with a snapshot are truncated to `snapshot.at_seq -
keep_tail` (the snapshot preserves state; the tail preserves recent
debuggability). Truncation is an atomic rewrite: write tmp → fsync →
`os.replace`, exactly v1's `_rewrite` discipline. A `ledger:compaction`
event records what was removed (counts, not contents).

### 5.3 Tail
`tail(stream_or_prefix, handler)`: `memory`/`jsonl` notify in-process
subscribers synchronously after append (fire-and-forget tasks);
`sqlite`/`dynamodb` poll `head` per subscribed stream every `tail_poll_ms`
and deliver new events in order. Used by projections that must stay
live (Interface's vitals, Planning's backlog view) without re-reading.

### 5.4 Concurrency and multi-process
In `single` mode all writers share one process; per-stream
`asyncio.Lock` suffices. In `local-multi`, `jsonl` takes an advisory
file lock around append (cheap; contention is per stream) — but the
*recommended* multi-process backend is `sqlite`, whose `BEGIN IMMEDIATE`
serializes writers with a 5 s `busy_timeout`. `expected_seq` CAS is how
Planning's `task.claim` guarantees a single claimant across Worker
processes (`07-planning.md`): the claim appends `task.claimed` with
`expected_seq = head_seen`; a loser gets `ConflictError` and replies
`granted: false`.

### 5.5 Lifecycle
`start()` opens/validates the data dir, rebuilds `index.json` if stale,
verifies the last line of each stream, takes the LOCK (jsonl). `stop()`
flushes, releases. `health()`: `degraded` on fsync errors or free disk
< 5 %, `down` if the data dir is unwritable.

## 6. Key behaviors — worked scenarios

**S1 — Single claimant across two Worker processes (Flow 2/7).** Both
`orchestration@w1` and `@w2` receive `task.available{T9}` (a redelivery
after a crash). Each requests `task.claim`. Planning handles both (in
order on key `task:T9`): for w1 it reads head=4, appends
`task.claimed{worker:w1}` with `expected_seq=4` → seq 5, replies
`granted:true`. For w2 it reads head=5, sees the latest event is an
unexpired claim, replies `granted:false` without appending — or, in a
race where Planning itself is multi-instance, w2's append with
`expected_seq=4` raises `ConflictError` and Planning replies
`granted:false`. Exactly one Worker proceeds; the Ledger enforced it.

**S2 — Projection rebuild after restart (Flow 7).** Kernel restarts.
Planning constructs `TaskView(stream_prefix="task:")` and calls
`ledger.rebuild(view, "task:T9")`: snapshot at seq 200 loads; events
201..217 replay (`task.step`×15, `task.paused`, `task.claimed`); the
view shows `status=in_progress, claim lease expired`; Planning re-emits
`task.available`. Nothing was lost; nothing needed a mutable status
field.

**S3 — Failure: disk full during append.** `fsync` raises `OSError
(ENOSPC)`. The backend rolls back the in-memory index change, does *not*
record the idempotency key, raises `LedgerUnavailable`; the calling
subsystem nacks its message (redelivered later); the Ledger emits
`system.health{status:down, detail:"ENOSPC"}`; Guardian, seeing Ledger
`down`, denies non-read-only actions (an action whose result cannot be
recorded must not run — `09-guardian.md`). After space is freed the
next append succeeds; the partial line (if any) was never written
because the write happens before fsync but the index update after — on
restart the trailing partial line is truncated per §5.1.

**S4 — Idempotent replay of v1 data.** `simorgh migrate-v1` iterates
`read_v1(~/.simorgh/memory.jsonl)` (6,000 records) → `append` each with
`idempotency_key="v1:<id>"`. Run twice, the second run appends zero
events (`counters.dedupes = 6000`).

**S5 — Compaction keeps the story.** After 30 days, `trace:*` streams
older than 7 d are deleted (thousands of streams, gigabytes); `task:*`
streams keep every event until snapshotted, then keep the snapshot +
last 50 events. `simorgh trace <old-id>` reports "compacted" honestly
rather than an empty result.

## 7. Design considerations and tradeoffs

- **Event streams over a mutable database.** A mutable status column is
  faster to query and slower to trust: v1 already learned (tasks.py,
  `project_status()`) that a parent status that *can* diverge from its
  children *will*. Replay + snapshots gives both truth and speed.
  (harness-01 "append-only durable state"; harness-05 §7.)
- **One file per stream** (not v1's one file for everything): bounded
  reads per task, trivial retention per prefix, no giant rewrite to
  prune one stream. Cost: many small files; mitigated by the index and
  by `sqlite` for large deployments.
- **fsync on every append** costs ~1–5 ms per write on SSD. Accepted:
  the rate of durable events is bounded by LLM/tool latency, and v1
  proved the "lose at most the mid-write record" guarantee is worth it.
  Configurable off for tests.
- **Blob threshold enforced at append time** (not just recommended):
  otherwise a single file-content payload bloats a stream and slows
  every replay. Same reasoning as Claude Code's per-message budget
  reduction — the cheapest context intervention is never storing the
  bulk inline (harness-01 compaction layer 1).
- **Idempotency in the store, not only in handlers**: at-least-once
  delivery (`01-bus.md`) means duplicates are normal; dedupe at the
  Ledger makes every projection correct even if a handler forgets.
- **CAS instead of locks for coordination**: works identically on
  `jsonl`, `sqlite`, and DynamoDB (conditional put), so single-claimant
  logic is backend-agnostic (AGI-04 §10 multi-agent orchestration needs
  exactly-one-worker semantics somewhere; here it is the log).
- **Retention as policy, deletion as an event**: forgetting is
  explicit and auditable (AGI-04 §3 "forgetting/pruning" is a design
  question, not an accident).

## 8. Safety, degradation, and failure modes

| Condition | Behavior |
|---|---|
| Crash mid-write | Trailing partial line truncated on start; `system.health` warn; at most one event lost, never a corrupted stream |
| CAS conflict | `ConflictError` to the caller; never retried by the Ledger (the caller decides — usually "someone else won") |
| Duplicate append (same idempotency key) | Returns existing seq; no write; counted |
| Disk full / unwritable | `LedgerUnavailable`; health `down`; Guardian denies non-read-only actions system-wide until healthy |
| Corrupt snapshot | Ignored with a warning; full replay from seq 1 |
| Stream name invalid / payload too large / NaN | `ValidationError` at the caller |
| Backend missing (`boto3` absent for dynamodb) | Config-time `BackendUnavailable`; Kernel refuses to start in that mode |
| `system.pause` | No effect (appends continue; pausing must itself be recorded) |
| `system.stop` | Flush + fsync + release lock; compaction in progress finishes its current atomic rewrite then aborts |

Guaranteed floor: `memory` and `jsonl` backends need nothing but a
writable directory; the Kernel falls back to `jsonl` if a configured
backend is unavailable *only* when explicitly allowed (`allow_fallback =
true`), otherwise it refuses to start — silent data-location changes are
worse than a clear failure.

## 9. Testing strategy

- **Contract tests**: `Event` canonical JSON round-trip; stream grammar; blob threshold enforcement; `system.metrics`/`system.health` payloads validate.
- **Unit tests** (`tests/simorgh/ledger/`): CAS success/conflict; idempotency dedupe; head/read/limit; snapshots + `rebuild` (empty, snapshot-only, snapshot+tail, corrupt snapshot); tail delivery order; escape/unescape of stream names; `read_v1` mapping for every v1 kind in `06` §5; compaction plans for each policy; atomic rewrite leaves old-or-new never partial (inject failure between tmp write and replace).
- **Backend parity**: parametrized over `memory`, `jsonl`, `sqlite`; `dynamodb` only under `SIMORGH_TEST_AWS=1` (moto is *not* used — no third-party deps; the aws suite is skipped without credentials).
- **Property tests**: (1) replaying any prefix of a stream through a `Projection` yields the same state as the snapshot taken at that seq; (2) for any sequence of concurrent CAS appends from N tasks, exactly one succeeds per `expected_seq`; (3) crash simulation (truncate file at random byte) never yields a parse error after `start()`.
- **Multi-process test**: two `multiprocessing` writers on `sqlite` (and `jsonl` with LOCK) interleave appends; seqs are dense and unique.
- **Integration**: `test_flow_7_resume_from_ledger.py` with Planning/Orchestration fakes; `test_migrate_v1_is_idempotent.py` against a fixture copy of a real `memory.jsonl`.
- **Mocks**: `FakeClock` for retention windows; a fault-injecting file object for fsync errors.

## 10. Build steps (an agent picks this up here)

1. Skeleton per `05` §2; `api.py` (Event, errors, backend + Projection protocols); `streams.py` grammar + registry + tests. *Accept:* boundary test; grammar tests.
2. `memory.py` backend + `client.py` (validation, idempotency, CAS, rebuild/materialize, tail). *Accept:* unit + property (1),(2) on `memory`.
3. `blobs.py` local store + threshold enforcement in client. *Accept:* blob round-trip; oversize inline payload rejected.
4. `jsonl.py` (files, index, fsync, LOCK, partial-line recovery, snapshots, idem index). *Accept:* parity suite on `jsonl`; crash property (3); multi-process LOCK test.
5. `compaction.py` + `service.py` (sleep tick → compaction; health/metrics). *Accept:* policy tests; atomic rewrite fault-injection test.
6. `migrate_v1.py` (`read_v1` + route table). *Accept:* fixture replay idempotent; every v1 kind routed.
7. `sqlite.py`. *Accept:* parity suite; multi-process CAS test.
8. Integration Flow 7 + migrate test. *Accept:* green.
9. `dynamodb.py` + `S3BlobStore` (Phase 5). *Accept:* parity under `SIMORGH_TEST_AWS=1`, skipped otherwise.
10. README build log, config table, EVOLUTION milestone.

Size: **M–L**. Parallelizable: steps 4 and 7 after step 2; step 9 independent.

## 11. Migration notes

- `JSONFileMemoryStore.add` (fsync-per-append) and `_rewrite` (tmp →
  fsync → `os.replace`) move into `jsonl.py` nearly verbatim; `MemoryRecord`
  stays in `memory` as that subsystem's projection over `memory:*`
  streams — the Ledger stores `Event`s, not `MemoryRecord`s.
- `MemoryStore.query/semantic_search/score_confidence/link_causal/find_contradictions/reconsolidate`
  → `05-memory.md` (they are retrieval and semantics, not storage).
- `ActivityLog` → the `activity` stream (Orchestration/Interface append; Interface's `log` renders).
- `tasks.py::_fold` → the `Projection` pattern (`planning.projections`).
- Tests: `tests/test_long_term.py` storage cases (durability, atomic rewrite, delete/compact) move to `tests/simorgh/ledger/`; retrieval cases move with `memory`.
- Data: `simorgh migrate-v1` replays `~/.simorgh/memory.jsonl` once (idempotent); v1's file is left untouched.

## 12. Open questions

1. **Protocol additions.** `03` §6's `Ledger` protocol lacks `put_blob/get_blob`, `rebuild/materialize`, `truncate`. *Default:* add them to `contracts.protocols.Ledger` in Phase 0 (flagged to the parent).
2. **Trace volume.** Even sampled, `trace:*` will dominate bytes. *Default:* 7-day retention plus a `trace_max_bytes` cap that compacts oldest-first when exceeded.
3. **`memory:*` retention.** The Memory subsystem prunes semantically (confidence decay); should the Ledger also cap it? *Default:* no hard cap; Memory emits `memory.forgotten` and the Ledger truncates only below snapshots.
4. **Windows file locking.** `fcntl` is POSIX-only. *Default:* `msvcrt.locking` shim; document that `local-multi` on Windows should use `sqlite`.
5. **Encryption at rest.** Not in scope for v2.0; *default:* rely on OS/volume encryption; note in `01` non-goals.
6. **Retention defaults are too narrow, and compaction has no clock (post-cutover review, 2026-09-06 — `07-post-cutover-review.md` §3.7).** `ledger/compaction.py`'s `DEFAULT_RETENTION` covers only `trace:`, `dead:`, `activity`; `metrics:history`, `curiosity:ticks`, `memory:episodic`, `cognition:calls`, `learn:*` grow without bound, and compaction runs only on `system.tick.sleep` — a Kernel that rarely sleeps never compacts even what has a policy. One live session grew `memory:episodic` to hundreds of KB and helped cause a `context_too_large` failure upstream. *Default:* add `metrics:history` and `curiosity:ticks` (short, e.g. 2 d) to `DEFAULT_RETENTION`; add a `max_events` cap alongside duration so one very active session can't outgrow its window; run compaction on a periodic timer as well as on sleep; cross-reference `[runtime] sleep_every_s` and `[ledger] retention` in the config tables so a generous duration isn't silently unenforced.
