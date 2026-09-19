# curiosity -- contract

One-line status: layer 4 · 1,433 lines · 9 test files · lock: `curiosity` in docs/modules/locks.toml

## Purpose

TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.

## Files

| File | For |
|---|---|
| `simorgh/curiosity/__init__.py` | TODO |
| `simorgh/curiosity/api.py` | TODO |
| `simorgh/curiosity/config.py` | TODO |
| `simorgh/curiosity/drives.py` | TODO |
| `simorgh/curiosity/idea.py` | TODO |
| `simorgh/curiosity/interests.py` | TODO |
| `simorgh/curiosity/projections.py` | TODO |
| `simorgh/curiosity/projectproposal.py` | TODO |
| `simorgh/curiosity/sampler.py` | TODO |
| `simorgh/curiosity/service.py` | TODO |
| `simorgh/curiosity/sharing.py` | TODO |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/curiosity/service.py | TODO |
| `action.result` | `messages/action.py::ActionResult` | simorgh/curiosity/service.py | TODO |
| `cognition.provider.status` | `messages/cognition.py::CognitionProviderStatus` | simorgh/curiosity/service.py | TODO |
| `curiosity.discover.reply` | `messages/curiosity.py::CuriosityDiscoverReply` | simorgh/curiosity/service.py | TODO |
| `curiosity.discover.request` | `messages/curiosity.py::CuriosityDiscoverRequest` | simorgh/curiosity/service.py | TODO |
| `curiosity.interest.add` | `messages/curiosity.py::CuriosityInterestAdd` | simorgh/curiosity/service.py | TODO |
| `curiosity.interest.follow_up.request` | `messages/curiosity.py::CuriosityInterestFollowUpRequest` | simorgh/curiosity/service.py | TODO |
| `curiosity.interest.list.reply` | `messages/curiosity.py::CuriosityInterestListReply` | simorgh/curiosity/service.py | TODO |
| `curiosity.interest.list.request` | `messages/curiosity.py::CuriosityInterestListRequest` | simorgh/curiosity/service.py | TODO |
| `curiosity.share.proposed` | `messages/curiosity.py::CuriosityShareProposed` | simorgh/curiosity/service.py | TODO |
| `curiosity.share.request` | `messages/curiosity.py::CuriosityShareRequest` | simorgh/curiosity/service.py | TODO |
| `learn.self_patch.applied` | `messages/learn.py::LearnSelfPatchApplied` | simorgh/curiosity/service.py | TODO |
| `learn.skill.acquired` | `messages/learn.py::LearnSkillAcquired` | simorgh/curiosity/service.py | TODO |
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | simorgh/curiosity/service.py | TODO |
| `persona.state.changed` | `messages/persona.py::PersonaStateChanged` | simorgh/curiosity/service.py | TODO |
| `project.completed` | `messages/plan.py::ProjectCompleted` | simorgh/curiosity/service.py | TODO |
| `project.failed` | `messages/plan.py::ProjectFailed` | simorgh/curiosity/service.py | TODO |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/curiosity/service.py | TODO |
| `system.tick.idle` | `messages/system.py::SystemTickIdle` | simorgh/curiosity/service.py | TODO |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/curiosity/service.py | TODO |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/curiosity/service.py | TODO |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/curiosity/service.py | TODO |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/curiosity/service.py | TODO |
| `task.created` | `messages/task.py::TaskCreated` | simorgh/curiosity/service.py | TODO |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/curiosity/service.py | TODO |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/curiosity/service.py | TODO |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/curiosity/service.py | TODO |
| `curiosity.candidate` | `messages/curiosity.py::CuriosityCandidate` | simorgh/curiosity/service.py | TODO |
| `curiosity.discover.reply` | `messages/curiosity.py::CuriosityDiscoverReply` | simorgh/curiosity/service.py | TODO |
| `curiosity.interest.follow_up.reply` | `messages/curiosity.py::CuriosityInterestFollowUpReply` | simorgh/curiosity/service.py | TODO |
| `curiosity.interest.list.reply` | `messages/curiosity.py::CuriosityInterestListReply` | simorgh/curiosity/service.py | TODO |
| `curiosity.interest.updated` | `messages/curiosity.py::CuriosityInterestUpdated` | simorgh/curiosity/service.py | TODO |
| `curiosity.share.proposed` | `messages/curiosity.py::CuriosityShareProposed` | simorgh/curiosity/service.py | TODO |
| `curiosity.share.reply` | `messages/curiosity.py::CuriosityShareReply` | simorgh/curiosity/service.py | TODO |
| `intent.goal.stated` | `messages/intent.py::IntentGoalStated` | simorgh/curiosity/service.py | TODO |
| `memory.store` | `messages/memory.py::MemoryStore` | simorgh/curiosity/service.py | TODO |
| `self.gaps` | `messages/self_.py::SelfGaps` | simorgh/curiosity/service.py | TODO |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/curiosity/service.py | TODO |
| `world.env.query` | `messages/world.py::WorldEnvQuery` | simorgh/curiosity/service.py | TODO |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `curiosity:candidates` | simorgh/curiosity/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `curiosity:interests` | simorgh/curiosity/service.py | simorgh/ledger/migrate_v1.py | see ledger/compaction.py DEFAULT_RETENTION |
| `curiosity:projects` | simorgh/curiosity/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `curiosity:shares` | simorgh/curiosity/service.py | - | see ledger/compaction.py DEFAULT_RETENTION |
| `curiosity:ticks` | simorgh/curiosity/service.py | simorgh/ledger/compaction.py | see ledger/compaction.py DEFAULT_RETENTION |
| `feed:{topic}` | simorgh/curiosity/service.py | simorgh/interface/dashfeeds.py | see ledger/compaction.py DEFAULT_RETENTION |

