# growth.estimate (was learning) -- contract

One-line status: layer 4 · 727 lines · 4 test files · lock: `growth` in docs/modules/locks.toml (one lock for the three parts)

## Purpose

Learning owns the outcome record and the competence estimate: it turns `task.completed` / `task.failed` / `task.blocked` into one `learn:outcomes` event per run, folds those into `CompetenceTable` (Laplace-smoothed success rate, calibration, strategy ranking), and announces each outcome and the new estimate on the bus. It never acts: it runs no tool, edits no file and changes no config, and its one query answer (`learn.strategy.suggest`) is a pure read of the projection. The shaping decision is that competence is a projection over an append-only stream: `CompetenceTable.apply` does nothing a fresh `rebuild` would not (`competence.py:1-12`), so the table survives restarts by replaying `learn:outcomes` at `start()` (`service.py:72`). The task type is read from the task's own `task:<id>` stream (its `created` event), never guessed from the terminal message (`outcomes.py:1-11`). The self-patch PatchPipeline that used to live here was retired on 2026-09-18 (commit `62318d3`); self-landing now happens in `orchestration/session.py::_land`.

## Files

| File | For |
|---|---|
| `simorgh/growth/estimate/__init__.py` | re-exports `Service`, `VERSION` |
| `simorgh/growth/estimate/competence.py` | `CompetenceTable`: the projection over `learn:outcomes` (rate, calibration, UCB1 strategy ranking) |
| `simorgh/growth/estimate/config.py` | `[growth.estimate]` dataclass |
| `simorgh/growth/estimate/correlator.py` | id-keyed futures for `action.result` / `verify.result`; a leftover of the retired pipeline, nothing awaits them |
| `simorgh/growth/estimate/models.py` | plain dataclasses (`TaskTypeStats`, `StrategyStats`, `StrategyScore`; `Strategy`, `Outcome`, `PatchTaskSpec` unused) |
| `simorgh/growth/estimate/outcomes.py` | `OutcomeRecorder`: terminal task messages to `learn:outcomes` events and the two announcements |
| `simorgh/growth/estimate/service.py` | `Service`: subscriptions, competence rebuild at start, health |
| `simorgh/growth/estimate/strategy.py` | `build_reply`: answers `learn.strategy.suggest` from the table |

`simorgh/growth/estimate/README.md` still describes the retired `pipeline.py` and `learn.pipeline.run`; it is stale.

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/growth/estimate/service.py | records a success (weight 1.0) with the cached verify verdict; skips untyped turns |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/growth/estimate/service.py | records a failure (weight 1.0); skips untyped turns |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/growth/estimate/service.py | records a failure at `blocked_sample_weight` (0.5); does NOT skip untyped turns |
| `verify.result` | `messages/verify.py::VerifyResult` | simorgh/growth/estimate/service.py | caches the verdict by `verification_id` (last 500) for the completion join |
| `action.result` | `messages/action.py::ActionResult` | simorgh/growth/estimate/service.py | resolves a `Correlator` future; nothing waits on one since the pipeline retired |
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/growth/estimate/service.py | same, with `denied: True`; dead for the same reason |
| `learn.strategy.suggest` | `messages/learn.py::LearnStrategySuggest` | simorgh/growth/estimate/service.py | replies with the best strategy or overall rate for a task type; no requester today |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `learn.outcome.recorded` | `messages/learn.py::LearnOutcomeRecorded` | simorgh/growth/estimate/outcomes.py | after each outcome append (also on a deduplicated redelivery); Reflection consumes it |
| `learn.competence.updated` | `messages/learn.py::LearnCompetenceUpdated` | simorgh/growth/estimate/outcomes.py | right after `learn.outcome.recorded`, with that type's rate, calibration, samples; World Model consumes it |
| `learn.strategy.suggest.reply` | `messages/learn.py::LearnStrategySuggestReply` | simorgh/growth/estimate/service.py | as the bus reply to `learn.strategy.suggest` |
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/growth/estimate/service.py | declared; `_propose_action` has no caller, so never in practice |
| `verify.requested` | `messages/verify.py::VerifyRequested` | simorgh/growth/estimate/service.py | declared; `_request_verify` has no caller, so never in practice |

The generated rows for `learn.self_patch.applied`, `learn.self_patch.reverted`, `learn.skill.acquired` and `memory.store` were deleted: Learning publishes none of them (the first is published by `orchestration/session.py::_land`; the second by nobody since the pipeline retired).

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `learn:outcomes` | simorgh/growth/estimate/outcomes.py (write), simorgh/growth/estimate/service.py (rebuild) | - | forever (deliberately no entry in `DEFAULT_RETENTION`; the competence fold is rebuilt from it) |
| `learn:patch:{task_id}` | simorgh/growth/estimate/outcomes.py (read only) | - | no writer since the pipeline retired; the read always finds nothing, so `strategy` is never set |
| `task:{task_id}` | simorgh/growth/estimate/outcomes.py (read only) | written by Planning/Orchestration | forever |

