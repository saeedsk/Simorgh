# curiosity -- contract

One-line status: layer 4 · 1,433 lines · 9 test files · lock: `curiosity` in docs/modules/locks.toml

## Purpose

Curiosity owns Sim's self-directed exploration: when the system is idle and the backlog is empty, it picks a target area and module by drive-weighted random sampling, asks the model for one narrow idea about that exact target, and publishes it as a `curiosity.candidate` (Planning turns it into a task). It also, rarely, proposes an open-ended project (`intent.goal.stated`), tracks interests and polls their RSS/Atom feeds, and decides when a growth or news item is worth sharing (Persona phrases it). It must never create tasks itself, never read another subsystem's ledger streams (it keeps its own projections from bus events, `projections.py`), never fetch the network directly (feed polls go out as `action.proposed{tool: web_fetch}` through Guardian), and never let the model choose its own target. That last rule is the shaping decision: sample first, by weighted randomness over a real inventory, then ask the model; softmax, never argmax (`sampler.py`, `idea.py`), because an open "propose an improvement" question collapses onto the same few ideas.

## Files

| File | For |
|---|---|
| `simorgh/curiosity/__init__.py` | re-exports `Service` |
| `simorgh/curiosity/api.py` | internal working types (`Area`, `Gap`, `Target`, `Idea`, `DriveContext`, `Interest`, `ShareDecision`) and Protocols; nothing on the wire |
| `simorgh/curiosity/config.py` | frozen `Config`, `drive_weights`, `from_mapping` for `[curiosity]` |
| `simorgh/curiosity/drives.py` | `DriveEngine`: per-area scores from gap, staleness, interest and boredom; mood -> temperature and research bias |
| `simorgh/curiosity/idea.py` | `TargetedIdeaProposer`: one think per target, parses only PATCH/RESEARCH + description |
| `simorgh/curiosity/interests.py` | `InterestService` (score, decay, follow-up cooldown) and the stdlib RSS/Atom parser |
| `simorgh/curiosity/projections.py` | in-memory backlog counter, area staleness, active-project flag, recent-candidate dedupe |
| `simorgh/curiosity/projectproposal.py` | `OpenEndedProjectProposer`: the rare model-chosen project goal |
| `simorgh/curiosity/sampler.py` | `DriveWeightedSampler`: two-stage softmax pick (area, then module) avoiding recent subjects |
| `simorgh/curiosity/service.py` | the `Service`: subscriptions, the exploration tick, feed follow-ups, sharing, ledger appends |
| `simorgh/curiosity/sharing.py` | `ShareScheduler`: growth-before-news share decision with cooldowns |

## Consumes

Exact subscription list: `_CONSUMES` (`service.py:31-38`), plus `system.tick.second`, which is subscribed through the handler dict (`service.py:143`) but missing from `_CONSUMES`; the manifest test's regex only sees `subscribe(topics.X`, so it does not catch this.

