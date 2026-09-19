# benchmark -- contract

One-line status: layer 5 · 2,822 lines · 17 test files · lock: `benchmark` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/benchmark/__init__.py` | TODO |
| `simorgh/benchmark/api.py` | TODO |
| `simorgh/benchmark/config.py` | TODO |
| `simorgh/benchmark/datasets.py` | TODO |
| `simorgh/benchmark/runner.py` | TODO |
| `simorgh/benchmark/scoring.py` | TODO |
| `simorgh/benchmark/service.py` | TODO |
| `simorgh/benchmark/store.py` | TODO |
| `simorgh/benchmark/swebench.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `benchmark.history.reply` | `messages/benchmark.py::BenchmarkHistoryReply` | simorgh/benchmark/service.py | TODO |
| `benchmark.history.request` | `messages/benchmark.py::BenchmarkHistoryRequest` | simorgh/benchmark/service.py | TODO |
| `benchmark.load.request` | `messages/benchmark.py::BenchmarkLoadRequest` | simorgh/benchmark/service.py | TODO |
| `benchmark.run.request` | `messages/benchmark.py::BenchmarkRunRequest` | simorgh/benchmark/service.py | TODO |
| `benchmark.stop.reply` | `messages/benchmark.py::BenchmarkStopReply` | simorgh/benchmark/service.py | TODO |
| `benchmark.stop.request` | `messages/benchmark.py::BenchmarkStopRequest` | simorgh/benchmark/service.py | TODO |
| `benchmark.suites.request` | `messages/benchmark.py::BenchmarkSuitesRequest` | simorgh/benchmark/service.py | TODO |
| `cognition.provider.status` | `messages/cognition.py::CognitionProviderStatus` | simorgh/benchmark/service.py | TODO |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/benchmark/runner.py | TODO |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/benchmark/runner.py | TODO |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/benchmark/runner.py | TODO |
| `task.started` | `messages/task.py::TaskStarted` | simorgh/benchmark/runner.py | TODO |
| `task.step` | `messages/task.py::TaskStep` | simorgh/benchmark/runner.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `benchmark.history.reply` | `messages/benchmark.py::BenchmarkHistoryReply` | simorgh/benchmark/service.py | TODO |
| `benchmark.load.reply` | `messages/benchmark.py::BenchmarkLoadReply` | simorgh/benchmark/service.py | TODO |
| `benchmark.progress` | `messages/benchmark.py::BenchmarkProgress` | simorgh/benchmark/service.py | TODO |
| `benchmark.run.completed` | `messages/benchmark.py::BenchmarkRunCompleted` | simorgh/benchmark/service.py | TODO |
| `benchmark.run.reply` | `messages/benchmark.py::BenchmarkRunReply` | simorgh/benchmark/service.py | TODO |
| `benchmark.stop.reply` | `messages/benchmark.py::BenchmarkStopReply` | simorgh/benchmark/service.py | TODO |
| `benchmark.suites.reply` | `messages/benchmark.py::BenchmarkSuitesReply` | simorgh/benchmark/service.py | TODO |
| `task.cancel` | `messages/task.py::TaskCancel` | simorgh/benchmark/runner.py, simorgh/benchmark/service.py | TODO |
| `task.create` | `messages/task.py::TaskCreate` | simorgh/benchmark/runner.py | TODO |
| `task.list.request` | `messages/task.py::TaskListRequest` | simorgh/benchmark/service.py | TODO |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/benchmark/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `benchmark:runs` | simorgh/benchmark/store.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `task:{task_id}` | simorgh/benchmark/runner.py | simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py, simorgh/orchestration/profiles.py, simorgh/orchestration/progress.py, simorgh/orchestration/resume.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/service.py, simorgh/orchestration/session.py, simorgh/orchestration/tools.py, simorgh/orchestration/worker.py, simorgh/planning/api.py, simorgh/planning/dag.py, simorgh/planning/intake.py, simorgh/planning/scheduler.py, simorgh/planning/service.py, simorgh/planning/store.py, simorgh/reflection/service.py, simorgh/verification/checklist.py, simorgh/verification/checks/fullsuiteran.py, simorgh/verification/service.py, simorgh/verification/trajectory.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[benchmark]` in simorgh.toml; dataclass in `simorgh/benchmark/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `default_cases` | `10` | yes |
| `case_timeout_s` | `600.0` | yes |
| `case_claim_timeout_s` | `1800.0` | yes |
| `case_max_steps` | `30` | yes |
| `concurrency` | `1` | NO (declared, never read) |
| `floor_retries` | `3` | yes |
| `floor_retry_wait_s` | `60.0` | yes |
| `fetch_timeout_s` | `30.0` | yes |
| `cache_dir` | `''` | yes |
| `history_limit` | `200` | yes |
| `attachment_dir` | `'workspace/benchmark'` | yes |
| `swebench_checkout_dir` | `'workspace/swebench'` | yes |
| `swebench_log_dir` | `'results/swebench'` | yes |
| `swebench_eval_timeout_s` | `3600.0` | yes |
| `swebench_setup_timeout_s` | `1800.0` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract benchmark`.

- `tests/simorgh/benchmark/test_a_case_that_never_started_is_not_an_answer.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_a_coloured_log_is_still_a_result.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_a_committed_fix_is_still_a_patch.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_a_failure_stays_in_the_denominator.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_a_floor_reply_is_not_an_answer.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_a_mode_flip_is_not_a_patch.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_api.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_attachments.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_checkout_manifest.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_cli_and_web.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_cost_is_real.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_levels.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_model_and_render.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_scoring.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_service_flow.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_swebench.py` -- TODO: what it pins
- `tests/simorgh/benchmark/test_the_image_tree_is_the_baseline.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim benchmark --by <you> --task "..."`), commit the lock, edit only `simorgh/benchmark/`, `tests/simorgh/benchmark/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py benchmark` before committing; commit subject `benchmark: <what changed>`.
