# memory -- contract

One-line status: layer 2 · 1,901 lines · 12 test files · lock: `memory` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/memory/__init__.py` | TODO |
| `simorgh/memory/api.py` | TODO |
| `simorgh/memory/config.py` | TODO |
| `simorgh/memory/consolidation.py` | TODO |
| `simorgh/memory/embed.py` | TODO |
| `simorgh/memory/embedders.py` | TODO |
| `simorgh/memory/recall.py` | TODO |
| `simorgh/memory/service.py` | TODO |
| `simorgh/memory/store.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `memory.consolidated` | `messages/memory.py::MemoryConsolidated` | simorgh/memory/service.py | TODO |
| `memory.contradiction.flagged` | `messages/memory.py::MemoryContradictionFlagged` | simorgh/memory/service.py | TODO |
| `memory.forget` | `messages/memory.py::MemoryForget` | simorgh/memory/service.py | TODO |
| `memory.forgotten` | `messages/memory.py::MemoryForgotten` | simorgh/memory/service.py | TODO |
| `memory.retrieve` | `messages/memory.py::MemoryRetrieve` | simorgh/memory/service.py | TODO |
| `memory.retrieve.reply` | `messages/memory.py::MemoryRetrieveReply` | simorgh/memory/service.py | TODO |
| `memory.store` | `messages/memory.py::MemoryStore` | simorgh/memory/service.py | TODO |
| `memory.stored` | `messages/memory.py::MemoryStored` | simorgh/memory/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/memory/service.py | TODO |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/memory/service.py | TODO |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/memory/service.py | TODO |
| `turn.completed` | `messages/task.py::TurnCompleted` | simorgh/memory/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/memory/consolidation.py | TODO |
| `memory.consolidated` | `messages/memory.py::MemoryConsolidated` | simorgh/memory/service.py | TODO |
| `memory.contradiction.flagged` | `messages/memory.py::MemoryContradictionFlagged` | simorgh/memory/service.py | TODO |
| `memory.forget.reply` | `messages/memory.py::MemoryForgetReply` | simorgh/memory/service.py | TODO |
| `memory.forgotten` | `messages/memory.py::MemoryForgotten` | simorgh/memory/service.py | TODO |
| `memory.retrieve.reply` | `messages/memory.py::MemoryRetrieveReply` | simorgh/memory/service.py | TODO |
| `memory.stored` | `messages/memory.py::MemoryStored` | simorgh/memory/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/memory/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `contradiction:{ref_a}:{ref_b}` | simorgh/memory/store.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `memory:contradictions` | simorgh/memory/store.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `memory:tombstones` | simorgh/memory/store.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `memory:{kind}` | simorgh/memory/store.py | simorgh/execution/knowledge/index.py, simorgh/execution/vision.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/worker.py | see ledger/compaction.py DEFAULT_RETENTION |
| `person:{name}` | simorgh/memory/service.py | simorgh/guardian/rules.py, simorgh/orchestration/context.py, simorgh/voice/speakers.py, simorgh/voice/vad.py | see ledger/compaction.py DEFAULT_RETENTION |
| `working:{session_id}:{i}` | simorgh/memory/store.py | simorgh/interface/dispatch.py, simorgh/orchestration/context.py, simorgh/verification/checks/render.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[memory]` in simorgh.toml; dataclass in `simorgh/memory/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `half_life_seconds` | `DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS` | yes |
| `working_max_turns` | `20` | yes |
| `working_max_chars` | `8000` | yes |
| `default_k` | `5` | yes |
| `embedder` | `'hashing'` | yes |
| `recency_weight` | `0.1` | yes |
| `consolidate_after_start_s` | `120.0` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract memory`.

- `tests/simorgh/memory/test_consolidation.py` -- TODO: what it pins
- `tests/simorgh/memory/test_consolidation_actually_runs.py` -- TODO: what it pins
- `tests/simorgh/memory/test_consolidation_never_invents_a_memory.py` -- TODO: what it pins
- `tests/simorgh/memory/test_consolidation_never_invents_a_specific.py` -- TODO: what it pins
- `tests/simorgh/memory/test_contradiction_subjects.py` -- TODO: what it pins
- `tests/simorgh/memory/test_embedders.py` -- TODO: what it pins
- `tests/simorgh/memory/test_first_consolidation.py` -- TODO: what it pins
- `tests/simorgh/memory/test_long_content.py` -- TODO: what it pins
- `tests/simorgh/memory/test_quiet_is_not_remembered.py` -- TODO: what it pins
- `tests/simorgh/memory/test_recall_scaling.py` -- TODO: what it pins
- `tests/simorgh/memory/test_service.py` -- TODO: what it pins
- `tests/simorgh/memory/test_store.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim memory --by <you> --task "..."`), commit the lock, edit only `simorgh/memory/`, `tests/simorgh/memory/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py memory` before committing; commit subject `memory: <what changed>`.
