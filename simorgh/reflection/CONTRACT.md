# reflection -- contract

One-line status: layer 4 · 2,157 lines · 10 test files · lock: `reflection` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/reflection/__init__.py` | TODO |
| `simorgh/reflection/api.py` | TODO |
| `simorgh/reflection/calibration.py` | TODO |
| `simorgh/reflection/config.py` | TODO |
| `simorgh/reflection/critique.py` | TODO |
| `simorgh/reflection/denials.py` | TODO |
| `simorgh/reflection/digest.py` | TODO |
| `simorgh/reflection/distillation.py` | TODO |
| `simorgh/reflection/drift.py` | TODO |
| `simorgh/reflection/health.py` | TODO |
| `simorgh/reflection/patterns.py` | TODO |
| `simorgh/reflection/service.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/reflection/service.py | TODO |
| `learn.outcome.recorded` | `messages/learn.py::LearnOutcomeRecorded` | simorgh/reflection/service.py | TODO |
| `learn.self_patch.applied` | `messages/learn.py::LearnSelfPatchApplied` | simorgh/reflection/service.py | TODO |
| `learn.self_patch.reverted` | `messages/learn.py::LearnSelfPatchReverted` | simorgh/reflection/service.py | TODO |
| `learn.skill.acquired` | `messages/learn.py::LearnSkillAcquired` | simorgh/reflection/service.py | TODO |
| `persona.state.changed` | `messages/persona.py::PersonaStateChanged` | simorgh/reflection/service.py | TODO |
| `plan.revised` | `messages/plan.py::PlanRevised` | simorgh/reflection/service.py | TODO |
| `reflect.review.reply` | `messages/reflect.py::ReflectReviewReply` | simorgh/reflection/service.py | TODO |
| `reflect.review.request` | `messages/reflect.py::ReflectReviewRequest` | simorgh/reflection/service.py | TODO |
| `self.observation` | `messages/self_.py::SelfObservation` | simorgh/reflection/service.py | TODO |
| `system.started` | `messages/system.py::SystemStarted` | simorgh/reflection/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/reflection/service.py | TODO |
| `system.tick.idle` | `messages/system.py::SystemTickIdle` | simorgh/reflection/service.py | TODO |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/reflection/service.py | TODO |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/reflection/service.py | TODO |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/reflection/service.py | TODO |
| `task.created` | `messages/task.py::TaskCreated` | simorgh/reflection/service.py | TODO |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/reflection/service.py | TODO |
| `task.step` | `messages/task.py::TaskStep` | simorgh/reflection/service.py | TODO |
| `verify.result` | `messages/verify.py::VerifyResult` | simorgh/reflection/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/reflection/service.py | TODO |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/reflection/service.py | TODO |
| `memory.store` | `messages/memory.py::MemoryStore` | simorgh/reflection/service.py | TODO |
| `reflect.alert.cleared` | `messages/reflect.py::ReflectAlertCleared` | simorgh/reflection/service.py | TODO |
| `reflect.alert.raised` | `messages/reflect.py::ReflectAlertRaised` | simorgh/reflection/service.py | TODO |
| `reflect.calibration.updated` | `messages/reflect.py::ReflectCalibrationUpdated` | simorgh/reflection/service.py | TODO |
| `reflect.drift.detected` | `messages/reflect.py::ReflectDriftDetected` | simorgh/reflection/service.py | TODO |
| `reflect.health.finding` | `messages/reflect.py::ReflectHealthFinding` | simorgh/reflection/service.py | TODO |
| `reflect.patterns.found` | `messages/reflect.py::ReflectPatternsFound` | simorgh/reflection/service.py | TODO |
| `reflect.review.reply` | `messages/reflect.py::ReflectReviewReply` | simorgh/reflection/service.py | TODO |
| `self.observation` | `messages/self_.py::SelfObservation` | simorgh/reflection/service.py | TODO |
| `system.health` | `messages/system.py::SystemHealth` | simorgh/reflection/service.py | TODO |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/reflection/service.py | TODO |
| `task.create` | `messages/task.py::TaskCreate` | simorgh/reflection/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `cert:ha.local` | simorgh/reflection/digest.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `reflect:calibration` | simorgh/reflection/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `reflect:critique:` | simorgh/reflection/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `reflect:critique:{task_id}` | simorgh/reflection/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `reflect:distillation` | simorgh/reflection/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `reflect:drift:` | simorgh/reflection/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `reflect:health` | simorgh/reflection/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `reflect:patterns` | simorgh/reflection/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `reflect:self` | simorgh/reflection/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `reflection:alerts` | simorgh/reflection/service.py | simorgh/interface/dispatch.py | see ledger/compaction.py DEFAULT_RETENTION |
| `task:{task_id}` | simorgh/reflection/service.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py, simorgh/orchestration/profiles.py, simorgh/orchestration/progress.py, simorgh/orchestration/resume.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/service.py, simorgh/orchestration/session.py, simorgh/orchestration/tools.py, simorgh/orchestration/worker.py, simorgh/planning/api.py, simorgh/planning/dag.py, simorgh/planning/intake.py, simorgh/planning/scheduler.py, simorgh/planning/service.py, simorgh/planning/store.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[reflection]` in simorgh.toml; dataclass in `simorgh/reflection/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `health_window` | `12` | yes |
| `health_extreme` | `0.9` | yes |
| `health_pinned_n` | `5` | yes |
| `health_load_ceiling` | `0.95` | yes |
| `health_oscillation_warn` | `6` | yes |
| `health_oscillation_critical` | `8` | yes |
| `drift_check_every_steps` | `8` | yes |
| `drift_heuristic_threshold` | `0.5` | yes |
| `drift_emit_threshold` | `0.6` | yes |
| `stall_idle_seconds` | `1800.0` | yes |
| `critique_max_tokens` | `400` | yes |
| `distillation_enabled` | `True` | yes |
| `max_distillations_per_day` | `3` | yes |
| `skill_dir` | `'simorgh_skills'` | yes |
| `pattern_window_seconds` | `86400.0` | yes |
| `pattern_min_rate` | `0.5` | yes |
| `pattern_min_samples` | `3` | yes |
| `denial_window_seconds` | `3600.0` | yes |
| `denial_min_repeats` | `5` | yes |
| `monitors_enabled` | `True` | yes |
| `alert_warn_window_s` | `3600.0` | yes |
| `quiet_hours` | `''` | yes |
| `digest_enabled` | `True` | yes |
| `digest_hour` | `8` | yes |
| `announce_critical` | `False` | yes |
| `calibration_bins` | `10` | yes |
| `calibration_min_samples` | `10` | yes |
| `review_timeout_s` | `8.0` | yes |
| `max_concurrent_reviews` | `2` | yes |
| `reflect_after_start_s` | `120.0` | yes |
| `reflect_every_s` | `3600.0` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract reflection`.

- `tests/simorgh/reflection/test_calibration.py` -- TODO: what it pins
- `tests/simorgh/reflection/test_config.py` -- TODO: what it pins
- `tests/simorgh/reflection/test_critique.py` -- TODO: what it pins
- `tests/simorgh/reflection/test_digest.py` -- TODO: what it pins
- `tests/simorgh/reflection/test_distillation.py` -- TODO: what it pins
- `tests/simorgh/reflection/test_drift.py` -- TODO: what it pins
- `tests/simorgh/reflection/test_health.py` -- TODO: what it pins
- `tests/simorgh/reflection/test_patterns.py` -- TODO: what it pins
- `tests/simorgh/reflection/test_service_alerts.py` -- TODO: what it pins
- `tests/simorgh/reflection/test_service_stall.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim reflection --by <you> --task "..."`), commit the lock, edit only `simorgh/reflection/`, `tests/simorgh/reflection/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py reflection` before committing; commit subject `reflection: <what changed>`.
