# verification -- contract

One-line status: layer 3 · 3,153 lines · 18 test files · lock: `verification` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/verification/__init__.py` | TODO |
| `simorgh/verification/api.py` | TODO |
| `simorgh/verification/checklist.py` | TODO |
| `simorgh/verification/checks/__init__.py` | TODO |
| `simorgh/verification/checks/_baseline.py` | TODO |
| `simorgh/verification/checks/_files.py` | TODO |
| `simorgh/verification/checks/denylist_immunity.py` | TODO |
| `simorgh/verification/checks/didanything.py` | TODO |
| `simorgh/verification/checks/docstring.py` | TODO |
| `simorgh/verification/checks/fullsuiteran.py` | TODO |
| `simorgh/verification/checks/invariants.py` | TODO |
| `simorgh/verification/checks/isolated_suite.py` | TODO |
| `simorgh/verification/checks/js_syntax.py` | TODO |
| `simorgh/verification/checks/render.py` | TODO |
| `simorgh/verification/checks/sandbox_smoke.py` | TODO |
| `simorgh/verification/checks/syntax.py` | TODO |
| `simorgh/verification/checks/trailing_narration.py` | TODO |
| `simorgh/verification/config.py` | TODO |
| `simorgh/verification/parsing.py` | TODO |
| `simorgh/verification/planreview.py` | TODO |
| `simorgh/verification/rigor.py` | TODO |
| `simorgh/verification/service.py` | TODO |
| `simorgh/verification/trajectory.py` | TODO |
| `simorgh/verification/verdict.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/verification/service.py | TODO |
| `action.result` | `messages/action.py::ActionResult` | simorgh/verification/service.py | TODO |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/verification/service.py | TODO |
| `guardian.review` | `messages/guardian.py::GuardianReview` | simorgh/verification/service.py | TODO |
| `plan.proposed` | `messages/plan.py::PlanProposed` | simorgh/verification/service.py | TODO |
| `plan.reviewed` | `messages/plan.py::PlanReviewed` | simorgh/verification/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/verification/service.py | TODO |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/verification/service.py | TODO |
| `verify.requested` | `messages/verify.py::VerifyRequested` | simorgh/verification/service.py | TODO |
| `verify.result` | `messages/verify.py::VerifyResult` | simorgh/verification/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/verification/service.py | TODO |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/verification/service.py | TODO |
| `guardian.review` | `messages/guardian.py::GuardianReview` | simorgh/verification/service.py | TODO |
| `plan.proposed` | `messages/plan.py::PlanProposed` | simorgh/verification/service.py | TODO |
| `plan.reviewed` | `messages/plan.py::PlanReviewed` | simorgh/verification/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/verification/service.py | TODO |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/verification/service.py | TODO |
| `verify.requested` | `messages/verify.py::VerifyRequested` | simorgh/verification/service.py | TODO |
| `verify.result` | `messages/verify.py::VerifyResult` | simorgh/verification/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `denied:` | simorgh/verification/verdict.py | simorgh/curiosity/interests.py, simorgh/execution/service.py, simorgh/guardian/rules.py, simorgh/guardian/service.py, simorgh/interface/httpapi.py, simorgh/orchestration/api.py, simorgh/orchestration/session.py | see ledger/compaction.py DEFAULT_RETENTION |
| `error:` | simorgh/verification/checks/render.py | simorgh/benchmark/api.py, simorgh/benchmark/runner.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/backends/sqlite.py, simorgh/bus/client.py, simorgh/bus/factory.py, simorgh/cognition/providers/claude_code.py, simorgh/cognition/providers/gemini.py, simorgh/cognition/providers/ollama.py, simorgh/cognition/router.py, simorgh/contracts/messages/cognition.py, simorgh/contracts/protocols.py, simorgh/contracts/registry.py, simorgh/execution/capabilities.py, simorgh/execution/knowledge/tools.py, simorgh/execution/pim/connectors/fakes.py, simorgh/execution/render.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/interface/dashfeeds.py, simorgh/interface/dispatch.py, simorgh/kernel/cli.py, simorgh/kernel/vault.py, simorgh/ledger/client.py, simorgh/ledger/service.py, simorgh/orchestration/api.py, simorgh/orchestration/context.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/session.py, simorgh/voice/delivery.py, simorgh/voice/planner.py, simorgh/voice/session.py, simorgh/voice/tts/streaming.py, simorgh/voice/tts/subproc.py | see ledger/compaction.py DEFAULT_RETENTION |
| `no:cacheprovider` | simorgh/verification/checks/_baseline.py | simorgh/execution/tools.py | see ledger/compaction.py DEFAULT_RETENTION |
| `run_shell:git` | simorgh/verification/checks/didanything.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `run_shell:{program_name}` | simorgh/verification/checks/didanything.py | simorgh/benchmark/swebench.py, simorgh/execution/script.py, simorgh/execution/shell.py, simorgh/execution/writewatch.py, simorgh/guardian/rules.py | see ledger/compaction.py DEFAULT_RETENTION |
| `task:{task_id}` | simorgh/verification/service.py, simorgh/verification/trajectory.py | simorgh/benchmark/runner.py, simorgh/benchmark/service.py, simorgh/bus/backends/aws.py, simorgh/bus/backends/memory.py, simorgh/bus/trace.py, simorgh/contracts/toolargs.py, simorgh/execution/home/ring.py, simorgh/execution/service.py, simorgh/execution/tools.py, simorgh/execution/worktree.py, simorgh/interface/dashfeeds.py, simorgh/interface/httpapi.py, simorgh/interface/panel.py, simorgh/interface/render.py, simorgh/interface/service.py, simorgh/interface/telegram.py, simorgh/kernel/api.py, simorgh/kernel/metrics.py, simorgh/kernel/supervisor.py, simorgh/learning/outcomes.py, simorgh/ledger/client.py, simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py, simorgh/ledger/streams.py, simorgh/orchestration/context.py, simorgh/orchestration/profiles.py, simorgh/orchestration/progress.py, simorgh/orchestration/resume.py, simorgh/orchestration/scaffolds.py, simorgh/orchestration/service.py, simorgh/orchestration/session.py, simorgh/orchestration/tools.py, simorgh/orchestration/worker.py, simorgh/planning/api.py, simorgh/planning/dag.py, simorgh/planning/intake.py, simorgh/planning/scheduler.py, simorgh/planning/service.py, simorgh/planning/store.py, simorgh/reflection/service.py, simorgh/voice/service.py, simorgh/voice/session.py | see ledger/compaction.py DEFAULT_RETENTION |
| `verification:{action_id}` | simorgh/verification/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `verify:{verification_id}` | simorgh/verification/service.py | simorgh/ledger/compaction.py, simorgh/ledger/streams.py, simorgh/orchestration/api.py, simorgh/orchestration/profiles.py, simorgh/orchestration/session.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[verification]` in simorgh.toml; dataclass in `simorgh/verification/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `rigor_by_kind` | `field(default_factory=lambda: {k: _rigor(v) for k, v in _DEF` | yes |
| `rigor_by_reversibility` | `field(default_factory=lambda: {k: _rigor(v) for k, v in _DEF` | yes |
| `checklist_max_items` | `6` | yes |
| `checklist_min_answered_fraction` | `0.67` | yes |
| `docstring_min_chars_to_protect` | `80` | yes |
| `docstring_shrink_threshold` | `0.3` | yes |
| `invariants` | `field(default_factory=lambda: dict(_DEFAULT_INVARIANTS))` | yes |
| `test_suite_require_count_not_below_baseline` | `True` | yes |
| `sandbox_smoke_kinds` | `('skill',)` | yes |
| `trajectory_wasted_step_ratio_warn` | `0.5` | NO (declared, never read) |
| `review_require_real_provider` | `True` | NO (declared, never read) |
| `plan_review_max_steps` | `8` | yes |
| `action_timeout_seconds` | `5.0` | yes |
| `think_timeout_seconds` | `200.0` | yes |
| `isolated_suite_timeout_seconds` | `120.0` | yes |
| `max_denied_actions` | `2` | yes |
| `forced_rigor` | `None` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract verification`.

- `tests/simorgh/verification/checks/test_nonpython_checks.py` -- TODO: what it pins
- `tests/simorgh/verification/test_a_reviewer_cannot_be_talked_past.py` -- TODO: what it pins
- `tests/simorgh/verification/test_checklist.py` -- TODO: what it pins
- `tests/simorgh/verification/test_checks.py` -- TODO: what it pins
- `tests/simorgh/verification/test_container_run_covers_the_change.py` -- TODO: what it pins
- `tests/simorgh/verification/test_did_anything.py` -- TODO: what it pins
- `tests/simorgh/verification/test_docstring.py` -- TODO: what it pins
- `tests/simorgh/verification/test_files_follow_the_repo_root.py` -- TODO: what it pins
- `tests/simorgh/verification/test_full_suite_ran.py` -- TODO: what it pins
- `tests/simorgh/verification/test_invariants.py` -- TODO: what it pins
- `tests/simorgh/verification/test_parsing.py` -- TODO: what it pins
- `tests/simorgh/verification/test_planreview.py` -- TODO: what it pins
- `tests/simorgh/verification/test_red_suite_attribution.py` -- TODO: what it pins
- `tests/simorgh/verification/test_replace_in_file_is_a_write.py` -- TODO: what it pins
- `tests/simorgh/verification/test_rigor.py` -- TODO: what it pins
- `tests/simorgh/verification/test_the_reviewer_still_could_be_talked_past.py` -- TODO: what it pins
- `tests/simorgh/verification/test_trajectory.py` -- TODO: what it pins
- `tests/simorgh/verification/test_verdict.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim verification --by <you> --task "..."`), commit the lock, edit only `simorgh/verification/`, `tests/simorgh/verification/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py verification` before committing; commit subject `verification: <what changed>`.