## Config

`[curiosity]` in simorgh.toml; dataclass in `simorgh/curiosity/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `candidates_per_tick` | `2` | yes |
| `recent_subjects` | `30` | yes |
| `drive_gap` | `0.45` | NO (declared, never read) |
| `drive_staleness` | `0.3` | NO (declared, never read) |
| `drive_interest` | `0.15` | NO (declared, never read) |
| `drive_boredom` | `0.1` | NO (declared, never read) |
| `temperature` | `0.7` | yes |
| `project_chance` | `0.2` | yes |
| `boredom_after_seconds` | `1800.0` | yes |
| `min_explore_interval_seconds` | `300.0` | yes |
| `autonomy_on_boot` | `True` | yes |
| `staleness_horizon_seconds` | `7 * 86400.0` | yes |
| `budget_backoff_below_remaining` | `0.2` | yes |
| `budget_stop_below_remaining` | `0.05` | yes |
| `interest_follow_up_cooldown_seconds` | `3600.0` | yes |
| `interest_max_items_per_follow_up` | `5` | yes |
| `interest_default_topics` | `field(default_factory=lambda: _DEFAULT_TOPICS)` | yes |
| `share_growth_cooldown_seconds` | `900.0` | yes |
| `share_news_cooldown_seconds` | `1800.0` | yes |
| `mood_arousal_temperature_gain` | `0.2` | yes |
| `world_query_timeout` | `3.0` | yes |
| `cognition_timeout` | `20.0` | yes |
| `active_project_confirm_timeout` | `60.0` | yes |
| `focus` | `field(default_factory=dict)` | yes |

## Public Python surface

TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).

## Invariants

TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract curiosity`.

- `tests/simorgh/curiosity/test_config.py` -- TODO: what it pins
- `tests/simorgh/curiosity/test_drives.py` -- TODO: what it pins
- `tests/simorgh/curiosity/test_idea.py` -- TODO: what it pins
- `tests/simorgh/curiosity/test_interests.py` -- TODO: what it pins
- `tests/simorgh/curiosity/test_projections.py` -- TODO: what it pins
- `tests/simorgh/curiosity/test_projectproposal.py` -- TODO: what it pins
- `tests/simorgh/curiosity/test_sampler.py` -- TODO: what it pins
- `tests/simorgh/curiosity/test_service.py` -- TODO: what it pins
- `tests/simorgh/curiosity/test_sharing.py` -- TODO: what it pins

## Known issues (2026-09-18 evaluation)

TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.

## Planned changes (roadmap)

TODO: stage numbers from docs/plan/ and what changes here.

## Working on this module

Lock it first (`python tools/modlock.py claim curiosity --by <you> --task "..."`), commit the lock, edit only `simorgh/curiosity/`, `tests/simorgh/curiosity/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py curiosity` before committing; commit subject `curiosity: <what changed>`.
