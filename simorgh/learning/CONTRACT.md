# learning -- contract

One-line status: layer 4 · 727 lines · 4 test files · lock: `learning` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/learning/__init__.py` | TODO |
| `simorgh/learning/competence.py` | TODO |
| `simorgh/learning/config.py` | TODO |
| `simorgh/learning/correlator.py` | TODO |
| `simorgh/learning/models.py` | TODO |
| `simorgh/learning/outcomes.py` | TODO |
| `simorgh/learning/service.py` | TODO |
| `simorgh/learning/strategy.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/learning/service.py | TODO |
| `action.result` | `messages/action.py::ActionResult` | simorgh/learning/service.py | TODO |
| `learn.competence.updated` | `messages/learn.py::LearnCompetenceUpdated` | simorgh/learning/service.py | TODO |
| `learn.outcome.recorded` | `messages/learn.py::LearnOutcomeRecorded` | simorgh/learning/service.py | TODO |
| `learn.strategy.suggest` | `messages/learn.py::LearnStrategySuggest` | simorgh/learning/service.py | TODO |
| `learn.strategy.suggest.reply` | `messages/learn.py::LearnStrategySuggestReply` | simorgh/learning/service.py | TODO |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/learning/service.py | TODO |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/learning/service.py | TODO |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/learning/service.py | TODO |
| `verify.result` | `messages/verify.py::VerifyResult` | simorgh/learning/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/learning/service.py | TODO |
| `learn.competence.updated` | `messages/learn.py::LearnCompetenceUpdated` | simorgh/learning/outcomes.py, simorgh/learning/service.py | TODO |
| `learn.outcome.recorded` | `messages/learn.py::LearnOutcomeRecorded` | simorgh/learning/outcomes.py, simorgh/learning/service.py | TODO |
| `learn.self_patch.applied` | `messages/learn.py::LearnSelfPatchApplied` | simorgh/learning/service.py | TODO |
| `learn.self_patch.reverted` | `messages/learn.py::LearnSelfPatchReverted` | simorgh/learning/service.py | TODO |
| `learn.skill.acquired` | `messages/learn.py::LearnSkillAcquired` | simorgh/learning/service.py | TODO |
| `learn.strategy.suggest.reply` | `messages/learn.py::LearnStrategySuggestReply` | simorgh/learning/service.py | TODO |
| `memory.store` | `messages/memory.py::MemoryStore` | simorgh/learning/service.py | TODO |
| `verify.requested` | `messages/verify.py::VerifyRequested` | simorgh/learning/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `learn:outcomes` | simorgh/learning/competence.py, simorgh/learning/outcomes.py, simorgh/learning/service.py | simorgh/ledger/compaction.py | see ledger/compaction.py DEFAULT_RETENTION |
| `learn:patch:{task_id}` | simorgh/learning/outcomes.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `task:{task_id}` | simorgh/learning/outcomes.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py, simorgh/orchestration/profiles.py, simorgh/orchestration/progress.py, simorgh/orchestration/resume.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/service.py, simorgh/orchestration/session.py, simorgh/orchestration/tools.py, simorgh/orchestration/worker.py, simorgh/planning/api.py, simorgh/planning/dag.py, simorgh/planning/intake.py, simorgh/planning/scheduler.py, simorgh/planning/service.py, simorgh/planning/store.py, simorgh/reflection/service.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[learning]` in simorgh.toml; dataclass in `simorgh/learning/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `max_draft_attempts` | `3` | NO (declared, never read) |
| `max_pipeline_wall_seconds` | `900.0` | NO (declared, never read) |
| `action_timeout_seconds` | `60.0` | NO (declared, never read) |
| `verify_timeout_seconds` | `300.0` | NO (declared, never read) |
| `hot_swap_slots` | `('logic', 'emotion', 'skills')` | NO (declared, never read) |
| `explore_bonus` | `0.15` | yes |
| `min_samples_for_trust` | `5` | yes |
| `blocked_sample_weight` | `0.5` | yes |
| `max_concurrent_pipelines` | `2` | NO (declared, never read) |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract learning`.

- `tests/simorgh/learning/test_competence.py` -- TODO: what it pins
- `tests/simorgh/learning/test_outcomes.py` -- TODO: what it pins
- `tests/simorgh/learning/test_service.py` -- TODO: what it pins
- `tests/simorgh/learning/test_strategy.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim learning --by <you> --task "..."`), commit the lock, edit only `simorgh/learning/`, `tests/simorgh/learning/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py learning` before committing; commit subject `learning: <what changed>`.
