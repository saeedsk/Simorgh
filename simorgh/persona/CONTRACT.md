# persona -- contract

One-line status: layer 5 · 806 lines · 4 test files · lock: `persona` in docs/modules/locks.toml

## Purpose

Persona owns Sim's continuous mood (valence, arousal, cognitive load), the rule-based emotion floor that moves it, the identity-plus-mood "voice" block Cognition puts in prompts, and a narrow regex user model ("call me X", "I prefer X"). It no longer paces proactive shares: that was a second path for unprompted speech beside Initiative's, and stage 6 item 6 says there is one (removed 2026-09-20 with `sharing.py`, its four `[persona.share]` keys and its subscription). It never calls Cognition and never sits in a model call path: it reacts to bus events and answers `persona.voice` requests, so it keeps working with every provider down (`service.py:1-5`, `emotion.py`). It is the single writer of `persona:state` and restores mood from it at start, decayed forward by the time the process was down (`service.py:131-181`). The shaping decision is that mood is cheap deterministic arithmetic on an injected clock, announced on the bus only when it has really moved: a delta below 1e-4 is dropped, and decay is announced only after drifting `decay_announce_delta` from the last announced state (V6).

## Files

| File | For |
|---|---|
| `simorgh/persona/__init__.py` | empty package marker |
| `simorgh/persona/api.py` | re-exports the pure types (`EmotionalState`, `MoodEngine`, `VoiceComposer`, `SharePolicy`, `UserModel`, ...) for tests |
| `simorgh/persona/config.py` | frozen `Config`, `resolved_soul_path`, `from_mapping` for `[persona]` |
| `simorgh/persona/emotion.py` | lexicon-based `react(text)` -> mood delta; no model |
| `simorgh/persona/mood.py` | `EmotionalState` and `MoodEngine`: apply delta, set, decay toward baseline, restore, bounded history |
| `simorgh/persona/service.py` | the `Service`: subscriptions, mood restore, announce-on-change, voice replies |
| `simorgh/persona/sharing.py` | `SharePolicy`: per-kind cooldown, quiet period after user activity, hourly cap |
| `simorgh/persona/user_model.py` | `UserModel`: regex facet extraction with confidence merge, values sanitised for a protected prompt block |
| `simorgh/persona/voice.py` | `mood_phrase` and `VoiceComposer`: identity summary + mood phrase within `voice_max_chars` |

## Consumes

Exact subscription list: `Service.consumes` (`service.py:73-77`).

| Topic | Schema | Where | Does |
|---|---|---|---|
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | simorgh/persona/service.py | notes user activity, applies the lexicon reaction, extracts user-model facets |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/persona/service.py | valence nudge `outcome_nudge_success` |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/persona/service.py | valence nudge `outcome_nudge_failure` |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/persona/service.py | smaller valence nudge `outcome_nudge_blocked` (blocked is retried, not terminal) |
| `reflect.health.finding` | `messages/reflect.py::ReflectHealthFinding` | simorgh/persona/service.py | `critical` + `request_reset` sets mood back to baseline |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/persona/service.py | every `decay_interval_s`, decays mood; announces only past `decay_announce_delta` |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/persona/service.py | suspends sharing unless the state is `running` |
| `persona.voice` | `messages/persona.py::PersonaVoice` | simorgh/persona/service.py | replies with the style block and mood phrase (requested by `cognition/assembler.py`) |
| `ui.prompt.answered` | `messages/ui.py::UiPromptAnswered` | simorgh/persona/service.py | somebody is at the keyboard |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `persona.state.changed` | `messages/persona.py::PersonaStateChanged` | simorgh/persona/service.py | a mood change of at least 1e-4, a health reset, or decay past `decay_announce_delta` (consumed by Reflection, Curiosity, Interface, Voice) |
| `persona.user_model.updated` | `messages/persona.py::PersonaUserModelUpdated` | simorgh/persona/service.py | a facet is extracted from a percept (consumed by World Model) |
| `persona.voice.reply` | `messages/persona.py::PersonaVoiceReply` | simorgh/persona/service.py | reply to `persona.voice` (via `bus.reply`) |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `persona:state` | simorgh/persona/service.py (written on every announce; its last event read back at start) | named in ledger/compaction.py for retention | 7d (keep_tail still leaves the last events for restore) |
| `persona:user_model` | simorgh/persona/service.py | - (write-only; the user model is not restored at start) | forever (no `DEFAULT_RETENTION` entry) |
| `persona:shares` | simorgh/persona/service.py | - | forever |

## Config

