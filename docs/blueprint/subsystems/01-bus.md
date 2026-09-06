# 01 — Bus (`simorgh/bus/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). This spec refines those; it may not
> contradict them.

**Layer:** 0 Substrate
**Owner (build):** unassigned
**Status:** draft
**Depends on (contracts only):** `contracts.envelope.Message`, `contracts.envelope.validate`, `contracts.topics` (catalog + pattern grammar), `contracts.protocols.Bus/Subscription/Ledger/Clock`
**v1 code that migrates here:** none directly (v1 had no system bus; `src/memory/shared_bus.py` is a persona-state pub/sub that migrates to `persona`). The trace-writer replaces the durability role of `src/orchestrator/activity_log.py`'s tool-call records.

## 1. Purpose and responsibilities

The Bus is the nervous system: the only way any two subsystems ever
communicate. It moves typed, validated `Message`s between publishers and
subscribers with three interaction patterns (event, command,
request/reply), guarantees ordering per `partition_key`, delivers
commands at-least-once with acknowledgement and dead-lettering, preempts
by priority, enforces the Kernel's reserved-topic policy, applies
backpressure, and appends every message to the Ledger's `trace:*`
streams so the causal history of any decision is reconstructible. It
does all of this identically over three backends — in-process asyncio,
a single SQLite file shared by processes on one host, and AWS SNS/SQS —
so deployment topology is configuration, never code.

**Responsibilities (owns):**
- The `Bus` protocol implementation and the three backends.
- Topic pattern matching (`*` one segment, `#` rest) and routing.
- Consumer groups (competing consumers) versus broadcast subscriptions.
- Per-`partition_key` ordering within a group; priority dequeue; TTL.
- Ack/nack/redelivery, `max_deliveries`, dead-letter queues.
- Request/reply plumbing (reply inboxes, correlation, timeouts).
- Envelope validation on publish; version translation hook (`contracts.compat`).
- The trace writer (every message → `trace:<trace_id>` in the Ledger, with sampling).
- Backpressure (bounded per-group depth) and delivery metrics.
- The `BusPolicy` hook the Kernel uses for reserved-topic enforcement.

**Explicit non-responsibilities (belongs elsewhere):**
- Deciding *who* may subscribe to what — the policy is installed by the Kernel (`03-kernel.md`); the Bus only enforces it.
- Approval tokens, HMAC secrets — Guardian/Execution/Kernel.
- Durable business state — the Ledger. The Bus persists only in-flight messages (sqlite/aws) for delivery guarantees.
- Retry *policy* for business operations (how many times to redraft a patch) — the owning subsystem; the Bus only redelivers a nacked command.
- Serialization of large payloads — producers store blobs in the Ledger and pass `*_ref` (Ledger spec §4).

**Principles this subsystem is the primary enforcer of:** 4.2 (messages, not calls), 4.4 (append-only trace), 4.14 (stdlib core, optional adapters), and the transport half of 4.3 (reserved-topic topology).

## 2. Position in the architecture

Layer 0. Every flow in `02` §5 rides on it; it is the first thing the
Kernel constructs and the last thing it stops. It participates in Flow
5 (pause/stop) by honoring priority 9 so `system.pause` overtakes a
backlog, and in Flow 7 (crash/resume) because the `sqlite`/`aws`
backends persist undelivered commands and in-flight leases across
process death.

Imports permitted: `simorgh.contracts.*`, stdlib (`asyncio`, `heapq`,
`sqlite3`, `json`, `time`, `uuid`, `fnmatch`-free custom matcher). The
`aws` backend lazily imports `boto3` inside `aws.py`; if the import
fails the backend registers as unavailable. The Bus imports the Ledger
*client type* only, for the trace writer. Nothing else under `simorgh.`.

## 3. Interfaces

### 3.1 Messages consumed
The Bus does not consume application messages. It reacts to two things
from the Kernel through direct API calls (not messages): `install_policy(policy)`
and `set_state(paused|running|stopping)` (used to pause command dequeue
for non-`system.*` types while paused — see §8).

| Type | Pattern | Semantics | What this subsystem does with it |
|---|---|---|---|
| (all) | `#` | — | Validates, routes, traces, and delivers every message; no application handling |

