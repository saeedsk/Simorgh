# `simorgh/bus/` — the nervous system

Spec: [`docs/blueprint/subsystems/01-bus.md`](../../docs/blueprint/subsystems/01-bus.md).
Contracts it speaks: `docs/blueprint/03-contracts-and-messaging.md` §2–§7, §10.

The only way any two subsystems communicate: typed, validated `Message`s
with three interaction patterns (event, command, request/reply), ordering
per `partition_key`, at-least-once commands with ack/nack/dead-letter,
priority-9 preemption for `system.pause/stop/resume`, reserved-topic
enforcement, backpressure, and a trace of every message into the Ledger.

```
client.py       BusClient (the public Bus; the ONLY module other packages import)
api.py          SubscriptionSpec, Delivery, BusBackend, BusPolicy, exceptions
router.py       pattern routing; replies are point-to-point to the requester's inbox
backends/       memory (asyncio, the floor) · sqlite (WAL, multi-process) · aws (SNS+SQS, optional)
trace.py        TraceWriter -> Ledger `trace:<trace_id>`, per-type sampling, blob refs, never blocks
enforcement.py  ReservedTopologyPolicy + IdentityRegistry (subsystem tokens in multi-process modes)
policy.py       AllowAllPolicy (zero-config default)
metrics.py      counters/gauges -> system.metrics
service.py      Service(Subsystem): health + metrics ticker
factory.py      make_backend / make_client / make_bus from Config
config.py       [bus] table -> Config (+ SIMORGH_BUS_BACKEND / SIMORGH_BUS_SQLITE_PATH)
```

## Run the tests

```
python3 -m unittest discover -s tests/simorgh/bus -t .      # this package
python3 -m unittest discover -s tests -t .                   # everything (v1 + v2)
SIMORGH_TEST_AWS=1 python3 -m unittest tests.simorgh.bus.test_aws_fake   # the aws backend against a fake boto3 (always runs; the flag only gates a real-network suite that does not exist yet)
```

## Notes for the next builder

- **DB calls in `sqlite.py` are synchronous on the event loop** — every
  statement is sub-millisecond on these tables; if a real deployment shows
  poller stalls, the fix is `asyncio.to_thread` around `_lease_ready`, not
  a rewrite.
- **Explicit `bus.nack(message)` inside a handler**: the backends record
  the explicit outcome by delivery id and honor it when the handler
  returns; the memory backend also honors `retry_after`.
- **Replies never fan out.** A message with `reply_to` + `correlation_id`
  is routed only to the subscription whose pattern is exactly `reply_to`.
- The `aws` backend is exercised only against `tests/simorgh/bus/fake_boto3.py`;
  nothing here touches the network.

## Build log

- 2026-09-06 — Built to spec §10 steps 1–9 (aws included, fake-tested). See
  `docs/EVOLUTION.md` milestone 99.

## Definition of done

- [x] Spec status `built`; README links spec
- [x] `consumes`/`produces` declared (health, metrics)
- [x] Boundary test passes
- [x] Contract tests for every produced type
- [x] Unit + property tests on `memory` and `sqlite`; aws via fake
- [x] Integration scenarios (two toy subsystems; Flow 5 pause preemption)
- [x] v1 tests still green
- [x] No third-party dependency in the core
- [x] `EVOLUTION.md` milestone written