`[persona]` in simorgh.toml; dataclass in `simorgh/persona/config.py`. Several keys are nested in the TOML: `[persona.baseline] valence/arousal`, `[persona.outcome_nudge] success/failure/blocked`, `[persona.voice] max_chars` (`config.py:50-77`). An explicitly constructed `Config` wins over `ctx.config`. `[persona.user_model] min_confidence_to_use` (field `user_model_min_confidence`) was removed 2026-09-19: nothing read it (its only reader, `UserModel.register`, had no caller and was removed too); a `[persona]` section holding only that key is now reported by the Kernel's config check as changing nothing. The confidence floor for user facets in prompts is Cognition's own constant (`cognition/assembler.py::_MIN_FACET_CONFIDENCE`).

| Key | Default | Read in the package |
|---|---|---|
| `repo_root` | `Path('.')` | yes (`resolved_soul_path`); the Kernel passes no `default_repo_root`, so it is the working directory unless set |
| `soul_path` | `Path('docs/SOUL.md')` | yes (identity summary at start) |
| `baseline_valence` | `0.0` | yes |
| `baseline_arousal` | `0.0` | yes |
| `decay_half_life_s` | `900.0` | yes |
| `decay_interval_s` | `5.0` | yes |
| `decay_announce_delta` | `0.02` | yes |
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
| `voice_max_chars` | `600` | yes |

## Public Python surface

- `simorgh.persona.service.Service` (`name = "persona"`): the Subsystem; `health()` is `down` before start, `ok` after.
- `simorgh.persona.api` re-exports the pure types; no other package imports them (module boundary), and nothing is exported through `simorgh.contracts`.
- No module-level mutable singletons. `_announced` is set lazily as an instance attribute (`service.py:211, 274`); `_mood`, `_user_model`, `_share_policy`, `_voice` exist only after `start()`.

## Invariants

- Every subscription is declared in `Service.consumes`, and every declared topic is referenced in the package (`tests/simorgh/test_manifests_match_the_code.py`).
- Persona never publishes `cognition.think` and never waits on another subsystem; every handler is local arithmetic plus at most one publish and one ledger append.
- Persona never subscribes to `action.proposed`/`action.approved` and never publishes the topics in `PUBLISH_ONLY_BY` (`contracts/topics.py`; no policy entry names Persona itself).
- Every `persona.state.changed` is also appended to `persona:state`, and Persona is the only writer of that stream.
- A mood change smaller than 1e-4 on every axis is not announced; decay is announced only when valence or arousal has moved at least `decay_announce_delta` from the last announced state.
- After a restart the mood is the last `persona:state` event decayed by the offline time; a missing or unreadable stream is a cold start at the configured baseline, never an error.
- A `reflect.health.finding` resets mood only when `severity == critical` and `action_taken == request_reset`.
- `persona.voice.reply` always contains the mood phrase, even when `voice_max_chars` forces the identity to be trimmed; a missing SOUL.md or `## Identity` heading yields "You are Simorgh."
- A user-model facet value is single-line, bounded and stripped of control characters; a multi-line percept extracts nothing.
- A share is shown at most once per kind cooldown, never within `quiet_when_active_s` of user activity, at most `max_shares_per_hour`, and never while the system is not `running`.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract persona`.

- `tests/simorgh/persona/test_service.py` -- the real Service on a real bus: percept and task nudges, facet extraction, health reset, voice reply, decay, share pacing and suspension
- `tests/simorgh/persona/test_voice_and_continuity.py` -- the voice block keeps the mood phrase and the whole Identity section; mood survives a restart and decays over an outage; facet sanitising
- `tests/simorgh/persona/test_decay_is_announced_on_change.py` -- a slow decay over a hundred ticks is announced a few times, not every tick (V6)
- `tests/simorgh/persona/test_sharing.py` -- hourly cap and pruning of old share times

## Known issues (2026-09-18 evaluation)

- V6 -- mood decay was announced on 93% of 5 s ticks (44,444 of 47,784 `persona:state` events); fixed 2026-09-18 (`aa05475`, `decay_announce_delta`) and `persona:state` given 7d retention (`62318d3`). The other half of V6, a 2 s-timeout bus round trip on every prompt for one sentence (`cognition/assembler.py:54`), is open.

## Planned changes (roadmap)

- Stage 1 (telemetry out of the decision log): `persona.state.changed` spans are sampled at 1/50 in the telemetry store.
- Stage 4 item 4: one `ContextBuilder` in Orchestration renders "persona voice" in a fixed prefix order, the direction V6 names ("persona as an injected reader" instead of a bus request per prompt).
- Stage 5 item 4: `persona/user_model.py`'s regex extraction is retired in favour of entity-linked facts and a per-person digest.
- Stage 6 item 6: `persona/sharing.py` moves into the new `initiative/` module with Curiosity's sharing and reminder delivery.

## Working on this module

Lock it first (`python tools/modlock.py claim persona --by <you> --task "..."`), commit the lock, edit only `simorgh/persona/`, `tests/simorgh/persona/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py persona` before committing; commit subject `persona: <what changed>`.