| Topic | Schema | Where | Does |
|---|---|---|---|
| `system.tick.idle` | `messages/system.py::SystemTickIdle` | simorgh/curiosity/service.py | runs one exploration tick (guarded), then maybe proposes a share |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/curiosity/service.py | every 30th tick publishes a `system.metrics` gauge of interest count (undeclared) |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/curiosity/service.py | decays interest scores by the elapsed window |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/curiosity/service.py | tracks system state and `autonomous_paused` (`auto off`/`auto on`) |
| `task.created` | `messages/task.py::TaskCreated` | simorgh/curiosity/service.py | backlog count up; remembers subject; a `project` task confirms the active project |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/curiosity/service.py | backlog count down; touches the subject's area staleness |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/curiosity/service.py | backlog count down when terminal |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/curiosity/service.py | parks the task in the backlog until `retry_after` |
| `project.completed` | `messages/plan.py::ProjectCompleted` | simorgh/curiosity/service.py | clears the active-project flag |
| `project.failed` | `messages/plan.py::ProjectFailed` | simorgh/curiosity/service.py | clears the active-project flag |
| `learn.self_patch.applied` | `messages/learn.py::LearnSelfPatchApplied` | simorgh/curiosity/service.py | offers a growth share; touches the subject's staleness |
| `learn.skill.acquired` | `messages/learn.py::LearnSkillAcquired` | simorgh/curiosity/service.py | offers a growth share |
| `cognition.provider.status` | `messages/cognition.py::CognitionProviderStatus` | simorgh/curiosity/service.py | folds the worst remaining budget fraction for the exploration throttle |
| `persona.state.changed` | `messages/persona.py::PersonaStateChanged` | simorgh/curiosity/service.py | keeps valence/arousal for sampling temperature and research bias |
| `action.result` | `messages/action.py::ActionResult` | simorgh/curiosity/service.py | completes a pending feed `web_fetch`: parse items, store memories, offer news |
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/curiosity/service.py | completes a pending feed `web_fetch` as denied |
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | simorgh/curiosity/service.py | `command` channel only: `interest <x>`, `interests`/`curious`, `news`, `growth` |
| `curiosity.discover.request` | `messages/curiosity.py::CuriosityDiscoverRequest` | simorgh/curiosity/service.py | forced tick (bypasses pause, autonomy, backlog, cooldown, budget); replies with created ids |
| `curiosity.share.request` | `messages/curiosity.py::CuriosityShareRequest` | simorgh/curiosity/service.py | shares now if the scheduler's next decision is of the asked kind; replies |
| `curiosity.interest.add` | `messages/curiosity.py::CuriosityInterestAdd` | simorgh/curiosity/service.py | notes a topic or feed URL (published by Interface) |
| `curiosity.interest.list.request` | `messages/curiosity.py::CuriosityInterestListRequest` | simorgh/curiosity/service.py | replies with interests, scores, last follow-up |
| `curiosity.interest.follow_up.request` | `messages/curiosity.py::CuriosityInterestFollowUpRequest` | simorgh/curiosity/service.py | proposes a feed fetch; replies `items_found: 0` always, because nothing has been read yet: the real count arrives later on `curiosity.interest.updated` after `action.result` |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `curiosity.candidate` | `messages/curiosity.py::CuriosityCandidate` | simorgh/curiosity/service.py | an exploration tick yields a non-duplicate idea for a sampled target (consumed by Planning); `novelty_score` is 1 minus the closest `difflib` ratio to a recent candidate's description (1.0 when none is recent; always above 1 - 0.6, since similar ones are dropped) |
| `intent.goal.stated` | `messages/intent.py::IntentGoalStated` | simorgh/curiosity/service.py | a project proposal succeeds (`origin: curiosity`, `wants_project: true`) |
| `curiosity.share.proposed` | `messages/curiosity.py::CuriosityShareProposed` | simorgh/curiosity/service.py | the share scheduler says it is time (idle tick, command or request; consumed by Persona) |
| `curiosity.interest.updated` | `messages/curiosity.py::CuriosityInterestUpdated` | simorgh/curiosity/service.py | a feed follow-up completes or is denied (allow-listed one-sided: dashboard) |
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/curiosity/service.py | an interest follow-up: `web_fetch`, `read_only`, network scope |
| `memory.store` | `messages/memory.py::MemoryStore` | simorgh/curiosity/service.py | one `semantic` memory per parsed feed item, tagged `news` |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/curiosity/service.py | every 30th `system.tick.second`: `gauges.interests` |
| `curiosity.discover.reply` | `messages/curiosity.py::CuriosityDiscoverReply` | simorgh/curiosity/service.py | reply to a discover request |
| `curiosity.share.reply` | `messages/curiosity.py::CuriosityShareReply` | simorgh/curiosity/service.py | reply to a share request |
| `curiosity.interest.list.reply` | `messages/curiosity.py::CuriosityInterestListReply` | simorgh/curiosity/service.py | reply to a list request |
| `curiosity.interest.follow_up.reply` | `messages/curiosity.py::CuriosityInterestFollowUpReply` | simorgh/curiosity/service.py | reply to a follow-up request |
| `world.env.query` | `messages/world.py::WorldEnvQuery` | simorgh/curiosity/service.py | request: `capability_map` and `file_index` for sampling, previews and project proposals (not in `_PRODUCES`) |
| `self.gaps` | `messages/self_.py::SelfGaps` | simorgh/curiosity/service.py | request: the k weakest task types for the gap drive (not in `_PRODUCES`) |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/curiosity/service.py | request: one idea per target, or one project goal (not in `_PRODUCES`) |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `curiosity:ticks` | simorgh/curiosity/service.py | - (named in ledger/compaction.py for retention) | 7d |
| `curiosity:candidates` | simorgh/curiosity/service.py | - | forever (no `DEFAULT_RETENTION` entry) |
| `curiosity:interests` | simorgh/curiosity/service.py | simorgh/ledger/migrate_v1.py (writes v1 interests into it) | forever |
| `curiosity:projects` | simorgh/curiosity/service.py | - | forever |
| `curiosity:shares` | simorgh/curiosity/service.py | - | forever |

