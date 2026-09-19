# learning -- contract

One-line status: layer 4 · 727 lines · 4 test files · lock: `learning` in docs/modules/locks.toml

## Purpose

Learning owns the outcome record and the competence estimate: it turns `task.completed` / `task.failed` / `task.blocked` into one `learn:outcomes` event per run, folds those into `CompetenceTable` (Laplace-smoothed success rate, calibration, strategy ranking), and announces each outcome and the new estimate on the bus. It never acts: it runs no tool, edits no file and changes no config, and its one query answer (`learn.strategy.suggest`) is a pure read of the projection. The shaping decision is that competence is a projection over an append-only stream: `CompetenceTable.apply` does nothing a fresh `rebuild` would not (`competence.py:1-12`), so the table survives restarts by replaying `learn:outcomes` at `start()` (`service.py:72`). The task type is read from the task's own `task:<id>` stream (its `created` event), never guessed from the terminal message (`outcomes.py:1-11`). The self-patch PatchPipeline that used to live here was retired on 2026-09-18 (commit `62318d3`); self-landing now happens in `orchestration/session.py::_land`.

## Files

| File | For |
|---|---|
| `simorgh/learning/__init__.py` | re-exports `Service`, `VERSION` |
| `simorgh/learning/competence.py` | `CompetenceTable`: the projection over `learn:outcomes` (rate, calibration, UCB1 strategy ranking) |
| `simorgh/learning/config.py` | `[learning]` dataclass |
| `simorgh/learning/correlator.py` | id-keyed futures for `action.result` / `verify.result`; a leftover of the retired pipeline, nothing awaits them |
| `simorgh/learning/models.py` | plain dataclasses (`TaskTypeStats`, `StrategyStats`, `StrategyScore`; `Strategy`, `Outcome`, `PatchTaskSpec` unused) |
| `simorgh/learning/outcomes.py` | `OutcomeRecorder`: terminal task messages to `learn:outcomes` events and the two announcements |
| `simorgh/learning/service.py` | `Service`: subscriptions, competence rebuild at start, health |
| `simorgh/learning/strategy.py` | `build_reply`: answers `learn.strategy.suggest` from the table |

`simorgh/learning/README.md` still describes the retired `pipeline.py` and `learn.pipeline.run`; it is stale.

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/learning/service.py | records a success (weight 1.0) with the cached verify verdict; skips untyped turns |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/learning/service.py | records a failure (weight 1.0); skips untyped turns |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/learning/service.py | records a failure at `blocked_sample_weight` (0.5); does NOT skip untyped turns |
| `verify.result` | `messages/verify.py::VerifyResult` | simorgh/learning/service.py | caches the verdict by `verification_id` (last 500) for the completion join |
| `action.result` | `messages/action.py::ActionResult` | simorgh/learning/service.py | resolves a `Correlator` future; nothing waits on one since the pipeline retired |
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/learning/service.py | same, with `denied: True`; dead for the same reason |
| `learn.strategy.suggest` | `messages/learn.py::LearnStrategySuggest` | simorgh/learning/service.py | replies with the best strategy or overall rate for a task type; no requester today |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `learn.outcome.recorded` | `messages/learn.py::LearnOutcomeRecorded` | simorgh/learning/outcomes.py | after each outcome append (also on a deduplicated redelivery); Reflection consumes it |
| `learn.competence.updated` | `messages/learn.py::LearnCompetenceUpdated` | simorgh/learning/outcomes.py | right after `learn.outcome.recorded`, with that type's rate, calibration, samples; World Model consumes it |
| `learn.strategy.suggest.reply` | `messages/learn.py::LearnStrategySuggestReply` | simorgh/learning/service.py | as the bus reply to `learn.strategy.suggest` |
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/learning/service.py | declared; `_propose_action` has no caller, so never in practice |
| `verify.requested` | `messages/verify.py::VerifyRequested` | simorgh/learning/service.py | declared; `_request_verify` has no caller, so never in practice |

The generated rows for `learn.self_patch.applied`, `learn.self_patch.reverted`, `learn.skill.acquired` and `memory.store` were deleted: Learning publishes none of them (the first is published by `orchestration/session.py::_land`; the second by nobody since the pipeline retired).

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `learn:outcomes` | simorgh/learning/outcomes.py (write), simorgh/learning/service.py (rebuild) | - | forever (deliberately no entry in `DEFAULT_RETENTION`; the competence fold is rebuilt from it) |
| `learn:patch:{task_id}` | simorgh/learning/outcomes.py (read only) | - | no writer since the pipeline retired; the read always finds nothing, so `strategy` is never set |
| `task:{task_id}` | simorgh/learning/outcomes.py (read only) | written by Planning/Orchestration | forever |

## Config

`[learning]` in simorgh.toml; dataclass in `simorgh/learning/config.py`. Loaded from `ctx.config` in `start()` unless the caller passed one (`service.py:65-66`).

| Key | Default | Read in the package |
|---|---|---|
| `max_draft_attempts` | `3` | NO (declared, never read) |
| `max_pipeline_wall_seconds` | `900.0` | NO (declared, never read) |
| `action_timeout_seconds` | `60.0` | NO (declared, never read) |
| `verify_timeout_seconds` | `300.0` | NO (declared, never read) |
| `hot_swap_slots` | `('logic', 'emotion', 'skills')` | NO (declared, never read) |
| `explore_bonus` | `0.15` | yes (`strategy.py`) |
| `min_samples_for_trust` | `5` | yes (`strategy.py`) |
| `blocked_sample_weight` | `0.5` | yes (`outcomes.py::on_task_blocked`) |
| `max_concurrent_pipelines` | `2` | NO (declared, never read) |

