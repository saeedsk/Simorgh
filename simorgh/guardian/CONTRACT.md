# guardian -- contract

One-line status: layer 3 · 1,929 lines · 12 test files · lock: `guardian` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/guardian/__init__.py` | TODO |
| `simorgh/guardian/api.py` | TODO |
| `simorgh/guardian/charter.py` | TODO |
| `simorgh/guardian/config.py` | TODO |
| `simorgh/guardian/pipeline.py` | TODO |
| `simorgh/guardian/posture.py` | TODO |
| `simorgh/guardian/rules.py` | TODO |
| `simorgh/guardian/service.py` | TODO |
| `simorgh/guardian/tokens.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/guardian/service.py | TODO |
| `cognition.provider.status` | `messages/cognition.py::CognitionProviderStatus` | simorgh/guardian/service.py | TODO |
| `guardian.posture.reply` | `messages/guardian.py::GuardianPostureReply` | simorgh/guardian/service.py | TODO |
| `guardian.posture.request` | `messages/guardian.py::GuardianPostureRequest` | simorgh/guardian/service.py | TODO |
| `guardian.review` | `messages/guardian.py::GuardianReview` | simorgh/guardian/service.py | TODO |
| `reflect.drift.detected` | `messages/reflect.py::ReflectDriftDetected` | simorgh/guardian/service.py | TODO |
| `reflect.health.finding` | `messages/reflect.py::ReflectHealthFinding` | simorgh/guardian/service.py | TODO |
| `system.resume` | `messages/system.py::SystemResume` | simorgh/guardian/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/guardian/service.py | TODO |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/guardian/service.py | TODO |
| `task.created` | `messages/task.py::TaskCreated` | simorgh/guardian/service.py | TODO |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/guardian/service.py | TODO |
| `ui.prompt` | `messages/ui.py::UiPrompt` | simorgh/guardian/service.py | TODO |
| `ui.prompt.answered` | `messages/ui.py::UiPromptAnswered` | simorgh/guardian/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `action.approved` | `messages/action.py::ActionApproved` | simorgh/guardian/service.py | TODO |
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/guardian/service.py | TODO |
| `action.needs_human` | `messages/action.py::ActionNeedsHuman` | simorgh/guardian/service.py | TODO |
| `guardian.posture.changed` | `messages/guardian.py::GuardianPostureChanged` | simorgh/guardian/service.py | TODO |
| `guardian.posture.reply` | `messages/guardian.py::GuardianPostureReply` | simorgh/guardian/service.py | TODO |
| `guardian.review.reply` | `messages/guardian.py::GuardianReviewReply` | simorgh/guardian/service.py | TODO |
| `ui.prompt` | `messages/ui.py::UiPrompt` | simorgh/guardian/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `action:{action_id}` | simorgh/guardian/service.py | simorgh/cognition/compaction.py, simorgh/cognition/config.py, simorgh/execution/render.py, simorgh/execution/service.py, simorgh/execution/verifier.py, simorgh/interface/benchmarkchart.py, simorgh/ledger/compaction.py, simorgh/ledger/service.py, simorgh/ledger/streams.py, simorgh/verification/config.py, simorgh/verification/service.py, simorgh/verification/verdict.py, simorgh/voice/service.py | see ledger/compaction.py DEFAULT_RETENTION |
| `guardian:rejected` | simorgh/guardian/service.py | simorgh/ledger/compaction.py, simorgh/ledger/migrate_v1.py | see ledger/compaction.py DEFAULT_RETENTION |
| `guardian:trust` | simorgh/guardian/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[guardian]` in simorgh.toml; dataclass in `simorgh/guardian/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `mode` | `'guarded'` | yes |
| `baseline_posture` | `'guarded'` | yes |
| `approval_ttl_s` | `120.0` | yes |
| `protected_subjects` | `DEFAULT_PROTECTED_SUBJECTS` | yes |
| `denylist` | `field(default_factory=lambda: dict(DEFAULT_DENYLIST))` | yes |
| `immunity_similarity_threshold` | `0.85` | yes |
| `max_consecutive_failures` | `15` | yes |
| `health_critical_tightens_to` | `'guarded'` | yes |
| `lock_ttl_s` | `600.0` | yes |
| `budget_pressure_tighten_at` | `0.9` | yes |
| `irreversible_requires_human` | `True` | yes |
| `reversible_auto_in_guarded` | `True` | NO (declared, never read) |
| `physical_auto_approve` | `False` | yes |
| `physical_tool_prefixes` | `('cam_', 'ring_', 'cast_', 'tv_', 'home_', 'media_', 'music_` | yes |
| `physical_observe_tools` | `('cam_list', 'cam_state', 'cam_snapshot', 'cam_recordings', ` | yes |
| `physical_always_human_tools` | `('cam_siren', 'ring_siren', 'cam_setup', 'ring_setup', 'cast` | yes |
| `classifier_enabled` | `False` | yes |
| `classifier_timeout_s` | `3.0` | NO (declared, never read) |
| `human_prompt_timeout_s` | `1800.0` | yes |
| `autonomous_origins` | `('curiosity', 'reflection', 'research', 'project', 'assistan` | yes |
| `static_analysis_enabled` | `True` | yes |
| `static_analysis_min_severity` | `'HIGH'` | yes |
| `static_analysis_timeout_s` | `20.0` | yes |
| `shellcheck_enabled` | `True` | yes |
| `shellcheck_timeout_s` | `10.0` | yes |
| `package_denylist` | `('(?i)^sudo', '(?i)^pip$', '(?i)^setuptools$')` | yes |
| `grant_import_denylist` | `('os', 'sys', 'subprocess', 'shutil', 'socket', 'ctypes', 'i` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract guardian`.

- `tests/simorgh/guardian/test_charter.py` -- TODO: what it pins
- `tests/simorgh/guardian/test_code_payload_paths.py` -- TODO: what it pins
- `tests/simorgh/guardian/test_config.py` -- TODO: what it pins
- `tests/simorgh/guardian/test_physical_rule.py` -- TODO: what it pins
- `tests/simorgh/guardian/test_pipeline.py` -- TODO: what it pins
- `tests/simorgh/guardian/test_plan_mode_allows_reading.py` -- TODO: what it pins
- `tests/simorgh/guardian/test_posture.py` -- TODO: what it pins
- `tests/simorgh/guardian/test_review.py` -- TODO: what it pins
- `tests/simorgh/guardian/test_rules.py` -- TODO: what it pins
- `tests/simorgh/guardian/test_service.py` -- TODO: what it pins
- `tests/simorgh/guardian/test_the_question_says_what_it_approves.py` -- TODO: what it pins
- `tests/simorgh/guardian/test_tokens.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim guardian --by <you> --task "..."`), commit the lock, edit only `simorgh/guardian/`, `tests/simorgh/guardian/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py guardian` before committing; commit subject `guardian: <what changed>`.

This package is Guardian-protected: Sim's own tasks cannot edit it. A human-run agent may, with the lock, because a person is accountable for the commit.