All five are write-only from Curiosity's side: interests, backlog, staleness and recent candidates live in memory and restart empty (default feeds are re-seeded at start, `service.py:138-140`), so a tracked interest added at runtime does not survive a restart.

## Config

`[curiosity]` in simorgh.toml; dataclass in `simorgh/curiosity/config.py`. `from_mapping` keeps only known field names, so an unknown or misspelt key is dropped silently; `[curiosity.focus]` is an area -> multiplier table. An explicitly constructed `Config` wins over `ctx.config`.

| Key | Default | Read in the package |
|---|---|---|
| `candidates_per_tick` | `2` | yes |
| `recent_subjects` | `30` | yes |
| `drive_gap` | `0.45` | yes (via `Config.drive_weights`, `drives.py:24`) |
| `drive_staleness` | `0.3` | yes (via `Config.drive_weights`, `drives.py:24`) |
| `drive_interest` | `0.15` | yes (via `Config.drive_weights`, `drives.py:24`) |
| `drive_boredom` | `0.1` | yes (via `Config.drive_weights`, `drives.py:24`) |
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

- `simorgh.curiosity.Service` (`name = "curiosity"`, keyword-only `config`, `seed` for the sampler RNG): the Subsystem; `health()` is always `ok`.
- `Config` (`config.py`), read by the Kernel's config check.
- Nothing is exported through `simorgh.contracts`; `api.py` types are package-internal.
- No module-level mutable singletons. Per-instance state worth knowing: `_pending_web_fetches` (action_id -> feed) grows if a proposed fetch never gets a result or denial; `_task_subjects` likewise for tasks that never terminate.

## Invariants