The six unread keys belonged to the retired PatchPipeline.

## Public Python surface

- `simorgh.learning.Service` (`name = "learning"`, layer 4): `start(ctx)`, `stop()`, `health()`; `consumes` / `produces` as in the tables above (exact for subscriptions, pinned by `tests/simorgh/test_manifests_match_the_code.py`). `health()` is `ok` with the count of skipped untyped turns, or `degraded` if the competence rebuild failed at start.
- `CompetenceTable` (`competence.py`): duck-typed ledger projection (`apply`, `fold`, `state`, `load`, `applied_seq`) plus readers `success_rate`, `calibration`, `samples`, `suggest`. Imported by nothing outside the package; the World Model keeps its own copy of competence from `learn.competence.updated`.
- `OutcomeRecorder`, `build_reply`, `Correlator`: package-internal.
- No module-level mutable singletons. Per-instance state that is lost on restart: the verify-verdict cache (500 entries, `outcomes.py:25`), so a `task.completed` whose `verify.result` arrived before a restart records verdict `unknown`.

## Invariants

- One `learn:outcomes` event per (task_id, terminal type, run index): the idempotency key is `{task_id}:{event_type}:{run}` (`outcomes.py:181`); a redelivered terminal message appends nothing and does not re-fold the table.
- `CompetenceTable` after live `apply` equals a fresh `rebuild` over `learn:outcomes` (the property in `test_competence.py`).
- A `task.completed` or `task.failed` whose task stream has no `created` event (task type `unknown`) records nothing and increments `skipped_unknown`.
- Cost and duration are summed over the last run of the task stream only (`_last_run`), never the whole stream.
- With zero samples, `learn.strategy.suggest.reply` is `{success_rate: 0.5, samples: 0}` with no `strategy` key; with samples but no strategy breakdown it carries the real overall rate and still no `strategy`.
- Learning never publishes `action.approved` or `action.denied` and never subscribes to `action.proposed` (`contracts/topics.py` `SUBSCRIBE_ONLY_BY` / `PUBLISH_ONLY_BY`). No topics.py policy entry names `learning` directly.
- `learn.strategy.suggest` and `learn.self_patch.reverted` are on the one-sided allow-list in `tests/simorgh/contracts/test_topics_have_both_sides.py` (no requester until stage 8; no publisher since the pipeline retired).
- Learning imports only `simorgh.contracts`, `simorgh.ledger.client` and the standard library (`tests/simorgh/test_module_boundaries.py`).

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract learning`.

- `tests/simorgh/learning/test_outcomes.py` -- terminal message to outcome: success/failure/blocked weights, task type from the task stream, verify join, per-run cost and dedup keys.
- `tests/simorgh/learning/test_competence.py` -- the projection math (Laplace, shrinkage, UCB1, calibration) and apply == rebuild, state/load round trip.
- `tests/simorgh/learning/test_strategy.py` -- the `learn.strategy.suggest.reply` shape against the real schema, floor and overall-rate fallbacks.
- `tests/simorgh/learning/test_service.py` -- health is `ok` and counts untyped turns; `draft_candidate` is not a registered tool.

## Known issues (2026-09-18 evaluation)

- C1 / W1 (critical): the self-improvement topic was never published by the real landing path. Fixed 2026-09-18 outside this package: `orchestration/session.py::_land` publishes `learn.self_patch.applied` (commit `1e486f1`). `learn.self_patch.reverted` still has no publisher.
- C2 / W2 (critical): 91% of outcomes were chat turns typed `unknown` with `succeeded=True`. Partly fixed 2026-09-18 (commit `62318d3`): completed and failed untyped turns are skipped. Still open: a `task.completed` is recorded `succeeded=True` whatever the verify verdict (`outcomes.py:133`), `on_task_blocked` does not skip `unknown` (`outcomes.py:148-156`), and competence still gates nothing (only rendered in the self summary).
- C14: PatchPipeline, Correlator and strategy suggestion had no publisher or requester. Partly fixed 2026-09-18 (commit `62318d3`, pipeline deleted, health ok). Still dead: `Correlator`, `_propose_action`, `_request_verify`, the `action.result` / `action.denied` subscriptions, the six pipeline config keys and the `learn:patch:` read.
- W7: one-sided topics. `learn.strategy.suggest` (no requester) and `learn.self_patch.reverted` (no publisher) are allow-listed with a reason (commit `cd807d4`, `b5c2671`).
- Thin tests (called out by earlier reviews): four files; no test drives the service through a real bus subscription.

## Planned changes (roadmap)

- Stage 6 item 1 (`docs/plan/stage-6-self-world-people-tiers-initiative.md`): the Self Model is rebuilt at boot as a fold over `learn:outcomes` (Beta per task type and per strategy, forgetting, calibration as ECE); this package's stream becomes the input to that fold.
- Stage 8 (`docs/plan/stage-8-growth-merge-policy-loop.md`): Learning, Reflection and Curiosity merge into `simorgh/growth/` (item 1, topics preserved); estimates count only verify-backed outcomes and eval pass rates, never chat self-reports (item 2); failure clustering, a policy store and propose-evaluate-adopt through the gate follow (items 3-6). The strategy-suggest consumer and a `learn.self_patch.reverted` publisher (the loader's rollback) arrive here.

## Working on this module

Lock it first (`python tools/modlock.py claim learning --by <you> --task "..."`), commit the lock, edit only `simorgh/learning/`, `tests/simorgh/learning/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py learning` before committing; commit subject `learning: <what changed>`.
