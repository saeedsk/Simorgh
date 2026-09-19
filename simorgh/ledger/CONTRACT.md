# ledger -- contract

One-line status: layer 0 · 2,798 lines · 14 test files · lock: `ledger` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/ledger/__init__.py` | TODO |
| `simorgh/ledger/api.py` | TODO |
| `simorgh/ledger/backends/__init__.py` | TODO |
| `simorgh/ledger/backends/dynamodb.py` | TODO |
| `simorgh/ledger/backends/jsonl.py` | TODO |
| `simorgh/ledger/backends/memory.py` | TODO |
| `simorgh/ledger/backends/sqlite.py` | TODO |
| `simorgh/ledger/blobs.py` | TODO |
| `simorgh/ledger/client.py` | TODO |
| `simorgh/ledger/compaction.py` | TODO |
| `simorgh/ledger/config.py` | TODO |
| `simorgh/ledger/factory.py` | TODO |
| `simorgh/ledger/idempotency.py` | TODO |
| `simorgh/ledger/migrate_v1.py` | TODO |
| `simorgh/ledger/projection.py` | TODO |
| `simorgh/ledger/service.py` | TODO |
| `simorgh/ledger/streams.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `system.health` | `messages/system.py::SystemHealth` | simorgh/ledger/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/ledger/service.py | TODO |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/ledger/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `system.health` | `messages/system.py::SystemHealth` | simorgh/ledger/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/ledger/service.py | TODO |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/ledger/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `action:` | simorgh/ledger/compaction.py, simorgh/ledger/streams.py | simorgh/cognition/compaction.py, simorgh/cognition/config.py, simorgh/execution/render.py, simorgh/execution/service.py, simorgh/execution/verifier.py, simorgh/guardian/service.py, simorgh/interface/benchmarkchart.py, simorgh/verification/config.py, simorgh/verification/service.py, simorgh/verification/verdict.py, simorgh/voice/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `blob:{digest}` | simorgh/ledger/backends/dynamodb.py, simorgh/ledger/backends/sqlite.py, simorgh/ledger/blobs.py | simorgh/execution/knowledge/index.py, simorgh/execution/service.py, simorgh/kernel/migrate_v1.py, simorgh/kernel/vault.py, simorgh/orchestration/worker.py | see ledger/compaction.py DEFAULT_RETENTION |
| `cognition:` | simorgh/ledger/streams.py | simorgh/cognition/budget.py, simorgh/cognition/compaction.py, simorgh/cognition/router.py, simorgh/cognition/service.py, simorgh/planning/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `cognition:budget` | simorgh/ledger/migrate_v1.py | simorgh/cognition/budget.py | see ledger/compaction.py DEFAULT_RETENTION |
| `cognition:budget:` | simorgh/ledger/compaction.py | simorgh/cognition/budget.py | see ledger/compaction.py DEFAULT_RETENTION |
| `cognition:summaries:` | simorgh/ledger/compaction.py | simorgh/cognition/compaction.py | see ledger/compaction.py DEFAULT_RETENTION |
| `curiosity:` | simorgh/ledger/streams.py | simorgh/curiosity/interests.py, simorgh/curiosity/sampler.py, simorgh/curiosity/service.py, simorgh/planning/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `curiosity:interests` | simorgh/ledger/migrate_v1.py | simorgh/curiosity/interests.py, simorgh/curiosity/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `curiosity:ticks` | simorgh/ledger/compaction.py | simorgh/curiosity/sampler.py, simorgh/curiosity/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `dead:` | simorgh/ledger/compaction.py, simorgh/ledger/streams.py | simorgh/bus/backends/aws.py, simorgh/bus/client.py, simorgh/bus/config.py, simorgh/bus/service.py, simorgh/execution/media/cast.py, simorgh/kernel/configcheck.py | see ledger/compaction.py DEFAULT_RETENTION |
| `execution:inflight` | simorgh/ledger/compaction.py | simorgh/execution/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `execution:tools` | simorgh/ledger/compaction.py | simorgh/execution/service.py, simorgh/interface/dispatch.py, simorgh/orchestration/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `guardian:` | simorgh/ledger/streams.py | simorgh/guardian/posture.py, simorgh/guardian/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `guardian:rejected` | simorgh/ledger/migrate_v1.py | simorgh/guardian/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `learn:` | simorgh/ledger/streams.py | simorgh/learning/competence.py, simorgh/learning/outcomes.py, simorgh/learning/service.py, simorgh/learning/strategy.py, simorgh/voice/vad.py | see ledger/compaction.py DEFAULT_RETENTION |
| `learn:patches` | simorgh/ledger/migrate_v1.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `learn:skills` | simorgh/ledger/migrate_v1.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `ledger:` | simorgh/ledger/compaction.py, simorgh/ledger/streams.py | simorgh/bus/client.py, simorgh/bus/factory.py, simorgh/bus/trace.py, simorgh/cognition/budget.py, simorgh/cognition/compaction.py, simorgh/contracts/protocols.py, simorgh/interface/dispatch.py, simorgh/kernel/api.py, simorgh/kernel/context.py, simorgh/kernel/metrics.py, simorgh/kernel/migrate_v1.py, simorgh/kernel/scheduler.py, simorgh/learning/outcomes.py, simorgh/memory/recall.py, simorgh/memory/store.py, simorgh/orchestration/context.py, simorgh/planning/store.py | see ledger/compaction.py DEFAULT_RETENTION |
| `ledger:compaction` | simorgh/ledger/streams.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `memory:` | simorgh/ledger/streams.py | simorgh/execution/knowledge/index.py, simorgh/execution/vision.py, simorgh/memory/consolidation.py, simorgh/memory/recall.py, simorgh/memory/store.py, simorgh/orchestration/context.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/worker.py | see ledger/compaction.py DEFAULT_RETENTION |
| `memory:episodic` | simorgh/ledger/migrate_v1.py | simorgh/memory/store.py, simorgh/orchestration/context.py | see ledger/compaction.py DEFAULT_RETENTION |
| `memory:semantic` | simorgh/ledger/migrate_v1.py | simorgh/memory/consolidation.py, simorgh/memory/store.py | see ledger/compaction.py DEFAULT_RETENTION |
| `metrics:history` | simorgh/ledger/compaction.py | simorgh/execution/tools.py, simorgh/interface/config.py, simorgh/interface/httpapi.py, simorgh/kernel/metrics.py | see ledger/compaction.py DEFAULT_RETENTION |
| `persona:` | simorgh/ledger/streams.py | simorgh/persona/mood.py, simorgh/persona/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `persona:state` | simorgh/ledger/compaction.py | simorgh/persona/mood.py, simorgh/persona/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `plan:` | simorgh/ledger/streams.py | simorgh/contracts/messages/plan.py, simorgh/planning/planmode.py, simorgh/planning/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `project:` | simorgh/ledger/streams.py | simorgh/curiosity/service.py, simorgh/execution/security/selfcheck.py, simorgh/interface/render.py, simorgh/planning/intake.py, simorgh/planning/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `reflect:` | simorgh/ledger/compaction.py, simorgh/ledger/streams.py | simorgh/reflection/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `self:` | simorgh/ledger/streams.py | simorgh/cognition/router.py, simorgh/contracts/messages/self_.py, simorgh/execution/home/ring.py, simorgh/execution/security/api.py, simorgh/execution/tools.py, simorgh/execution/vision.py, simorgh/interface/dispatch.py, simorgh/interface/httpapi.py, simorgh/orchestration/scaffolds.py, simorgh/planning/service.py, simorgh/reflection/service.py, simorgh/worldmodel/selfmodel.py | see ledger/compaction.py DEFAULT_RETENTION |
| `task:` | simorgh/ledger/streams.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/orchestration/context.py, simorgh/orchestration/profiles.py, simorgh/orchestration/progress.py, simorgh/orchestration/resume.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/service.py, simorgh/orchestration/session.py, simorgh/orchestration/tools.py, simorgh/orchestration/worker.py, simorgh/planning/api.py, simorgh/planning/dag.py, simorgh/planning/intake.py, simorgh/planning/scheduler.py, simorgh/planning/service.py, simorgh/planning/store.py, simorgh/reflection/service.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |
| `trace:` | simorgh/ledger/compaction.py, simorgh/ledger/streams.py | simorgh/bus/client.py, simorgh/bus/factory.py, simorgh/bus/service.py, simorgh/bus/trace.py, simorgh/cognition/parser.py, simorgh/kernel/cli.py, simorgh/kernel/context.py, simorgh/kernel/metrics.py, simorgh/orchestration/context.py | see ledger/compaction.py DEFAULT_RETENTION |
| `v1:<id>` | simorgh/ledger/migrate_v1.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `v1:{record_id}` | simorgh/ledger/migrate_v1.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `verify:` | simorgh/ledger/compaction.py, simorgh/ledger/streams.py | simorgh/orchestration/api.py, simorgh/orchestration/profiles.py, simorgh/orchestration/session.py, simorgh/verification/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `voice:turns` | simorgh/ledger/compaction.py | simorgh/voice/api.py, simorgh/voice/config.py, simorgh/voice/pipeline.py, simorgh/voice/session.py, simorgh/voice/tts/lanes.py | see ledger/compaction.py DEFAULT_RETENTION |
| `world:` | simorgh/ledger/streams.py | simorgh/reflection/service.py, simorgh/worldmodel/facets/capability_map.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[ledger]` in simorgh.toml; dataclass in `simorgh/ledger/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `backend` | `'jsonl'` | yes |
| `data_dir` | `'~/.simorgh/ledger'` | NO (declared, never read) |
| `fsync` | `True` | yes |
| `snapshot_every` | `200` | yes |
| `blob_inline_threshold` | `4096` | yes |
| `tail_poll_ms` | `100` | yes |
| `keep_tail` | `50` | yes |
| `retention` | `field(default_factory=dict)` | yes |
| `compact_after_start_s` | `30.0` | yes |
| `allow_fallback` | `False` | yes |
| `dynamodb_table` | `''` | yes |
| `dynamodb_bucket` | `''` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract ledger`.

- `tests/simorgh/ledger/test_a_corrupt_line_is_a_gap_not_an_ending.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_backends.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_blobs.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_compaction.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_config_and_factory.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_contracts.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_head_never_regresses.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_idempotency.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_jsonl_crash_safety.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_jsonl_start_is_incremental.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_migrate_v1.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_projection.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_service.py` -- TODO: what it pins
- `tests/simorgh/ledger/test_streams.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim ledger --by <you> --task "..."`), commit the lock, edit only `simorgh/ledger/`, `tests/simorgh/ledger/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py ledger` before committing; commit subject `ledger: <what changed>`.