### 3.2 Messages produced
| Type | Semantics | Payload summary | Consumers (informational) |
|---|---|---|---|
| `system.health` | event | `{subsystem:"bus", status, detail}` — DLQ growth, backend errors, policy violations | kernel, interface, reflection |
| `system.metrics` | event | `{subsystem:"bus", counters:{published, delivered, acked, nacked, dead, expired, policy_denied}, gauges:{queue_depth.<group>, inflight.<group>, request_latency_ms_p50}}` | kernel, interface |

The Bus publishes these through itself, from source `bus`.

### 3.3 Request/reply APIs served
None at the message level. The Bus *implements* request/reply for others:
`request()` publishes the request with `reply_to` set to a per-client
inbox topic `_inbox.<source>.<client_uuid>` and `correlation_id` unset;
the responder calls `reply(request, type=..., payload=...)`, which
publishes to `request.reply_to` with `correlation_id = request.id`. The
requester resolves the awaiting future. Timeouts raise `BusTimeout`
(and the requester's client synthesizes an error reply per `03` §9).

### 3.4 Python protocol (`api.py`)

```python
# simorgh/bus/api.py
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Bus, Subscription   # re-exported for convenience

Handler = Callable[[Message], Awaitable[None]]

@dataclass(frozen=True)
class SubscriptionSpec:
    pattern: str                 # "task.*", "action.#", "#"
    group: str | None            # None = broadcast copy per subscription; str = competing consumers
    durable: bool                # persisted in sqlite/aws; ignored by memory
    source: str                  # subscribing subsystem name (for policy + metrics)
    max_inflight: int = 16       # per-subscription concurrency cap (partitions still serialized)

@dataclass
class Delivery:
    message: Message
    attempt: int                 # 1-based
    lease_until: float           # backend-specific visibility deadline
    group: str | None

class BusPolicy(Protocol):
    def check_subscribe(self, source: str, pattern: str) -> None: ...   # raise PolicyViolation
    def check_publish(self, source: str, type: str) -> None: ...

class BusBackend(Protocol):
    """What memory/sqlite/aws implement. The public Bus (client.py) wraps a backend
    with validation, policy, tracing, metrics, and request/reply."""
    async def start(self) -> None
    async def stop(self) -> None
    async def enqueue(self, message: Message) -> None
    async def register(self, spec: SubscriptionSpec, handler: Handler) -> Subscription
    async def ack(self, delivery: Delivery) -> None
    async def nack(self, delivery: Delivery, *, retry_after: float | None) -> None
    async def depth(self, group: str) -> int

class PolicyViolation(Exception): ...
class BusTimeout(TimeoutError): ...
class BusClosed(RuntimeError): ...
```

The public class is `simorgh.bus.client.BusClient(backend, *, ledger,
clock, policy, config, source)` implementing `contracts.protocols.Bus`
exactly:

```python
class BusClient(Bus):
    async def publish(self, message: Message) -> None
    async def subscribe(self, pattern, handler, *, group=None, durable=False) -> Subscription
    async def request(self, message: Message, *, timeout: float) -> Message
    async def reply(self, request: Message, *, type: str, payload: dict) -> None
    async def ack(self, message: Message) -> None
    async def nack(self, message: Message, *, retry_after: float | None = None) -> None
    # helpers (not in the protocol; sugar over publish):
    def new(self, type: str, payload: dict, *, caused_by: Message | None = None,
            partition_key: str | None = None, priority: int = 5, ttl_seconds: float | None = None,
            idempotency_key: str | None = None) -> Message      # fills source/trace/causation
```

Each subsystem receives its own `BusClient` from the Kernel with
`source` fixed to its name (so it cannot spoof another subsystem), all
clients sharing one backend instance (single process) or one SQLite
file/AWS deployment.

### 3.5 Configuration

```toml
[bus]
backend = "memory"                  # memory | sqlite | aws
max_queue_depth = 10000             # per consumer group; publish awaits above this (backpressure)
max_deliveries = 5                  # then → dead:<type>
default_lease_seconds = 30          # visibility timeout for commands (sqlite/aws)
request_default_timeout = 30.0
priority_preempt_threshold = 9      # messages at/above this bypass backpressure and jump queues
trace_enabled = true
trace_sample = { "system.tick.second" = 0.0, "system.metrics" = 0.0, "_inbox.#" = 0.0 }   # per-pattern sample rate, default 1.0
dedupe_window = 5000                # recently-seen message ids per group

[bus.sqlite]
path = "${data_dir}/bus.sqlite"     # one WAL DB shared by all processes on the host
poll_interval_ms = 50
[bus.aws]
region = "us-east-1"
topic_prefix = "simorgh-${deployment}"
queue_prefix = "simorgh-${deployment}"
```

Environment overrides: `SIMORGH_BUS_BACKEND`, `SIMORGH_BUS_SQLITE_PATH`.

## 4. Data model and Ledger streams

The Bus owns no business state. It writes:

- **`trace:<trace_id>`** (Ledger stream, appended by the trace writer):
  one event per message, `type` = message type, `payload` = the full
  envelope minus `payload` bodies over 4 KB (those are replaced by a
  blob ref). Sampled per `trace_sample`. This stream is what `simorgh
  trace <id>` renders.
- **`dead:<type>`** (Ledger stream): a copy of each message that
  exhausted `max_deliveries` or failed schema translation, with
  `{reason, attempts, last_error, group}`. The backend also keeps its own
  DLQ (a `deliveries` row state in sqlite, a real SQS DLQ in aws); the
  Ledger copy is the durable, inspectable record.
- **Backend-private state** (not Ledger): `memory` — nothing durable;
  `sqlite` — tables below; `aws` — SNS/SQS resources.

SQLite schema (`bus.sqlite`, WAL mode):

```
messages(id TEXT PK, type, schema_version INT, ts REAL, source, trace_id, causation_id,
         correlation_id, partition_key, priority INT, expires_at REAL, reply_to,
         idempotency_key, payload TEXT, enqueued_seq INTEGER)
subscriptions(sub_id TEXT PK, source, pattern, grp, durable INT, created_at REAL, last_seen REAL)
deliveries(delivery_id TEXT PK, message_id, sub_id, grp, attempt INT, state TEXT  -- pending|leased|acked|dead
           , lease_until REAL, retry_after REAL, partition_key, priority INT, enqueued_seq INT)
partition_locks(grp, partition_key, delivery_id, lease_until, PRIMARY KEY(grp, partition_key))
```

Indexes on `deliveries(grp, state, priority DESC, enqueued_seq)` and
`deliveries(lease_until)`.

## 5. Internal design

```
simorgh/bus/
  client.py       BusClient: validate → policy.check_publish → trace → backend.enqueue; subscribe wrapper;
                  request/reply futures; dispatcher (handler invocation, auto-ack/nack, metrics)
  router.py       compile(pattern) → matcher; match(type) over registered subscriptions
  memory.py       InMemoryBackend
  sqlite.py       SqliteBackend (+ poller task)
  aws.py          AwsBackend (lazy boto3)
  tracewriter.py  TraceWriter(ledger, sample_rules)
  policy.py       AllowAllPolicy (default for tests), PolicyViolation
  metrics.py      Counters/Gauges snapshot → system.metrics every N seconds
  service.py      Service(Subsystem): name="bus"; emits health/metrics; owns the poller/dispatcher tasks
  config.py
```

### 5.1 Publish path

```
publish(m):
  validate(m)                      # contracts.envelope.validate: catalog, schema, priority, partition form
  policy.check_publish(m.source, m.type)
  if state == "stopping" and not m.type.startswith("system."): raise BusClosed
  if m.priority < preempt_threshold: await backpressure(m)   # waits while any target group depth ≥ max
  trace.write(m)                   # async, sampled, never raises (logs + metric on failure)
  backend.enqueue(m)
  metrics.published[m.type] += 1
```

### 5.2 Delivery semantics (all backends)

- **Broadcast (`group=None`)**: each matching subscription gets its own
  delivery; auto-ack after the handler returns; a handler exception is
  logged, counted, and the delivery is *dropped* (events are facts; the
  Ledger already has them).
- **Competing (`group="workers"`)**: exactly one member per group gets a
  delivery; the handler's return acks; an exception nacks with
  exponential `retry_after` (1s, 2s, 4s… capped 60s) up to
  `max_deliveries`, then dead-letters. A handler may call
  `bus.nack(message, retry_after=…)` explicitly for transient conditions
  (e.g. budget exhausted) — the dispatcher then does not auto-ack.
- **Partition ordering**: within a group, a `partition_key` is held by at
  most one in-flight delivery. The next message for that key is not
  dispatched until the current one is acked/nacked/lease-expired. Keys
  are independent, so throughput scales across tasks while each task's
  messages stay sequential. Messages without a key are unordered.
- **Priority**: dequeue order is `(-priority, enqueued_seq)`. Priority
  ≥ `priority_preempt_threshold` (default 9 = `system.pause/stop/resume`)
  skips backpressure and is dispatched ahead of any waiting partition
  lock (system messages carry no partition key).
- **TTL**: `expires_at = ts + ttl_seconds`; an expired message is
  discarded at dequeue with `metrics.expired[type] += 1` and a
  `trace:*` note. Not dead-lettered (expiry is expected: e.g. a stale
  `task.available` is re-emitted by Planning).
- **Dedupe**: per group, an LRU of the last `dedupe_window` message ids;
  a redelivered-but-already-acked id is acked silently. Handlers remain
  idempotent by contract; this is only noise reduction.

State machine of a competing delivery:

```
   enqueue ──▶ pending ──dequeue──▶ leased ──ack──▶ acked
                 ▲                    │
                 │ retry_after ──nack─┘      lease expiry ──▶ pending (attempt+1)
                 │                    │
                 └─────────────── attempt > max_deliveries ──▶ dead ──▶ ledger dead:<type> + system.health
```

### 5.3 `memory` backend
One `asyncio.PriorityQueue`-like heap per consumer group plus one per
broadcast subscription; entries `(-priority, seq, message)`. A dispatcher
task per subscription pulls, checks partition lock (a `dict[str, bool]`
per group), and runs the handler in `asyncio.create_task` bounded by
`max_inflight` via a semaphore. Request/reply is a `dict[str,
asyncio.Future]` keyed by request id; `reply()` resolves the future
directly without a queue hop. Latency budget: < 1 ms per hop, < 5 ms per
request round-trip (measured in `tests/simorgh/bus/test_latency.py`).
Not durable; `durable=True` is accepted and ignored with a debug log.

### 5.4 `sqlite` backend
One WAL-mode database shared by all processes on the host. `enqueue`
inserts into `messages` and fans out one `deliveries` row per matching
durable subscription (broadcast) or one per group (competing).
Subscriptions are registered rows so a process that starts later still
receives messages enqueued while it was down (durable=True); non-durable
subscriptions only see messages enqueued after registration. A poller
task per process runs every `poll_interval_ms`: within a single
`BEGIN IMMEDIATE` transaction it selects the highest-priority
`pending` deliveries for its subscriptions whose partition is unlocked,
marks them `leased` with `lease_until = now + lease`, and inserts
`partition_locks`. Ack deletes the lock and marks `acked`; nack sets
`retry_after` and releases the lock; a reaper query every second
returns expired leases to `pending` (attempt+1). Request/reply uses the
same tables with the reply routed to the requester's `_inbox.*`
subscription. All writes are `fsync`'d by SQLite's WAL checkpoint; the
`busy_timeout` is 5 s.

### 5.5 `aws` backend
One SNS topic per domain (`simorgh-<dep>-task`, …); each consumer group
gets an SQS queue subscribed to the domains it declares patterns for,
with a filter policy on message attribute `type`. Competing groups use
a FIFO queue with `MessageGroupId = partition_key` (ordering) and
`MessageDeduplicationId = message.id`; broadcast subscriptions each get
their own standard queue. Priority is approximated by two queues per
group (`-hi` for ≥ threshold, polled first). DLQ via SQS redrive policy
(`maxReceiveCount = max_deliveries`) plus the Ledger `dead:*` copy
written by the consumer on final failure. Request/reply uses a
per-process temporary standard queue as the inbox. `boto3` is imported
lazily; absent → `BackendUnavailable` at config time with a clear
message.

### 5.6 Trace writer
`TraceWriter.write(m)`: if `random() < sample(m.type)`, appends an
`Event(stream=f"trace:{m.trace_id}", type=m.type, payload=envelope)` via
the Ledger client in a fire-and-forget task with a bounded internal
queue (drops with a metric under overload rather than slowing
publishers). Payload bodies over 4 KB are blob-referenced.

### 5.7 Lifecycle
`Service.start(ctx)` starts the backend, the dispatcher/poller tasks,
the metrics ticker; `stop()` sets state `stopping` (rejecting non-system
publishes), waits up to `drain_seconds` (default 10) for in-flight
handlers, cancels the rest, closes the backend. `health()` reports
`degraded` if DLQ grew in the last window or the backend reported
errors, `down` if the backend is unreachable.

## 6. Key behaviors — worked scenarios

**S1 — Competing consumers with ordering (Flow 2).** Planning publishes
`task.available{task_id=T1}` (group `workers`, key `task:T1`, priority 5)
and `task.available{T2}`. Two Workers (`orchestration@w1`, `@w2`) are
subscribed in group `workers`. The dispatcher hands T1 to w1 and T2 to
w2. w1 publishes `task.claim` (request) → Planning replies → w1 proceeds
and publishes `action.proposed{key task:T1}`. Meanwhile Planning
publishes `task.step` for T1 (same key) — it queues behind the in-flight
`action.proposed` for group `guardian`? No: different groups have
independent partition locks; ordering is per (group, key). Guardian's
group sees T1's messages in order; Worker w1's group sees its own in
order. w1 acks; the lock releases; the next T1 message dispatches.

**S2 — Request/reply with timeout (Flow 1).** Orchestration calls
`request(cognition.think, timeout=60)`. The client sets `reply_to =
_inbox.orchestration.<uuid>`, registers a future, publishes. Cognition's
handler calls `reply(req, type="cognition.think.reply", payload=…)`. The
reply is routed to the inbox; the future resolves; the trace stream shows
`think` and `think.reply` linked by `correlation_id`. If 60 s pass, the
client raises `BusTimeout`; the requester synthesizes `{ok:false,
error:{code:"timeout", retryable:true}}` (per `03` §9); a late reply is
dropped and counted (`metrics.late_replies`).

**S3 — Failure: handler crash, redelivery, dead-letter.** Execution's
handler for `action.approved` raises on a malformed tool arg the schema
did not catch. Dispatcher logs, nacks with `retry_after=1`; the
partition unlocks; after 1 s the delivery is re-leased (attempt 2); it
raises again… at attempt 6 (> `max_deliveries=5`) the delivery is
marked `dead`, the message is appended to Ledger `dead:action.approved`
with `{last_error, attempts:5}`, and the Bus emits `system.health{status:
degraded, detail:"dead-letter action.approved"}`. Guardian's approval
token has meanwhile expired (`expires_at` default 120 s), so even a
manual re-drive cannot execute it without re-approval — the token, not
the queue, is the safety boundary.

**S4 — Pause preemption (Flow 5).** With 3,000 `task.step` events
queued, Interface publishes `system.pause` (priority 9). It skips
backpressure and is dequeued next for every subscriber; Guardian denies
subsequent proposals; the Bus's `set_state("paused")` stops dequeuing
non-`system.*` *commands* (events still flow so projections stay
current).

**S5 — Policy violation.** A buggy `curiosity` package calls
`subscribe("action.proposed", …)`. The installed `KernelPolicy.check_subscribe`
raises `PolicyViolation`; the subscription is not created; the Bus
emits `system.health{status: degraded, detail: "policy: curiosity may not
subscribe action.proposed"}`; the Kernel marks the subsystem `degraded`.

## 7. Design considerations and tradeoffs

- **Three patterns on one abstraction** (event/command/request-reply via
  groups + reply inboxes) rather than three transports: fewer concepts
  for builders, one trace format, one policy hook. Cost: request/reply
  over `sqlite`/`aws` is slower than in-process; mitigated by keeping the
  hot chat path (`cognition.think`, `memory.retrieve`) in one process in
  `single` mode. (harness-01: "minimal scaffolding, maximal operational
  harness" — the harness pays for isolation, the model does not.)
- **At-least-once, not exactly-once.** Exactly-once across process
  crashes is not achievable without distributed transactions; idempotent
  handlers plus idempotency keys give the same observable result at far
  lower complexity. (harness-05 §7: append-only + reconstructible state
  makes duplicates harmless.)
- **Ordering per key, not global.** Global ordering would serialize the
  whole system; per-task ordering is what the flows actually need
  (AGI-04 "loop with many feedback paths" — feedback must be ordered
  *within* a loop, not across independent loops).
- **Priority preemption only for `system.*`.** A general priority scheme
  invites starvation games between subsystems; reserving preemption for
  corrigibility (`system.pause/stop`) keeps the guarantee simple and
  auditable (SOUL Directive 4; harness-01 "deny-first with human
  escalation").
- **Trace everything, sample the noise.** Full tracing is what makes
  `simorgh trace` and drift analysis possible (harness-03 "treat the plan
  changed as a loggable event"); per-second ticks and metrics are
  sampled to zero to keep the Ledger readable. Alternative (trace only
  errors) rejected: you cannot reconstruct a wrong decision from its
  errors alone.
- **SQLite over a local broker.** A local Redis/NATS would be faster and
  richer, but violates 4.14 (stdlib core, host anywhere). SQLite WAL with
  a 50 ms poller gives ~20 msg/s/process latency-bound throughput,
  ample for a system whose bottleneck is LLM calls.
- **Backpressure by awaiting publishers** rather than dropping: dropping
  an `action.result` would strand a task; slowing Curiosity's candidate
  generation when workers are saturated is the desired behavior (also
  how LLM budget pressure propagates, `03` §5).

## 8. Safety, degradation, and failure modes

| Condition | Behavior |
|---|---|
| Backend unreachable (sqlite locked > `busy_timeout`, AWS API error) | `publish` raises `BusUnavailable` after 3 retries; `health()`→`down`; Kernel supervision restarts the Bus service; subsystems treat as transient (nack) |
| Ledger unavailable (trace writer) | Tracing degrades to a bounded in-memory buffer (last 10k) and a `degraded` health event; delivery is unaffected — the Bus never blocks on the Ledger |
| Malformed message | Rejected at `publish` in the producer's process (`ValidationError`); never enters the queue |
| Unknown schema version | Routed through `contracts.compat`; if no translator, to `dead:<type>` with `reason=untranslatable` |
| Duplicate delivery after crash | Dedupe LRU suppresses recently-acked ids; otherwise the handler's idempotency contract applies |
| Handler never returns | `max_inflight` bounds concurrency; lease expiry (sqlite/aws) re-queues; `memory` backend has a per-handler timeout (`handler_timeout`, default 300 s) that cancels and nacks |
| Process restart mid-lease | sqlite/aws: lease expires → redelivered to another member; memory: lost (single process — by design) |
| `system.pause` | Command dequeue for non-`system.*` types halts; events continue; in-flight handlers finish |
| `system.stop` | Non-system publishes rejected (`BusClosed`); drain up to `drain_seconds`; leases released; backend closed. A stop never waits on a handler that is itself awaiting a model call — it is cancelled and its message re-queued (sqlite/aws) |

Guaranteed floor: the `memory` backend with `AllowAllPolicy` always
works with zero configuration and zero dependencies; every test and the
`--self-check` run on it.

## 9. Testing strategy

- **Contract tests**: `publish` rejects every invalid envelope case in `03` §2; `system.health`/`system.metrics` payloads validate.
- **Unit tests** (`tests/simorgh/bus/`): router pattern grammar (`task.*` vs `task.claim.reply`, `#`), priority ordering, TTL expiry, dedupe LRU, request/reply resolution and timeout, late-reply drop, backpressure awaits and releases, policy hook denial, trace sampling rules, drain behavior on stop.
- **Property tests** (`test_properties.py`, `random` + seeds, both `memory` and `sqlite`): (1) for any interleaving, messages sharing a partition key are delivered to a group in enqueue order; (2) every enqueued command is acked at least once or dead-lettered (at-least-once); (3) no message is delivered to two members of the same group concurrently; (4) a priority-9 message enqueued after N lower-priority messages is delivered before any of them that has not yet been leased; (5) crash simulation (drop leases) never loses a command.
- **Backend parity**: one parametrized suite runs the same scenarios against `memory` and `sqlite`; `aws` runs the same suite only when `SIMORGH_TEST_AWS=1` and `boto3` is importable (otherwise skipped, never failed).
- **Integration**: `tests/simorgh/integration/test_bus_two_toy_subsystems.py` (Phase 0 acceptance) — two toy `Service`s exchange an event, a command through a group of two, and a request/reply, on each backend; `test_flow_5_pause_preempts_backlog.py`.
- **Mocks**: `FakeClock` drives TTL/lease expiry; `FakeLedger` records trace appends.

## 10. Build steps (an agent picks this up here)

1. Package skeleton per `05` §2; `config.py`; `api.py` with the classes in §3.4; `router.py` + tests for the pattern grammar. *Accept:* boundary test passes; router tests green.
2. `client.py` with validation, `AllowAllPolicy`, request/reply futures, dispatcher with auto-ack/nack, metrics counters — against an in-memory stub backend. *Accept:* unit tests for publish/subscribe/request/timeout.
3. `memory.py` full backend (priority heap, groups, partition locks, TTL, dedupe, backpressure). *Accept:* property tests (1)–(4) on `memory`.
4. `tracewriter.py` + `service.py` (health/metrics). *Accept:* trace events appear in `FakeLedger` with sampling honored; metrics event emitted.
5. `sqlite.py` (schema, enqueue fan-out, poller, leases, reaper, durable subscriptions). *Accept:* property tests (1)–(5) on `sqlite`; two-process test (`multiprocessing`) shares one DB.
6. Policy hook + Kernel-style reserved-topic test (using a stub policy). *Accept:* S5 scenario.
7. Integration scenarios (Phase 0 acceptance) on both backends. *Accept:* green; latency test under budget.
8. `aws.py` (Phase 5): lazy boto3, topic/queue provisioning, FIFO groups, DLQ redrive. *Accept:* parity suite under `SIMORGH_TEST_AWS=1`; skipped cleanly otherwise.
9. README build log, config table, EVOLUTION milestone.

Size: **L**. Parallelizable: steps 3 and 5 (backends) after step 2; step 8 independent.

## 11. Migration notes

v1 has no equivalent; nothing is ported. Two v1 behaviors are
*replaced*: `ActivityLog.record_tool_call` (durable per-tool records)
becomes the `trace:*` stream written by the Bus for every
`action.*`/`tool.invoked` message; `SharedMemoryBus` mood pub/sub is
re-expressed as `persona.state.changed` events (see `14-persona.md`).
v1's `LiveTicker`/reminder "print between prompts" pattern is replaced
by `ui.notice` events consumed by Interface.

## 12. Open questions

1. **Should `action.approved` be publish-restricted to `guardian` as well as subscribe-restricted to `execution`?** `03` §3 only restricts subscription; the HMAC token already makes a forged approval inert. *Default:* add the publish restriction too (defense in depth) — proposed as a contracts/policy note to the parent.
2. **Per-handler timeout on `memory` backend** — 300 s default may be too short for a self-patch drafting loop that awaits several model calls. *Default:* subsystems may pass `max_handler_seconds` in `SubscriptionSpec`; Execution sets it per tool.
3. **Broadcast durability semantics in sqlite** — should a durable broadcast subscription that has been offline for days receive thousands of old events? *Default:* yes but capped by `ttl_seconds` set by producers on high-volume event types (`task.step` gets 1 h TTL).
4. **Priority inversion on partition locks** — a priority-9 message never carries a partition key today; if one ever does, it could wait behind a held lock. *Default:* validation forbids `partition_key` on priority ≥ threshold.
