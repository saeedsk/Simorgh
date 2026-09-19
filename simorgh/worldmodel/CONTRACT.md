# worldmodel -- contract

One-line status: layer 2 · 1,282 lines · 6 test files · lock: `worldmodel` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/worldmodel/__init__.py` | TODO |
| `simorgh/worldmodel/api.py` | TODO |
| `simorgh/worldmodel/config.py` | TODO |
| `simorgh/worldmodel/facets/__init__.py` | TODO |
| `simorgh/worldmodel/facets/capability_map.py` | TODO |
| `simorgh/worldmodel/facets/file_index.py` | TODO |
| `simorgh/worldmodel/facets/git_state.py` | TODO |
| `simorgh/worldmodel/facets/registry_facets.py` | TODO |
| `simorgh/worldmodel/selfmodel.py` | TODO |
| `simorgh/worldmodel/service.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `cognition.provider.status` | `messages/cognition.py::CognitionProviderStatus` | simorgh/worldmodel/service.py | TODO |
| `learn.competence.updated` | `messages/learn.py::LearnCompetenceUpdated` | simorgh/worldmodel/service.py | TODO |
| `learn.self_patch.applied` | `messages/learn.py::LearnSelfPatchApplied` | simorgh/worldmodel/service.py | TODO |
| `learn.self_patch.reverted` | `messages/learn.py::LearnSelfPatchReverted` | simorgh/worldmodel/service.py | TODO |
| `learn.skill.acquired` | `messages/learn.py::LearnSkillAcquired` | simorgh/worldmodel/service.py | TODO |
| `persona.user_model.updated` | `messages/persona.py::PersonaUserModelUpdated` | simorgh/worldmodel/service.py | TODO |
| `reflect.calibration.updated` | `messages/reflect.py::ReflectCalibrationUpdated` | simorgh/worldmodel/service.py | TODO |
| `self.gaps` | `messages/self_.py::SelfGaps` | simorgh/worldmodel/service.py | TODO |
| `self.gaps.reply` | `messages/self_.py::SelfGapsReply` | simorgh/worldmodel/service.py | TODO |
| `self.observation` | `messages/self_.py::SelfObservation` | simorgh/worldmodel/service.py | TODO |
| `self.summary` | `messages/self_.py::SelfSummary` | simorgh/worldmodel/service.py | TODO |
| `self.summary.reply` | `messages/self_.py::SelfSummaryReply` | simorgh/worldmodel/service.py | TODO |
| `system.started` | `messages/system.py::SystemStarted` | simorgh/worldmodel/service.py | TODO |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/worldmodel/service.py | TODO |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/worldmodel/service.py | TODO |
| `task.created` | `messages/task.py::TaskCreated` | simorgh/worldmodel/service.py | TODO |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/worldmodel/service.py | TODO |
| `tool.probed` | `messages/tool.py::ToolProbed` | simorgh/worldmodel/service.py | TODO |
| `tool.registered` | `messages/tool.py::ToolRegistered` | simorgh/worldmodel/service.py | TODO |
| `tool.unavailable` | `messages/tool.py::ToolUnavailable` | simorgh/worldmodel/service.py | TODO |
| `world.env.query` | `messages/world.py::WorldEnvQuery` | simorgh/worldmodel/service.py | TODO |
| `world.env.query.reply` | `messages/world.py::WorldEnvQueryReply` | simorgh/worldmodel/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `self.gaps.reply` | `messages/self_.py::SelfGapsReply` | simorgh/worldmodel/service.py | TODO |
| `self.model.updated` | `messages/self_.py::SelfModelUpdated` | simorgh/worldmodel/service.py | TODO |
| `self.summary.reply` | `messages/self_.py::SelfSummaryReply` | simorgh/worldmodel/service.py | TODO |
| `system.health` | `messages/system.py::SystemHealth` | simorgh/worldmodel/service.py | TODO |
| `world.env.observed` | `messages/world.py::WorldEnvObserved` | simorgh/worldmodel/service.py | TODO |
| `world.env.query.reply` | `messages/world.py::WorldEnvQueryReply` | simorgh/worldmodel/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|

## Config

`[worldmodel]` in simorgh.toml; dataclass in `simorgh/worldmodel/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `repo_root` | `Path('.')` | yes |
| `file_index_max_files` | `5000` | yes |
| `file_index_refresh_seconds` | `30.0` | yes |
| `git_refresh_seconds` | `60.0` | NO (declared, never read) |
| `soul_path` | `Path('docs/SOUL.md')` | NO (declared, never read) |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract worldmodel`.

- `tests/simorgh/worldmodel/test_capability_map.py` -- TODO: what it pins
- `tests/simorgh/worldmodel/test_file_index_facet.py` -- TODO: what it pins
- `tests/simorgh/worldmodel/test_git_state_facet.py` -- TODO: what it pins
- `tests/simorgh/worldmodel/test_selfmodel.py` -- TODO: what it pins
- `tests/simorgh/worldmodel/test_service.py` -- TODO: what it pins
- `tests/simorgh/worldmodel/test_substrate.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim worldmodel --by <you> --task "..."`), commit the lock, edit only `simorgh/worldmodel/`, `tests/simorgh/worldmodel/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py worldmodel` before committing; commit subject `worldmodel: <what changed>`.