## Config

`[growth.estimate]` in simorgh.toml (this was `[learning]` before the stage 8 merge); dataclass in `simorgh/growth/estimate/config.py`. Loaded from `ctx.config` in `start()` unless the caller passed one (`service.py:65-66`).

| Key | Default | Read in the package |
|---|---|---|
| `explore_bonus` | `0.15` | yes (`strategy.py`) |
| `min_samples_for_trust` | `5` | yes (`strategy.py`) |
| `blocked_sample_weight` | `0.5` | yes (`outcomes.py::on_task_blocked`) |
| `unverified_sample_weight` | `0.25` | yes (`outcomes.py::on_task_completed`) |
| `eval_sample_weight` | `0.5` | yes (`service.py::_on_estimate`, `load_evals`) |
| `eval_suites` | `patch->trials, research->research, chat->household` | yes (`service.py::_suite_for`) |
| `evals_record` | `.simorgh_loader/evals.jsonl` | yes (`service.py::start`) |

The six keys that belonged to the retired PatchPipeline (`max_draft_attempts`, `max_pipeline_wall_seconds`, `action_timeout_seconds`, `verify_timeout_seconds`, `hot_swap_slots`, `max_concurrent_pipelines`) were removed from the dataclass on 2026-09-19; `from_mapping` drops any key it does not know, so writing one changes nothing and the Kernel's config check reports the section (`tests/simorgh/growth/estimate/test_config.py`).

## What an estimate rests on (stage 8 item 2)

Two sources, weighted, and nothing else:

| Source | Weight per sample | Why |
|---|---|---|
| a task outcome a verification passed | 1.0 | the strongest thing there is: something checked it |
| a task outcome nobody verified | `unverified_sample_weight` (0.25) | "the task said it finished" is a self-report. It counts a little, because dropping it would leave whole task types with no estimate, and it is counted separately (`OutcomeRecorder.unverified`) so how much of an estimate is self-report can be read off |
| a blocked task | `blocked_sample_weight` (0.5), as a failure | it did not work, but it did not go wrong the way a failure does |
| an eval case | `eval_sample_weight` (0.5) | a fixture is the same question every time and the house is not in it |

Eval cases are kept under their own key (`eval:<suite>`), never mixed into the task type's own counts, so "what a fixture says" and "what happened in this house" can be read apart. `posterior(task_type, eval_suite=...)` is what blends them, and `_suite_for` maps a task type's first segment to a suite (`patch:src/memory` is about patching, not about that directory). Reports are read from `evals_record` at start -- a file rather than the bus, because the evals run before the Kernel is up, on every `simloader bless` -- and only the newest report per suite counts: older runs are history, not more evidence, and counting all of them would let a suite that has been run fifty times outvote the house.

A chat turn never reaches any of this: it has no task type, and untyped outcomes are skipped (`OutcomeRecorder.skipped_unknown`).

## Public Python surface

- `simorgh.growth.estimate.Service` (a part of the `growth` Subsystem since stage 8 item 1; it has no `name` of its own on the bus -- it publishes as `growth`): `start(ctx)`, `stop()`, `health()`; `consumes` / `produces` as in the tables above (exact for subscriptions, pinned by `tests/simorgh/test_manifests_match_the_code.py`). `health()` is `ok` with the count of skipped untyped turns, or `degraded` if the competence rebuild failed at start.
- `CompetenceTable` (`competence.py`): duck-typed ledger projection (`apply`, `fold`, `state`, `load`, `applied_seq`) plus readers `success_rate`, `calibration`, `samples`, `suggest`. Imported by nothing outside the package; the World Model keeps its own copy of competence from `learn.competence.updated`.
- `OutcomeRecorder`, `build_reply`, `Correlator`: package-internal.
- No module-level mutable singletons. Per-instance state that is lost on restart: the verify-verdict cache (500 entries, `outcomes.py:25`), so a `task.completed` whose `verify.result` arrived before a restart records verdict `unknown`.

## Invariants

- `self.estimate.request` is answered from the same `learn:outcomes` projection as the strategy suggestion: a Beta posterior per task type (and per strategy), `Beta(1,1)` when nothing is recorded -- mean 0.5 with a wide spread, which means "no idea", not "half the time". A consumer that acts on the mean must read `samples` too (stage 6 items 1-2).

