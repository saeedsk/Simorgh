# bus -- contract

One-line status: layer 0 · 2,172 lines · 13 test files · lock: `bus` in docs/modules/locks.toml

## Purpose

The bus carries every typed `Message` between subsystems: publish, subscribe with `*`/`#` patterns, request/reply over per-client inboxes, competing-consumer groups with ack/nack and dead-lettering, and a trace copy of each message into the Ledger. It owns delivery semantics and the enforcement point for the reserved-topology table in `contracts/topics.py`; it does not own the table, the envelope, or any topic's meaning. It must never let a handler's exception reach the publisher, never block a publisher on the Ledger (tracing is queued and drops with a counter), and never trust `message.source` for policy (the client's own `source`, fixed by the Kernel, is checked, `client.py:184`). The shaping decision: backends (`memory`, `sqlite`, `aws`) are interchangeable behind one `BusBackend` protocol (`api.py`), and `BusClient` wraps whichever one with validation, policy, backpressure, tracing and metrics. Live runs use `memory`; the other two serve deployment modes nothing selects today (B8).

## Files

| File | For |
|---|---|
| `simorgh/bus/__init__.py` | exports `Service` only |
| `simorgh/bus/api.py` | backend protocol, `SubscriptionSpec`, `Delivery`, exceptions, `UNBOUNDED` |
| `simorgh/bus/backends/__init__.py` | package marker |
| `simorgh/bus/backends/aws.py` | SNS/SQS backend, lazy boto3; unused in live runs |
| `simorgh/bus/backends/memory.py` | in-process asyncio backend: priority heaps per lane, the live default |
| `simorgh/bus/backends/sqlite.py` | durable multi-process backend with leases; unused in live runs |
| `simorgh/bus/client.py` | `BusClient`, the one public surface every subsystem holds |
| `simorgh/bus/config.py` | `[bus]` dataclasses and `SIMORGH_BUS_*` env overrides |
| `simorgh/bus/enforcement.py` | `ReservedTopologyPolicy` and `IdentityRegistry` |
| `simorgh/bus/factory.py` | `make_backend`/`make_client`/`make_bus`; default stderr handler-error hook |
| `simorgh/bus/metrics.py` | delivery counters and request latency p50 for `system.metrics` |
| `simorgh/bus/policy.py` | `AllowAllPolicy` (tests and the zero-config floor) |
| `simorgh/bus/router.py` | which subscriptions a message reaches; replies go only to their inbox |
| `simorgh/bus/service.py` | the bus's `Service`: periodic metrics and health |
| `simorgh/bus/trace.py` | `TraceWriter`: a span per traced message in the telemetry store (default), or `trace:<trace_id>` ledger streams with `trace_backend = "ledger"` |

## Consumes

`Service.consumes` is `()` (`service.py:19`). The bus subscribes to no topic; it delivers all of them.

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `system.health` | `messages/system.py::SystemHealth` | simorgh/bus/client.py | a delivery is dead-lettered (`status: degraded`, `client.py:331`) |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/bus/client.py, simorgh/bus/service.py | every `metrics_interval` (15 s, hard-coded default) from `Service._metrics_loop` via `BusClient.emit_metrics` |

Both are published with `source="bus"` through whichever client owns the call. `Service.health()` itself is polled by the Kernel, not published by the bus.

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `dead:<type>` | simorgh/bus/client.py:317 (appended on a dead letter; idempotency key `dead:<msg id>:<attempt>`) | simorgh/kernel/configcheck.py, simorgh/ledger/streams.py | 30d (`dead:` in DEFAULT_RETENTION) |
| `trace:<trace_id>` | simorgh/bus/trace.py:101 (one event per traced message; idempotency key = message id) | simorgh/kernel/cli.py (`trace` command), simorgh/kernel/context.py, simorgh/kernel/metrics.py, simorgh/orchestration/context.py, simorgh/cognition/parser.py | 2d (`trace:` in DEFAULT_RETENTION) |

The `group:<grp>:<pattern>` strings in `backends/sqlite.py` are sqlite subscription keys, not ledger streams. Payloads over `trace_blob_threshold_bytes` are stored with `ledger.put_blob` and the trace event carries `payload_ref`.

## Config

`[bus]` in simorgh.toml; dataclass in `simorgh/bus/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `backend` | `'memory'` | yes |
| `max_queue_depth` | `10000` | yes |
| `max_deliveries` | `5` | yes |
| `default_lease_seconds` | `30.0` | yes (sqlite backend only) |
| `request_default_timeout` | `30.0` | yes |
| `priority_preempt_threshold` | `9` | yes |
| `handler_timeout_seconds` | `300.0` | yes (memory backend only) |
| `drain_seconds` | `10.0` | NO (declared, never read; `BusClient.stop(drain_seconds=)` ignores its argument and no caller passes it; `kernel/configcheck.py:80-94` lists it) |
| `trace_enabled` | `True` | yes |
| `trace_backend` | `'telemetry'` | yes: `telemetry` (span name = type, span id = message id, parent = causation id, attrs `source` and any `payload_ref`; no body kept) or `ledger`; `telemetry` with no store falls back to the ledger |
| `trace_sample` | `field(default_factory=lambda: {'system.tick.second': 0.0, 's` | yes |
| `trace_blob_threshold_bytes` | `4096` | yes |
| `dedupe_window` | `5000` | yes |
| `metrics_interval_seconds` | `15.0` | NO (declared, never read; `kernel/registry.py:140` builds `BusService(bus_client)` without it) |
| `sqlite` | `field(default_factory=SqliteConfig)` | yes |
| `aws` | `field(default_factory=AwsConfig)` | yes |

Env overrides: `SIMORGH_BUS_BACKEND`, `SIMORGH_BUS_SQLITE_PATH` (`config.py:73-80`).

## Public Python surface

- `simorgh.bus.Service` (`service.py`): `name="bus"`, `consumes=()`, `produces=(system.health, system.metrics)`, `__init__(client, *, metrics_interval=15.0)`, `start/stop/health`. Health is `down` on metrics-publish errors, `degraded` when the dead counter rose since the last poll or the trace writer is buffering.
- `simorgh.bus.client.BusClient`: the only module other packages may import. Implements `contracts.protocols.Bus`: `new`, `publish`, `subscribe(pattern, handler, *, group, durable, max_inflight, max_handler_seconds)`, `ack`, `nack`, `request`, `request_or_error`, `reply`, `emit_metrics`, `set_state`, `start/stop`. Re-exports `BusClosed`, `BusTimeout`, `PolicyViolation`, `UNBOUNDED`.
- Kernel-only: `factory.make_backend/make_client/make_bus`, `enforcement.ReservedTopologyPolicy`, `enforcement.IdentityRegistry`, `config.Config`.
- Types other packages see through `simorgh.contracts`: `Message`/`Event` (`contracts/envelope.py`), `Bus` and `Subscription` protocols (`contracts/protocols.py`), the topic constants and policy tables (`contracts/topics.py`).
- Module-level singletons: none. Shared mutable state lives on objects the Kernel shares: one backend, one `Metrics` and one `TraceWriter` for all clients (`kernel/context.py:115`, `kernel/service.py:224`). Risk: `backend.set_dead_letter_hook` is overwritten by every new `BusClient` (`client.py:90`), so the last client built owns dead-letter handling; the shared `Metrics` is what lets `Service.health()` see it (`tests/simorgh/bus/test_one_counter_set_per_process.py`).

## Invariants

- `publish` validates the envelope (`contracts.envelope.validate`) before anything else; an invalid envelope raises and nothing is enqueued or traced.
- Policy is checked against the client's construction-time `source`, never `message.source`; a client cannot publish a restricted type under another subsystem's name.
- The bus enforces every entry of `contracts/topics.py` `SUBSCRIBE_ONLY_BY` (`action.proposed` guardian only; `action.approved` execution only), including through wildcards: a pattern that could match a restricted type is refused for any other source.
- The bus enforces `PUBLISH_ONLY_BY` and `PUBLISH_PAYLOAD_CONSTRAINTS` (`action.denied` from execution only with `layer: token`); a violation raises `PolicyViolation`.
- A reply (`reply_to` and `correlation_id` set) is delivered only to the inbox subscription whose pattern equals `reply_to`; inbox subscriptions never receive ordinary messages.
- A competing group gets one delivery per message; each broadcast subscription gets its own copy.
- A handler exception never propagates to the publisher. Group deliveries are nacked and retried with backoff up to `max_deliveries`, then appended to `dead:<type>` and announced on `system.health`; a failing broadcast delivery is dropped (`memory.py:276`) and printed to stderr by `factory.default_handler_error`.
- A message with `priority >= priority_preempt_threshold` bypasses backpressure; below it, `publish` waits while any target group's depth is at `max_queue_depth`.
- While stopping, only `system.*` publishes are accepted; pending requests fail with `BusClosed` rather than hang.
- `request` raises `BusTimeout` after its timeout and never leaks a pending future when `publish` rejects the request.
- Per-partition order holds within a lane: two messages with the same `partition_key` are never in flight together on one lane.
- A handler subscribed with `max_handler_seconds=UNBOUNDED` is never cut off by the bus.
- Tracing never blocks or fails delivery: a full queue drops with a counter; a ledger outage buffers and replays.
- A published message is sampled for tracing once, in `BusClient.publish` (`TraceWriter.should_trace`); `TraceWriter.write` does not sample again, so a rate `r` keeps about `r` of messages (`tests/simorgh/bus/test_trace.py::TestATracedMessageIsSampledOnce`).

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract bus`.

- `tests/simorgh/bus/test_contracts.py` -- every produced type validates against the catalogue; `produces` names real types; every invalid-envelope case is rejected on publish.
- `tests/simorgh/bus/test_enforcement.py` -- the reserved-topology table is enforced, wildcards included; no publishing under another subsystem's name.
- `tests/simorgh/bus/test_router.py` -- broadcast vs group fan-out, `*`/`#` matching, replies only to their inbox.
- `tests/simorgh/bus/test_client.py` -- publish validation, policy hook, request/reply and timeouts, explicit nack, backpressure, stopping.
- `tests/simorgh/bus/test_backends_parity.py` -- memory and sqlite give the same delivery semantics (ordering, at-least-once, dead letters with the ledger mirror, preemption, TTL, pause, dedupe).
- `tests/simorgh/bus/test_trace_goes_to_telemetry.py` -- a traced message is a span with id, parent and source; the ledger switch still writes streams.
- `tests/simorgh/bus/test_trace.py` -- sampling rules, `trace:<id>` stream with message-id idempotency, outage buffering, blob refs, drop-on-overflow.
- `tests/simorgh/bus/test_service_and_factory.py` -- config defaults and env overrides, backend selection, one shared backend, the Service's `produces` and health.
- `tests/simorgh/bus/test_a_long_handler_is_not_cut_off.py` -- `UNBOUNDED` handlers are not timed out; the default still guards hangs.

## Known issues (2026-09-18 evaluation)

- B2 (medium): one ledger stream plus idempotency sidecar per `trace_id` (`trace.py:101`); 76% of trace streams hold one event. Open; stage 1 item 3.
- P4 (low): tracing yields many one-event streams and no end-to-end trace per turn; the exclusion list in `config.py` misses chatty topics. Open; stage 1 items 2-3.
- B4 (low): broadcast subscriptions drop a raising handler's delivery and queues are unbounded; documented contract. Open (queue-depth metric and cap recommended).
- B5 (low): the memory backend's 5 ms wake-all ticker (`memory.py:132-135`) costs CPU when idle. Open.
- B6 (low): broadcast lanes run up to 16 handlers at once; order holds only where a `partition_key` is set. Open.
- B8 (low): the sqlite and aws backends and `IdentityRegistry` serve modes nothing selects. Open; stage 1 item 10 freezes aws.
- W4 (high, via B2): per-message traces are most of the ledger's file count. Open.
- L4 (medium): one tool call is ~13 bus messages; cost is trace fragmentation, not latency. Open.

None of these was fixed on 2026-09-18/19.

Found while writing this contract (not in the catalogue), fixed 2026-09-19: a traced message was sampled twice, once in `BusClient.publish` and again inside `TraceWriter.write`, so a fractional rate `r` kept `r²` of messages. `write` no longer samples.

## Planned changes (roadmap)

- Stage 1 item 3 done 2026-09-19: `TraceWriter` writes a span per message to the telemetry store; `trace:<id>` streams are written only with `[bus] trace_backend = "ledger"` (the rollback switch, one bless cycle). The Kernel's client now reads `[bus]` (it used `Config()` defaults, so `trace_sample` in simorgh.toml had no effect). Open: per-prefix fractional rates.
- Stage 1 item 5: `Message` gains an optional `deadline`; `BusClient.request` sets it from its timeout.
- Stage 1 item 10: `backends/aws.py` (and the identity registry) move under `simorgh/_frozen/`; the protocol and the sqlite backend stay.
- Stage 3 item 2: `session.delta` is bus-only with trace sampling 0.

## Working on this module

Lock it first (`python tools/modlock.py claim bus --by <you> --task "..."`), commit the lock, edit only `simorgh/bus/`, `tests/simorgh/bus/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py bus` before committing; commit subject `bus: <what changed>`.
