# planning -- contract

One-line status: layer 3 · 3,078 lines · 20 test files · lock: `planning` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/planning/__init__.py` | TODO |
| `simorgh/planning/api.py` | TODO |
| `simorgh/planning/bridge.py` | TODO |
| `simorgh/planning/config.py` | TODO |
| `simorgh/planning/dag.py` | TODO |
| `simorgh/planning/decomposer.py` | TODO |
| `simorgh/planning/dedupe.py` | TODO |
| `simorgh/planning/intake.py` | TODO |
| `simorgh/planning/model.py` | TODO |
| `simorgh/planning/planmode.py` | TODO |
| `simorgh/planning/reground.py` | TODO |
| `simorgh/planning/rollup.py` | TODO |
| `simorgh/planning/scheduler.py` | TODO |
| `simorgh/planning/service.py` | TODO |
| `simorgh/planning/store.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `curiosity.candidate` | `messages/curiosity.py::CuriosityCandidate` | simorgh/planning/service.py | TODO |
| `intent.goal.stated` | `messages/intent.py::IntentGoalStated` | simorgh/planning/service.py | TODO |
| `learn.self_patch.applied` | `messages/learn.py::LearnSelfPatchApplied` | simorgh/planning/service.py | TODO |
| `plan.reviewed` | `messages/plan.py::PlanReviewed` | simorgh/planning/service.py | TODO |
| `reflect.drift.detected` | `messages/reflect.py::ReflectDriftDetected` | simorgh/planning/service.py | TODO |
| `reflect.patterns.found` | `messages/reflect.py::ReflectPatternsFound` | simorgh/planning/service.py | TODO |
| `research.finding.recorded` | `messages/research.py::ResearchFindingRecorded` | simorgh/planning/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/planning/service.py | TODO |
| `system.tick.idle` | `messages/system.py::SystemTickIdle` | simorgh/planning/service.py | TODO |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/planning/service.py | TODO |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/planning/service.py | TODO |
| `task.cancel` | `messages/task.py::TaskCancel` | simorgh/planning/service.py | TODO |
| `task.claim` | `messages/task.py::TaskClaim` | simorgh/planning/service.py | TODO |
| `task.clear.request` | `messages/task.py::TaskClearRequest` | simorgh/planning/service.py | TODO |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/planning/service.py | TODO |
| `task.create` | `messages/task.py::TaskCreate` | simorgh/planning/service.py | TODO |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/planning/service.py | TODO |
| `task.lease_heartbeat` | `messages/task.py::TaskLeaseHeartbeat` | simorgh/planning/service.py | TODO |
| `task.list.request` | `messages/task.py::TaskListRequest` | simorgh/planning/service.py | TODO |
| `task.paused` | `messages/task.py::TaskPaused` | simorgh/planning/service.py | TODO |
| `task.started` | `messages/task.py::TaskStarted` | simorgh/planning/service.py | TODO |
| `task.step` | `messages/task.py::TaskStep` | simorgh/planning/service.py | TODO |
| `task.work_next.reply` | `messages/task.py::TaskWorkNextReply` | simorgh/planning/service.py | TODO |
| `task.work_next.request` | `messages/task.py::TaskWorkNextRequest` | simorgh/planning/service.py | TODO |
| `ui.prompt.answered` | `messages/ui.py::UiPromptAnswered` | simorgh/planning/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/planning/bridge.py | TODO |
| `plan.approved` | `messages/plan.py::PlanApproved` | simorgh/planning/service.py | TODO |
| `plan.proposed` | `messages/plan.py::PlanProposed` | simorgh/planning/service.py | TODO |
| `plan.revised` | `messages/plan.py::PlanRevised` | simorgh/planning/service.py | TODO |
| `project.completed` | `messages/plan.py::ProjectCompleted` | simorgh/planning/service.py | TODO |
| `project.failed` | `messages/plan.py::ProjectFailed` | simorgh/planning/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/planning/service.py | TODO |
| `task.available` | `messages/task.py::TaskAvailable` | simorgh/planning/scheduler.py, simorgh/planning/service.py | TODO |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/planning/service.py | TODO |
| `task.cancel` | `messages/task.py::TaskCancel` | simorgh/planning/service.py | TODO |
| `task.claim.reply` | `messages/task.py::TaskClaimReply` | simorgh/planning/service.py | TODO |
| `task.clear.reply` | `messages/task.py::TaskClearReply` | simorgh/planning/service.py | TODO |
| `task.cleared` | `messages/task.py::TaskCleared` | simorgh/planning/service.py | TODO |
| `task.create.reply` | `messages/task.py::TaskCreateReply` | simorgh/planning/service.py | TODO |
| `task.created` | `messages/task.py::TaskCreated` | simorgh/planning/service.py | TODO |
| `task.dependency.satisfied` | `messages/task.py::TaskDependencySatisfied` | simorgh/planning/service.py | TODO |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/planning/service.py | TODO |
| `task.list.reply` | `messages/task.py::TaskListReply` | simorgh/planning/service.py | TODO |
| `task.work_next.reply` | `messages/task.py::TaskWorkNextReply` | simorgh/planning/service.py | TODO |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/planning/service.py | TODO |
| `ui.prompt` | `messages/ui.py::UiPrompt` | simorgh/planning/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `dependency_failed:` | simorgh/planning/model.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `plan:{plan_id}` | simorgh/planning/service.py | simorgh/contracts/messages/plan.py, simorgh/ledger/streams.py | see ledger/compaction.py DEFAULT_RETENTION |
| `plan:{state.plan_id}` | simorgh/planning/service.py | simorgh/contracts/messages/plan.py, simorgh/ledger/streams.py | see ledger/compaction.py DEFAULT_RETENTION |
| `planning:index` | simorgh/planning/store.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `project:{project_id}` | simorgh/planning/service.py | simorgh/curiosity/service.py, simorgh/execution/security/selfcheck.py, simorgh/interface/render.py, simorgh/ledger/streams.py | see ledger/compaction.py DEFAULT_RETENTION |
| `task:` | simorgh/planning/store.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py, simorgh/orchestration/profiles.py, simorgh/orchestration/progress.py, simorgh/orchestration/resume.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/service.py, simorgh/orchestration/session.py, simorgh/orchestration/tools.py, simorgh/orchestration/worker.py, simorgh/reflection/service.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |
| `task:{dep_id}` | simorgh/planning/service.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py, simorgh/orchestration/profiles.py, simorgh/orchestration/progress.py, simorgh/orchestration/resume.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/service.py, simorgh/orchestration/session.py, simorgh/orchestration/tools.py, simorgh/orchestration/worker.py, simorgh/reflection/service.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |
| `task:{task.id}` | simorgh/planning/scheduler.py, simorgh/planning/service.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py, simorgh/orchestration/profiles.py, simorgh/orchestration/progress.py, simorgh/orchestration/resume.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/service.py, simorgh/orchestration/session.py, simorgh/orchestration/tools.py, simorgh/orchestration/worker.py, simorgh/reflection/service.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |
| `task:{task_id}` | simorgh/planning/service.py, simorgh/planning/store.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py, simorgh/orchestration/profiles.py, simorgh/orchestration/progress.py, simorgh/orchestration/resume.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/service.py, simorgh/orchestration/session.py, simorgh/orchestration/tools.py, simorgh/orchestration/worker.py, simorgh/reflection/service.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |
| `task:{tid}` | simorgh/planning/store.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py, simorgh/orchestration/profiles.py, simorgh/orchestration/progress.py, simorgh/orchestration/resume.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/service.py, simorgh/orchestration/session.py, simorgh/orchestration/tools.py, simorgh/orchestration/worker.py, simorgh/reflection/service.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |
| `task:{victim.id}` | simorgh/planning/service.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py, simorgh/orchestration/profiles.py, simorgh/orchestration/progress.py, simorgh/orchestration/resume.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/service.py, simorgh/orchestration/session.py, simorgh/orchestration/tools.py, simorgh/orchestration/worker.py, simorgh/reflection/service.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[planning]` in simorgh.toml; dataclass in `simorgh/planning/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `lease_seconds` | `600.0` | yes |
| `max_task_attempts` | `3` | NO (declared, never read) |
| `max_backlog` | `40` | yes |
| `max_blocked_retries` | `9` | yes |
| `blocked_retry_delay_seconds` | `300.0` | yes |
| `continuation_delay_seconds` | `10.0` | yes |
| `dedupe_similarity_threshold` | `0.45` | yes |
| `project_step_count` | `4` | yes |
| `source_roots` | `('simorgh/',)` | yes |
| `max_plan_revisions` | `2` | yes |
| `auto_approve_max_risk` | `'medium'` | yes |
| `human_approval_timeout_seconds` | `3600.0` | yes |
| `regrounding_age_seconds` | `21600.0` | yes |
| `reground_after_sibling_failure` | `True` | yes |
| `stalled_after_seconds` | `1800.0` | yes |
| `autonomous_origins` | `('curiosity', 'reflection', 'research', 'project', 'assistan` | yes |
| `priority_weights` | `field(default_factory=lambda: {'human': 3, 'project': 3, 'be` | yes |
| `leader` | `True` | NO (declared, never read) |
| `think_timeout_s` | `200.0` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract planning`.

- `tests/simorgh/planning/test_a_blocked_task_waits_its_retry_delay.py` -- TODO: what it pins
- `tests/simorgh/planning/test_a_claim_takes_the_best_ready_task.py` -- TODO: what it pins
- `tests/simorgh/planning/test_a_completion_after_the_lease_expired_is_not_lost.py` -- TODO: what it pins
- `tests/simorgh/planning/test_a_long_answer_still_completes_the_task.py` -- TODO: what it pins
- `tests/simorgh/planning/test_a_long_description_is_not_a_lost_task.py` -- TODO: what it pins
- `tests/simorgh/planning/test_a_paused_task_is_not_reopened_by_lease_expiry.py` -- TODO: what it pins
- `tests/simorgh/planning/test_completed_tasks_stay_completed.py` -- TODO: what it pins
- `tests/simorgh/planning/test_decomposer_dedupe_planmode.py` -- TODO: what it pins
- `tests/simorgh/planning/test_intake.py` -- TODO: what it pins
- `tests/simorgh/planning/test_model_dag_rollup.py` -- TODO: what it pins
- `tests/simorgh/planning/test_priority_is_actually_read.py` -- TODO: what it pins
- `tests/simorgh/planning/test_project_decomposition.py` -- TODO: what it pins
- `tests/simorgh/planning/test_reground.py` -- TODO: what it pins
- `tests/simorgh/planning/test_retries_do_not_starve_fresh_work.py` -- TODO: what it pins
- `tests/simorgh/planning/test_scheduler.py` -- TODO: what it pins
- `tests/simorgh/planning/test_store.py` -- TODO: what it pins
- `tests/simorgh/planning/test_task_create_reply.py` -- TODO: what it pins
- `tests/simorgh/planning/test_tasks_clear.py` -- TODO: what it pins
- `tests/simorgh/planning/test_the_backlog_is_bounded.py` -- TODO: what it pins
- `tests/simorgh/planning/test_the_backlog_is_offered_without_an_idle_tick.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim planning --by <you> --task "..."`), commit the lock, edit only `simorgh/planning/`, `tests/simorgh/planning/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py planning` before committing; commit subject `planning: <what changed>`.
