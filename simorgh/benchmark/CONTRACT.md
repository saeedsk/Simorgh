# benchmark -- contract

One-line status: layer 5 · 2,822 lines · 17 test files · lock: `benchmark` in docs/modules/locks.toml

## Purpose

Benchmark measures the whole running system against standard suites (GAIA, GAIA level 1, BFCL parallel, SWE-bench Verified) and keeps a per-model history of the results on the ledger. It owns suite download and caching (Hugging Face datasets-server over plain HTTPS, cache outside the repo under `~/.simorgh/benchmarks`), the published scorers (GAIA quasi-exact match, BFCL call match, SWE-bench by running the instance's tests in its container), and the run record. It must never call Cognition or a tool directly: every case is a `task.create{origin: benchmark}` on the bus, answered through Planning, Guardian, Orchestration and Verification, because the point is to measure Sim and not the model (`runner.py:1-12`). It must never guess a score: a case that was never asked, was answered by the offline floor, or could not be evaluated is `skipped` (out of the denominator), never wrong. Only one run at a time, so two runs do not measure each other's contention (`service.py:9-10`).

## Files

| File | For |
|---|---|
| `simorgh/benchmark/__init__.py` | empty package marker |
| `simorgh/benchmark/api.py` | `Case`, `Suite` (levels, sampling), `CaseResult`, `RunRecord` (totals, compact and full payloads) |
| `simorgh/benchmark/config.py` | frozen `Config` and `from_mapping` for `[benchmark]` |
| `simorgh/benchmark/datasets.py` | suite `SOURCES`, datasets-server fetch with retries, row -> `Case` parsers, cache, attachment download |
| `simorgh/benchmark/runner.py` | `Runner`: one task per case, waits for start then outcome, floor retries, SWE-bench checkout/diff/evaluate, cancels abandoned tasks |
| `simorgh/benchmark/scoring.py` | GAIA answer extraction and normalisation, BFCL call parsing and matching, `score_case` |
| `simorgh/benchmark/service.py` | the `Service`: request/reply handlers, one background run, progress and completion messages, orphan sweep at boot |
| `simorgh/benchmark/store.py` | `RunStore`: `benchmark:runs` summaries inline, per-case detail as a blob |
| `simorgh/benchmark/swebench.py` | Docker detection, checkout materialisation with a `ContainerCheckout` manifest, diff, test-log parsing, `judge`/`evaluate` |

## Consumes

Exact subscription list: `_CONSUMES` (`service.py:32-42`). The five `task.*` subscriptions are made per case by `runner.py::_AnswerWatch` and removed when the case ends.

| Topic | Schema | Where | Does |
|---|---|---|---|
| `benchmark.suites.request` | `messages/benchmark.py::BenchmarkSuitesRequest` | simorgh/benchmark/service.py | replies with each known suite, whether it is gated/scorable, cached case count and levels |
| `benchmark.run.request` | `messages/benchmark.py::BenchmarkRunRequest` | simorgh/benchmark/service.py | validates suite, Docker, level and sample, starts the background run, replies with the run id |
| `benchmark.history.request` | `messages/benchmark.py::BenchmarkHistoryRequest` | simorgh/benchmark/service.py | replies with run summaries (the last two scored runs per suite with cases), or one run's detail by `run_id` |
| `benchmark.load.request` | `messages/benchmark.py::BenchmarkLoadRequest` | simorgh/benchmark/service.py | downloads and caches a suite without running it |
| `benchmark.stop.request` | `messages/benchmark.py::BenchmarkStopRequest` | simorgh/benchmark/service.py | cancels the run in flight (its partial record is stored) and replies |
| `cognition.provider.status` | `messages/cognition.py::CognitionProviderStatus` | simorgh/benchmark/service.py | remembers the selected model for the per-model history |
| `task.started` | `messages/task.py::TaskStarted` | simorgh/benchmark/runner.py | starts the case's answer clock |
| `task.step` | `messages/task.py::TaskStep` | simorgh/benchmark/runner.py | sums `cost_usd` and counts steps per case task |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/benchmark/runner.py | the case's answer (`result_summary`; `floor` means skipped) |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/benchmark/runner.py | case outcome with its reason |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/benchmark/runner.py | case outcome with its reason (any partial answer is still scored) |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `benchmark.suites.reply` | `messages/benchmark.py::BenchmarkSuitesReply` | simorgh/benchmark/service.py | reply to suites request |
| `benchmark.run.reply` | `messages/benchmark.py::BenchmarkRunReply` | simorgh/benchmark/service.py | reply to run request: started, or an error (`already_running`, `dataset_unavailable`, `not_scorable`, `needs_docker`, `no_such_level`, `no_cases`) |
| `benchmark.history.reply` | `messages/benchmark.py::BenchmarkHistoryReply` | simorgh/benchmark/service.py | reply to history request (also used by `interface/httpapi.py` for the dashboard) |
| `benchmark.load.reply` | `messages/benchmark.py::BenchmarkLoadReply` | simorgh/benchmark/service.py | reply to load request |
| `benchmark.stop.reply` | `messages/benchmark.py::BenchmarkStopReply` | simorgh/benchmark/service.py | reply to stop request |
| `benchmark.progress` | `messages/benchmark.py::BenchmarkProgress` | simorgh/benchmark/service.py | after each case is scored (consumed by Interface) |
| `benchmark.run.completed` | `messages/benchmark.py::BenchmarkRunCompleted` | simorgh/benchmark/service.py | a run finishes (not when cancelled or crashed); allow-listed one-sided |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/benchmark/service.py | the run's one-line result after completion |
| `task.create` | `messages/task.py::TaskCreate` | simorgh/benchmark/runner.py | request, one per case: `origin: benchmark`, `mode: execute`, `max_steps: case_max_steps`, kind `research` or `patch` |
| `task.cancel` | `messages/task.py::TaskCancel` | simorgh/benchmark/runner.py, simorgh/benchmark/service.py | a case not started in time, timed out, or stopped; and at boot for every open `benchmark`-origin task (not in `_PRODUCES`) |
| `task.list.request` | `messages/task.py::TaskListRequest` | simorgh/benchmark/service.py | request, once at start, to find orphaned benchmark tasks (not in `_PRODUCES`) |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `benchmark:runs` | simorgh/benchmark/store.py | - (Interface reads it only through `benchmark.history.request`) | forever (no `DEFAULT_RETENTION` entry); one event per run, detail in a blob |

`task:{id}` appears in the code only as a bus `partition_key` on `task.cancel`, not as a stream Benchmark reads or writes. SWE-bench test logs go to files under `swebench_log_dir`, not the ledger.

## Config

`[benchmark]` in simorgh.toml; dataclass in `simorgh/benchmark/config.py`. `from_mapping` takes flat keys that match field names and drops anything else. `HF_TOKEN` (gated datasets) is read from the process environment (`datasets.py:290`), not from `ctx.secrets`.

| Key | Default | Read in the package |
|---|---|---|
| `default_cases` | `10` | yes |
| `case_timeout_s` | `600.0` | yes |
| `case_claim_timeout_s` | `1800.0` | yes |
| `case_max_steps` | `30` | yes |
| `concurrency` | `1` | NO (declared, never read; cases always run one at a time) |
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

- `simorgh.benchmark.service.Service` (`name = "benchmark"`, keyword-only `config`): the Subsystem; `health()` is always `ok` ("idle" or "running <suite>").
- `Config` (`config.py`), read by `kernel/configcheck.py`.
- The rest (`Runner`, `RunStore`, `RunRecord`, scorers, `swebench`) is internal; no other package imports it (the Kernel registry imports only `Service`). `tools/bench_instance.py` drives it from outside the process.
- Shared contract used: `simorgh.contracts.checkout.ContainerCheckout` (the checkout manifest Execution reads so `run_tests`/`git_commit` work inside a materialised SWE-bench checkout).
- Module-level mutable state: `datasets.SOURCES` is a module dict (read-only in practice). No singletons. `Runner` defaults `repo_root` to `Path.cwd()` and the Service does not pass one (`service.py:400`), so attachments and checkouts are placed relative to the working directory.

## Invariants

- `Service.consumes` covers every subscription in the package, including the runner's per-case `task.*` subscriptions (`tests/simorgh/test_manifests_match_the_code.py`).
- Benchmark never subscribes to `action.proposed`/`action.approved` and never publishes the `PUBLISH_ONLY_BY` topics (`contracts/topics.py`; no policy entry names Benchmark itself).
- Every case is asked through `task.create` with `origin: benchmark`, never `human`, and never by a direct Cognition call.
- At most one run is in flight; a second `benchmark.run.request` gets `already_running` with progress and how to stop it.
- The runner subscribes before it creates the task, so a fast answer cannot be missed.
- "Never started within `case_claim_timeout_s`", "Planning deduplicated the case", "the offline floor answered", "attachment could not be fetched", "Docker missing" and "tests could not run" are `skipped`, not wrong; a skipped case is not in the accuracy denominator.
- A floor-answered case is retried up to `floor_retries` times with doubling waits before it stays skipped.
- Every case task the run abandons (timeout, not started, stop) gets a `task.cancel`; at boot every open `benchmark`-origin task is cancelled.
- A stopped or crashed run is still stored, marked `partial`, with the cases it answered.
- A SWE-bench case is scored only by running `FAIL_TO_PASS` and `PASS_TO_PASS` in the instance's image; the diff is taken against the checkout's pristine tree (committed fixes included, mode-only changes excluded); the model's reply text is never evidence.
- GAIA scoring matches the published quasi-exact-match rules; BFCL scoring matches function names and arguments.
- Progress messages for every case are delivered before `benchmark.run.completed` and the result notice.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract benchmark`.

- `tests/simorgh/benchmark/test_service_flow.py` -- end to end over a bus: one task per case, scoring, skips, and the Service's request/reply wiring
- `tests/simorgh/benchmark/test_scoring.py` -- GAIA quasi-exact match and BFCL call match
- `tests/simorgh/benchmark/test_swebench.py` -- the SWE-bench log parsers and judge, and what they refuse to guess
- `tests/simorgh/benchmark/test_a_case_that_never_started_is_not_an_answer.py` -- queue time is not answer time; never-started is skipped
- `tests/simorgh/benchmark/test_a_floor_reply_is_not_an_answer.py` -- a floor-answered case is skipped and retried
- `tests/simorgh/benchmark/test_api.py` -- a stored summary recomputes its own totals truthfully
- `tests/simorgh/benchmark/test_cli_and_web.py` -- the `benchmark` command's parsing and rendering, and the dashboard payload shape
- `tests/simorgh/benchmark/test_checkout_manifest.py` -- the `ContainerCheckout` manifest derived from the eval script

## Known issues (2026-09-18 evaluation)

No catalogue id names this package directly. Related:

- P6 -- there is no regression benchmark for the daily path (chat/voice latency, prompt size, memory block); this package measures task suites only (open, stage 4 evals).
- T6 -- the evaluation's nine-day ledger window is dominated by dashboard and benchmark traffic, which skews "tool never called" counts.
- `concurrency` is a declared key nothing reads.

## Planned changes (roadmap)

- Stage 2: BFCL and BFCL-parallel are run through this package on the live model (3 repeats) before native tool use lands; that score is the number to beat.
- Stage 4 item 6: budgets in tokens/USD/wall-clock; benchmark results are part of its acceptance.
- Stage 4 item 9: this package merges with `tools/trial.py`, `tools/trial_suite.py`, `tools/observer_kit.py` and `tools/bench_instance.py` into `simorgh/evals/`, with household, conversation, tool-use (BFCL), research (GAIA), code (SWE-bench Verified slice), long-task and voice suites, >= 3 repeats with a bootstrap CI, floor-answered cases skipped, a replay tier, and `simloader.py bless` running the suite.
- Stage 7: "step budget exhausted", the leading benchmark failure, is addressed by long-horizon planning.
- Stage 8 item 8: the nightly growth loop runs evals and benchmarks on `system.tick.sleep` under a daily cost cap.

## Working on this module

Lock it first (`python tools/modlock.py claim benchmark --by <you> --task "..."`), commit the lock, edit only `simorgh/benchmark/`, `tests/simorgh/benchmark/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py benchmark` before committing; commit subject `benchmark: <what changed>`.
