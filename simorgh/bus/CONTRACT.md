# bus -- contract

One-line status: layer 0 · 2,172 lines · 13 test files · lock: `bus` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/bus/__init__.py` | TODO |
| `simorgh/bus/api.py` | TODO |
| `simorgh/bus/backends/__init__.py` | TODO |
| `simorgh/bus/backends/aws.py` | TODO |
| `simorgh/bus/backends/memory.py` | TODO |
| `simorgh/bus/backends/sqlite.py` | TODO |
| `simorgh/bus/client.py` | TODO |
| `simorgh/bus/config.py` | TODO |
| `simorgh/bus/enforcement.py` | TODO |
| `simorgh/bus/factory.py` | TODO |
| `simorgh/bus/metrics.py` | TODO |
| `simorgh/bus/policy.py` | TODO |
| `simorgh/bus/router.py` | TODO |
| `simorgh/bus/service.py` | TODO |
| `simorgh/bus/trace.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `system.health` | `messages/system.py::SystemHealth` | simorgh/bus/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/bus/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `system.health` | `messages/system.py::SystemHealth` | simorgh/bus/client.py, simorgh/bus/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/bus/client.py, simorgh/bus/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `dead:{m.id}:{delivery.attempt}` | simorgh/bus/client.py | simorgh/execution/media/cast.py, simorgh/kernel/configcheck.py, simorgh/ledger/compaction.py, simorgh/ledger/streams.py | see ledger/compaction.py DEFAULT_RETENTION |
| `dead:{m.type}` | simorgh/bus/client.py | simorgh/execution/media/cast.py, simorgh/kernel/configcheck.py, simorgh/ledger/compaction.py, simorgh/ledger/streams.py | see ledger/compaction.py DEFAULT_RETENTION |
| `group:` | simorgh/bus/backends/sqlite.py | simorgh/contracts/protocols.py, simorgh/interface/render.py, simorgh/reflection/digest.py | see ledger/compaction.py DEFAULT_RETENTION |
| `group:{grp}:{pattern}` | simorgh/bus/backends/sqlite.py | simorgh/contracts/protocols.py, simorgh/interface/render.py, simorgh/reflection/digest.py | see ledger/compaction.py DEFAULT_RETENTION |
| `group:{reg.spec.group}:{reg.spec.pattern}` | simorgh/bus/backends/sqlite.py | simorgh/contracts/protocols.py, simorgh/interface/render.py, simorgh/reflection/digest.py | see ledger/compaction.py DEFAULT_RETENTION |
| `group:{spec.group}:{spec.pattern}` | simorgh/bus/backends/sqlite.py | simorgh/contracts/protocols.py, simorgh/interface/render.py, simorgh/reflection/digest.py | see ledger/compaction.py DEFAULT_RETENTION |
| `trace:{message.trace_id}` | simorgh/bus/trace.py | simorgh/cognition/parser.py, simorgh/kernel/cli.py, simorgh/kernel/context.py, simorgh/kernel/metrics.py, simorgh/ledger/backends/jsonl.py, simorgh/ledger/compaction.py, simorgh/ledger/service.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[bus]` in simorgh.toml; dataclass in `simorgh/bus/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `backend` | `'memory'` | yes |
| `max_queue_depth` | `10000` | yes |
| `max_deliveries` | `5` | yes |
| `default_lease_seconds` | `30.0` | yes |
| `request_default_timeout` | `30.0` | yes |
| `priority_preempt_threshold` | `9` | yes |
| `handler_timeout_seconds` | `300.0` | yes |
| `drain_seconds` | `10.0` | NO (declared, never read) |
| `trace_enabled` | `True` | yes |
| `trace_sample` | `field(default_factory=lambda: {'system.tick.second': 0.0, 's` | yes |
| `trace_blob_threshold_bytes` | `4096` | yes |
| `dedupe_window` | `5000` | yes |
| `metrics_interval_seconds` | `15.0` | NO (declared, never read) |
| `sqlite` | `field(default_factory=SqliteConfig)` | yes |
| `aws` | `field(default_factory=AwsConfig)` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract bus`.

- `tests/simorgh/bus/test_a_long_handler_is_not_cut_off.py` -- TODO: what it pins
- `tests/simorgh/bus/test_aws_fake.py` -- TODO: what it pins
- `tests/simorgh/bus/test_backends_parity.py` -- TODO: what it pins
- `tests/simorgh/bus/test_client.py` -- TODO: what it pins
- `tests/simorgh/bus/test_contracts.py` -- TODO: what it pins
- `tests/simorgh/bus/test_dead_letters_reach_bus_health.py` -- TODO: what it pins
- `tests/simorgh/bus/test_enforcement.py` -- TODO: what it pins
- `tests/simorgh/bus/test_latency.py` -- TODO: what it pins
- `tests/simorgh/bus/test_one_counter_set_per_process.py` -- TODO: what it pins
- `tests/simorgh/bus/test_router.py` -- TODO: what it pins
- `tests/simorgh/bus/test_service_and_factory.py` -- TODO: what it pins
- `tests/simorgh/bus/test_sqlite_multiprocess.py` -- TODO: what it pins
- `tests/simorgh/bus/test_trace.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim bus --by <you> --task "..."`), commit the lock, edit only `simorgh/bus/`, `tests/simorgh/bus/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py bus` before committing; commit subject `bus: <what changed>`.