- One `learn:outcomes` event per (task_id, terminal type, run index): the idempotency key is `{task_id}:{event_type}:{run}` (`outcomes.py:181`); a redelivered terminal message appends nothing and does not re-fold the table.
- `CompetenceTable` after live `apply` equals a fresh `rebuild` over `learn:outcomes` (the property in `test_competence.py`).
- A `task.completed` or `task.failed` whose task stream has no `created` event (task type `unknown`) records nothing and increments `skipped_unknown`.
- Cost and duration are summed over the last run of the task stream only (`_last_run`), never the whole stream.
- With zero samples, `learn.strategy.suggest.reply` is `{success_rate: 0.5, samples: 0}` with no `strategy` key; with samples but no strategy breakdown it carries the real overall rate and still no `strategy`.
- Learning never publishes `action.approved` or `action.denied` and never subscribes to `action.proposed` (`contracts/topics.py` `SUBSCRIBE_ONLY_BY` / `PUBLISH_ONLY_BY`). No topics.py policy entry names `learning` directly.
- `learn.strategy.suggest` and `learn.self_patch.reverted` are on the one-sided allow-list in `tests/simorgh/contracts/test_topics_have_both_sides.py` (no requester until stage 8; no publisher since the pipeline retired).
- Learning imports only `simorgh.contracts`, `simorgh.ledger.client` and the standard library (`tests/simorgh/test_module_boundaries.py`).

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract growth`.

- `tests/simorgh/growth/estimate/test_outcomes.py` -- terminal message to outcome: success/failure/blocked weights, task type from the task stream, verify join, per-run cost and dedup keys.
- `tests/simorgh/growth/estimate/test_competence.py` -- the projection math (Laplace, shrinkage, UCB1, calibration) and apply == rebuild, state/load round trip.
- `tests/simorgh/growth/estimate/test_strategy.py` -- the `learn.strategy.suggest.reply` shape against the real schema, floor and overall-rate fallbacks.
- `tests/simorgh/growth/estimate/test_service.py` -- health is `ok` and counts untyped turns; `draft_candidate` is not a registered tool.
- `tests/simorgh/growth/estimate/test_config.py` -- `[growth.estimate]` has exactly the three live keys; a retired pipeline key changes nothing.

## Known issues (2026-09-18 evaluation)

- C1 / W1 (critical): the self-improvement topic was never published by the real landing path. Fixed 2026-09-18 outside this package: `orchestration/session.py::_land` publishes `learn.self_patch.applied` (commit `1e486f1`). `learn.self_patch.reverted` still has no publisher.
- C2 / W2 (critical): 91% of outcomes were chat turns typed `unknown` with `succeeded=True`. Partly fixed 2026-09-18 (commit `62318d3`): completed and failed untyped turns are skipped. Still open: a `task.completed` is recorded `succeeded=True` whatever the verify verdict (`outcomes.py:133`), `on_task_blocked` does not skip `unknown` (`outcomes.py:148-156`), and competence still gates nothing (only rendered in the self summary).
- C14: PatchPipeline, Correlator and strategy suggestion had no publisher or requester. Partly fixed 2026-09-18 (commit `62318d3`, pipeline deleted, health ok). Still dead: `Correlator`, `_propose_action`, `_request_verify`, the `action.result` / `action.denied` subscriptions and the `learn:patch:` read (the six pipeline config keys were removed 2026-09-19).
- W7: one-sided topics. `learn.strategy.suggest` (no requester) and `learn.self_patch.reverted` (no publisher) are allow-listed with a reason (commit `cd807d4`, `b5c2671`).
- Thin tests (called out by earlier reviews): four files; no test drives the service through a real bus subscription.

## Planned changes (roadmap)

- Stage 6 item 1 (`docs/plan/stage-6-self-world-people-tiers-initiative.md`): the Self Model is rebuilt at boot as a fold over `learn:outcomes` (Beta per task type and per strategy, forgetting, calibration as ECE); this package's stream becomes the input to that fold.
- Stage 8 (`docs/plan/stage-8-growth-merge-policy-loop.md`): Learning, Reflection and Curiosity merged into `simorgh/growth/` (item 1, done 2026-09-20, topics preserved); estimates count only verify-backed outcomes and eval pass rates, never chat self-reports (item 2); failure clustering, a policy store and propose-evaluate-adopt through the gate follow (items 3-6). The strategy-suggest consumer and a `learn.self_patch.reverted` publisher (the loader's rollback) arrive here.

## Working on this module

Lock it first (`python tools/modlock.py claim growth --by <you> --task "..."`), commit the lock, edit only `simorgh/growth/estimate/`, `tests/simorgh/growth/estimate/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py learning` before committing; commit subject `learning: <what changed>`.