- Every subscription is declared in `Service.consumes` (`tests/simorgh/test_manifests_match_the_code.py`; today violated for `system.tick.second`, which the test's regex cannot see, see Consumes).
- Curiosity never subscribes to `action.proposed`/`action.approved` and never publishes `action.approved`, `action.denied`, `self.model.updated` or `plan.proposed` (`contracts/topics.py`; no policy entry names Curiosity itself).
- Every `action.proposed` it publishes is `tool: web_fetch`, `reversibility: read_only`, `proposed_by: curiosity`, for a URL that `is_feed_url` accepted; it never constructs a feed URL from a topic word.
- At most one exploration tick runs at a time; an idle tick that arrives while one is running is skipped and recorded, never queued.
- A non-forced tick is skipped when the system is paused/stopping, autonomy is paused, the backlog is non-empty, the explore cooldown has not elapsed, or the budget rate is 0; a `curiosity.discover.request` bypasses all of these.
- A skipped tick does not start the explore cooldown; the ticks stream records a skip reason only on the edge (a repeat of the same reason is not appended).
- The candidate's `subject` is always the sampler's target; the model's reply cannot redirect it.
- A candidate whose description is similar to a recent one is dropped, not published; a published one carries its measured `novelty_score` (`RecentCandidates.novelty`, pinned in `tests/simorgh/curiosity/test_service.py::test_candidate_novelty_is_measured_against_recent_candidates`).
- Exploration rate: 1.0 when budget is unknown, 0.5 at or below `budget_backoff_below_remaining`, 0 at or below `budget_stop_below_remaining`; a provider with no cap does not count.
- World Model absent: the tick records `no_world_model` and does not raise. A floor (non-model) Cognition reply yields no idea and no candidate (`idea.py:79-80`).
- Stage 8 merges this package into `growth/`; every `curiosity.*` topic keeps both its sides through the merge.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract curiosity`.

- `tests/simorgh/curiosity/test_service.py` -- the real Service on a real bus: tick guards, cooldown, discover/share/interest request-replies, feed follow-up via `action.proposed`/`action.result`, config reaching live objects
- `tests/simorgh/integration/test_curiosity_repetition_regression.py` -- sampling spreads across every module before repeating (the reason the package exists)
- `tests/simorgh/curiosity/test_sampler.py` -- softmax temperature behaviour, recent-subject avoidance, focus multipliers
- `tests/simorgh/curiosity/test_idea.py` -- the idea parser never takes a target path from the model
- `tests/simorgh/curiosity/test_interests.py` -- feed URL detection, RSS/Atom parsing, interest scoring and decay
- `tests/simorgh/curiosity/test_sharing.py` -- growth before news, cooldowns
- `tests/simorgh/curiosity/test_config.py` -- drive weights normalise; `from_mapping` overrides known keys, ignores unknown ones, parses `focus` and default topics

## Known issues (2026-09-18 evaluation)

- C1 -- `learn.self_patch.applied` had no real publisher, so growth shares never fired from landings; fixed 2026-09-18 (`1e486f1`).
- C4 -- a paused Curiosity appended `autonomy_paused` every 3 s (161k events, 45 MB); fixed 2026-09-18 (`62318d3`: edge-triggered record, and `curiosity:ticks` retention 7d). No test in `tests/simorgh/curiosity/` pins the edge trigger yet.
- C9 -- the budget throttle read fields Cognition never sends, so it never throttled; fixed 2026-09-18 (`62318d3`). No consumer-side test pins the field names yet.
- Found writing this contract, fixed 2026-09-19: `novelty_score` was always 1.0 (computed after the similarity filter had already dropped the similar ones); `_BudgetState.any_free` was never set after the C9 fix and was deleted; the follow-up request handler computed an unused interest and a return value that was always 0, both removed.
- C14 -- the drives cost health noise without producing decisions; candidate sampling is the part that changes behaviour (open, stage 8).

## Planned changes (roadmap)

- Stage 6 item 2: the gap drive reads a real `self.gaps` (posterior-based) from the new Self Model.
- Stage 6 item 6: `curiosity/sharing.py` moves into the new `initiative/` module (one proactive-delivery policy with Persona's sharing and reminders).
- Stage 8 item 1: Curiosity, Reflection and Learning merge into `simorgh/growth/`; `sampler.py` moves verbatim; every `curiosity.*` topic is still published.
- Stage 8 item 7: exploration becomes Thompson sampling over posteriors and world-model unknowns, keeping the sampler's diversity; targets extend beyond repo areas (unanswered questions, stale facts, unprobed devices, unexercised skills). The sampler regression test must stay unchanged.

## Working on this module

Lock it first (`python tools/modlock.py claim curiosity --by <you> --task "..."`), commit the lock, edit only `simorgh/curiosity/`, `tests/simorgh/curiosity/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py curiosity` before committing; commit subject `curiosity: <what changed>`.
