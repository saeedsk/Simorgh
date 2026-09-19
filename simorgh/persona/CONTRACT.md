# persona -- contract

One-line status: layer 5 · 806 lines · 3 test files · lock: `persona` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/persona/__init__.py` | TODO |
| `simorgh/persona/api.py` | TODO |
| `simorgh/persona/config.py` | TODO |
| `simorgh/persona/emotion.py` | TODO |
| `simorgh/persona/mood.py` | TODO |
| `simorgh/persona/service.py` | TODO |
| `simorgh/persona/sharing.py` | TODO |
| `simorgh/persona/user_model.py` | TODO |
| `simorgh/persona/voice.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `curiosity.share.proposed` | `messages/curiosity.py::CuriosityShareProposed` | simorgh/persona/service.py | TODO |
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | simorgh/persona/service.py | TODO |
| `persona.state.changed` | `messages/persona.py::PersonaStateChanged` | simorgh/persona/service.py | TODO |
| `persona.user_model.updated` | `messages/persona.py::PersonaUserModelUpdated` | simorgh/persona/service.py | TODO |
| `persona.voice` | `messages/persona.py::PersonaVoice` | simorgh/persona/service.py | TODO |
| `persona.voice.reply` | `messages/persona.py::PersonaVoiceReply` | simorgh/persona/service.py | TODO |
| `reflect.health.finding` | `messages/reflect.py::ReflectHealthFinding` | simorgh/persona/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/persona/service.py | TODO |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/persona/service.py | TODO |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/persona/service.py | TODO |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/persona/service.py | TODO |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/persona/service.py | TODO |
| `ui.prompt.answered` | `messages/ui.py::UiPromptAnswered` | simorgh/persona/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `persona.state.changed` | `messages/persona.py::PersonaStateChanged` | simorgh/persona/service.py | TODO |
| `persona.user_model.updated` | `messages/persona.py::PersonaUserModelUpdated` | simorgh/persona/service.py | TODO |
| `persona.voice.reply` | `messages/persona.py::PersonaVoiceReply` | simorgh/persona/service.py | TODO |
| `system.health` | `messages/system.py::SystemHealth` | simorgh/persona/service.py | TODO |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/persona/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `persona:shares` | simorgh/persona/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `persona:state` | simorgh/persona/service.py | simorgh/ledger/compaction.py | see ledger/compaction.py DEFAULT_RETENTION |
| `persona:user_model` | simorgh/persona/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[persona]` in simorgh.toml; dataclass in `simorgh/persona/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `repo_root` | `Path('.')` | NO (declared, never read) |
| `soul_path` | `Path('docs/SOUL.md')` | NO (declared, never read) |
| `baseline_valence` | `0.0` | yes |
| `baseline_arousal` | `0.0` | yes |
| `decay_half_life_s` | `900.0` | yes |
| `decay_interval_s` | `5.0` | yes |
| `history_limit` | `200` | yes |
| `lexicon_weight` | `0.15` | yes |
| `exclamation_arousal` | `0.1` | yes |
| `outcome_nudge_success` | `0.08` | yes |
| `outcome_nudge_failure` | `-0.1` | yes |
| `outcome_nudge_blocked` | `-0.03` | yes |
| `growth_cooldown_s` | `900.0` | yes |
| `news_cooldown_s` | `1800.0` | yes |
| `quiet_when_active_s` | `20.0` | yes |
| `max_shares_per_hour` | `4` | yes |
| `user_model_min_confidence` | `0.5` | NO (declared, never read) |
| `voice_max_chars` | `600` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract persona`.

- `tests/simorgh/persona/test_service.py` -- TODO: what it pins
- `tests/simorgh/persona/test_sharing.py` -- TODO: what it pins
- `tests/simorgh/persona/test_voice_and_continuity.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim persona --by <you> --task "..."`), commit the lock, edit only `simorgh/persona/`, `tests/simorgh/persona/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py persona` before committing; commit subject `persona: <what changed>`.
