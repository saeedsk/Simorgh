# orchestration -- contract

One-line status: layer X · 5,664 lines · 30 test files · lock: `orchestration` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/orchestration/__init__.py` | TODO |
| `simorgh/orchestration/api.py` | TODO |
| `simorgh/orchestration/claims.py` | TODO |
| `simorgh/orchestration/config.py` | TODO |
| `simorgh/orchestration/context.py` | TODO |
| `simorgh/orchestration/profiles.py` | TODO |
| `simorgh/orchestration/progress.py` | TODO |
| `simorgh/orchestration/resume.py` | TODO |
| `simorgh/orchestration/scaffolds.py` | TODO |
| `simorgh/orchestration/service.py` | TODO |
| `simorgh/orchestration/session.py` | TODO |
| `simorgh/orchestration/tools.py` | TODO |
| `simorgh/orchestration/worker.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/orchestration/service.py, simorgh/orchestration/session.py | TODO |
| `action.needs_human` | `messages/action.py::ActionNeedsHuman` | simorgh/orchestration/service.py | TODO |
| `action.result` | `messages/action.py::ActionResult` | simorgh/orchestration/service.py, simorgh/orchestration/session.py | TODO |
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | simorgh/orchestration/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/orchestration/service.py, simorgh/orchestration/worker.py | TODO |
| `task.available` | `messages/task.py::TaskAvailable` | simorgh/orchestration/service.py, simorgh/orchestration/worker.py | TODO |
| `task.cancel` | `messages/task.py::TaskCancel` | simorgh/orchestration/worker.py | TODO |
| `task.claim` | `messages/task.py::TaskClaim` | simorgh/orchestration/worker.py | TODO |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/orchestration/service.py | TODO |
| `task.paused` | `messages/task.py::TaskPaused` | simorgh/orchestration/service.py | TODO |
| `task.progress` | `messages/task.py::TaskProgress` | simorgh/orchestration/resume.py | TODO |
| `task.started` | `messages/task.py::TaskStarted` | simorgh/orchestration/resume.py, simorgh/orchestration/service.py | TODO |
| `task.step` | `messages/task.py::TaskStep` | simorgh/orchestration/resume.py, simorgh/orchestration/service.py | TODO |
| `tool.probed` | `messages/tool.py::ToolProbed` | simorgh/orchestration/service.py | TODO |
| `tool.registered` | `messages/tool.py::ToolRegistered` | simorgh/orchestration/service.py | TODO |
| `verify.result` | `messages/verify.py::VerifyResult` | simorgh/orchestration/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/orchestration/service.py, simorgh/orchestration/session.py | TODO |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/orchestration/session.py | TODO |
| `learn.self_patch.applied` | `messages/learn.py::LearnSelfPatchApplied` | simorgh/orchestration/session.py | TODO |
| `memory.store` | `messages/memory.py::MemoryStore` | simorgh/orchestration/service.py, simorgh/orchestration/worker.py | TODO |
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | simorgh/orchestration/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/orchestration/service.py | TODO |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/orchestration/service.py | TODO |
| `task.claim` | `messages/task.py::TaskClaim` | simorgh/orchestration/worker.py | TODO |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/orchestration/service.py | TODO |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/orchestration/service.py | TODO |
| `task.lease_heartbeat` | `messages/task.py::TaskLeaseHeartbeat` | simorgh/orchestration/worker.py | TODO |
| `task.paused` | `messages/task.py::TaskPaused` | simorgh/orchestration/service.py, simorgh/orchestration/session.py | TODO |
| `task.started` | `messages/task.py::TaskStarted` | simorgh/orchestration/service.py, simorgh/orchestration/session.py | TODO |
| `task.step` | `messages/task.py::TaskStep` | simorgh/orchestration/service.py, simorgh/orchestration/session.py | TODO |
| `tool.registered` | `messages/tool.py::ToolRegistered` | simorgh/orchestration/service.py | TODO |
| `turn.completed` | `messages/task.py::TurnCompleted` | simorgh/orchestration/service.py, simorgh/orchestration/worker.py | TODO |
| `verify.requested` | `messages/verify.py::VerifyRequested` | simorgh/orchestration/service.py, simorgh/orchestration/session.py | TODO |
| `verify.result` | `messages/verify.py::VerifyResult` | simorgh/orchestration/session.py | TODO |
| `world.env.query` | `messages/world.py::WorldEnvQuery` | simorgh/orchestration/context.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `execution:tools` | simorgh/orchestration/service.py | simorgh/execution/service.py, simorgh/interface/dispatch.py, simorgh/ledger/compaction.py | see ledger/compaction.py DEFAULT_RETENTION |
| `person:` | simorgh/orchestration/context.py | simorgh/guardian/rules.py, simorgh/memory/service.py, simorgh/voice/speakers.py, simorgh/voice/vad.py | see ledger/compaction.py DEFAULT_RETENTION |
| `person:{speaker}` | simorgh/orchestration/context.py | simorgh/guardian/rules.py, simorgh/memory/service.py, simorgh/voice/speakers.py, simorgh/voice/vad.py | see ledger/compaction.py DEFAULT_RETENTION |
| `skill:` | simorgh/orchestration/tools.py | simorgh/contracts/toolargs.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/interface/dispatch.py | see ledger/compaction.py DEFAULT_RETENTION |
| `someone:` | simorgh/orchestration/scaffolds.py | simorgh/memory/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |
| `task:{session.task_id}` | simorgh/orchestration/resume.py, simorgh/orchestration/session.py, simorgh/orchestration/worker.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/planning/api.py, simorgh/planning/dag.py, simorgh/planning/intake.py, simorgh/planning/scheduler.py, simorgh/planning/service.py, simorgh/planning/store.py, simorgh/reflection/service.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |
| `task:{task_id}` | simorgh/orchestration/worker.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/planning/api.py, simorgh/planning/dag.py, simorgh/planning/intake.py, simorgh/planning/scheduler.py, simorgh/planning/service.py, simorgh/planning/store.py, simorgh/reflection/service.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[orchestration]` in simorgh.toml; dataclass in `simorgh/orchestration/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `workers` | `1` | yes |
| `review_benchmark` | `True` | yes |
| `reground_every_steps` | `0` | yes |
| `keep_recent_steps` | `2` | yes |
| `clean_revisions` | `False` | yes |
| `delegation` | `False` | yes |
| `delegate_max_steps` | `12` | yes |
| `escalate_from_attempt` | `0` | yes |
| `parallel_read_tools` | `1` | yes |
| `skills_enabled` | `True` | yes |
| `skills_catalog_max_chars` | `3000` | yes |
| `skills_roots` | `('skills', '~/.simorgh/skills')` | yes |
| `skills_channels` | `('', 'cli', 'http')` | yes |
| `lease_seconds` | `600` | yes |
| `heartbeat_s` | `30` | yes |
| `max_depth` | `3` | yes |
| `max_children_concurrent` | `4` | NO (declared, never read) |
| `think_timeout_s` | `200.0` | yes |
| `needs_human_timeout_s` | `600.0` | NO (declared, never read) |
| `worktrees` | `True` | yes |
| `metrics_interval_s` | `3.0` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract orchestration`.

- `tests/simorgh/orchestration/test_api_and_profiles.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_attempts.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_cancel.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_catalog_channels.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_claims.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_clean_retries.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_context.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_delegate.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_escalation.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_honesty_claims.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_never_leave_a_broken_tree.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_one_task_at_a_time.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_parallel_reads.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_procedural_memory.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_pronunciation_claim.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_reground.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_scaffolds.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_scratch_workspace.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_session_flows.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_sim_knows_what_day_it_is.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_skills_catalog.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_the_memory_block_remembers_recent_turns.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_the_model_can_see_its_tools.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_tools_router.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_verify_subject_truncation.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_voice_can_do_what_chat_can_say.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_what_gets_written.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_worker.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_worktree_flow.py` -- TODO: what it pins
- `tests/simorgh/orchestration/test_wrote_misses_run_shell_run_script.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim orchestration --by <you> --task "..."`), commit the lock, edit only `simorgh/orchestration/`, `tests/simorgh/orchestration/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py orchestration` before committing; commit subject `orchestration: <what changed>`.
