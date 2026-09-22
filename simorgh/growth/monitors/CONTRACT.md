# growth.monitors (was reflection) -- contract

One-line status: layer 4 · 2,157 lines · 10 test files · lock: `growth` in docs/modules/locks.toml (one lock for the three parts)

## Purpose

Reflection watches what the system does and turns it into signals other subsystems act on: mood-health findings, task drift and stalls, failure patterns, confidence calibration, self-critiques, repeated Guardian denials, skill-distillation proposals, and monitor alerts with a daily digest. It is an observer that proposes: its outputs are bus messages (`reflect.*`, `self.observation`, `task.create`, `memory.store`) and, for alerts only, a `notify` routed through `action.proposed` so Guardian sees it like any other irreversible action (`service.py:806-817`). It must never call a tool directly, never write `self:model` (World Model folds `self.observation`), and never fabricate a verdict or critique when no model answers: drift stays `unknown` and a critique falls back to the mechanical floor (`drift.py`, `critique.py`). The shaping decision is that every judgement core (health, drift, patterns, calibration, denials, digest, distillation) is pure and synchronous with an injected clock; `service.py` is the only file that touches the bus, the ledger or the model.

## Files

| File | For |
|---|---|
| `simorgh/growth/monitors/__init__.py` | empty package marker |
| `simorgh/growth/monitors/api.py` | Protocols describing the four pure cores the service composes (documentation only) |
| `simorgh/growth/monitors/calibration.py` | `CalibrationTable`: stated confidence vs outcome per task type, Brier score, min-sample gate |
| `simorgh/growth/monitors/config.py` | frozen `Config` dataclass and `from_mapping` for `[growth.monitors]` |
| `simorgh/growth/monitors/critique.py` | lenient JSON parse of a model critique, with a floor critique when it fails |
| `simorgh/growth/monitors/denials.py` | `DenialMiner`: same tool+reason denied N times in a window becomes one proposal |
| `simorgh/growth/monitors/digest.py` | pure monitors, alert routing (rate limit, quiet hours, reopen), daily digest rendering |
| `simorgh/growth/monitors/distillation.py` | decides whether a solved task is worth a new skill, and its slug |
| `simorgh/growth/monitors/drift.py` | `DriftTracker` heuristic score plus a model verdict that can only raise it |
| `simorgh/growth/monitors/health.py` | `HealthMonitor`: pinned/oscillating mood and load -> warn/critical finding |
| `simorgh/growth/monitors/patterns.py` | `PatternMiner`: failure rate per `(task_type, strategy)` over a window |
| `simorgh/growth/monitors/service.py` | the `Service`: subscriptions, the reflection pass loop, publishing and ledger appends |

## Consumes

Exact subscription list: `Service.consumes` (`service.py:106-117`).

| Topic | Schema | Where | Does |
|---|---|---|---|
| `persona.state.changed` | `messages/persona.py::PersonaStateChanged` | simorgh/growth/monitors/service.py | feeds `HealthMonitor`; publishes a finding only when severity changes |
| `task.created` | `messages/task.py::TaskCreated` | simorgh/growth/monitors/service.py | registers the task's goal and scope with a new `DriftTracker` |
| `task.step` | `messages/task.py::TaskStep` | simorgh/growth/monitors/service.py | records the tool used, resets the stall clock, feeds the drift heuristic |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/growth/monitors/service.py | terminal: pattern sample, calibration, drift close, `self.observation`, critique for work kinds |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/growth/monitors/service.py | same terminal path as completed, as a failure |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/growth/monitors/service.py | same terminal path, counted as a failure |
| `verify.result` | `messages/verify.py::VerifyResult` | simorgh/growth/monitors/service.py | calibration sample for task type `verify` when a confidence is present |
| `plan.revised` | `messages/plan.py::PlanRevised` | simorgh/growth/monitors/service.py | counts a plan revision on a tracker keyed by `plan_id` (rarely matches; `service.py:427-440`) |
| `learn.outcome.recorded` | `messages/learn.py::LearnOutcomeRecorded` | simorgh/growth/monitors/service.py | pattern sample and calibration sample |
| `learn.self_patch.applied` | `messages/learn.py::LearnSelfPatchApplied` | simorgh/growth/monitors/service.py | publishes `self.observation{kind: change}` |
| `learn.self_patch.reverted` | `messages/learn.py::LearnSelfPatchReverted` | simorgh/growth/monitors/service.py | publishes `self.observation{kind: change}` (no publisher today) |
| `learn.skill.acquired` | `messages/learn.py::LearnSkillAcquired` | simorgh/growth/monitors/service.py | publishes `self.observation{kind: change}` |
| `system.started` | `messages/system.py::SystemStarted` | simorgh/growth/monitors/service.py | publishes `self.observation{kind: restart}` |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/growth/monitors/service.py | sets the paused flag (paused/stopping/stopped): no model calls, no monitors, no pass |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/growth/monitors/service.py | runs the reflection pass (patterns + calibration) |
| `system.tick.idle` | `messages/system.py::SystemTickIdle` | simorgh/growth/monitors/service.py | stall check, then due monitors, ad-hoc alerts and the digest |
| `reflect.review.request` | `messages/reflect.py::ReflectReviewRequest` | simorgh/growth/monitors/service.py | replies with patterns mined over the requested window (no publisher today) |
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/growth/monitors/service.py | scope denials feed drift; repeated denials become a `repeated_denial` pattern |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `reflect.health.finding` | `messages/reflect.py::ReflectHealthFinding` | simorgh/growth/monitors/service.py | health severity changes to warn/critical (consumed by Guardian, Persona) |
| `reflect.drift.detected` | `messages/reflect.py::ReflectDriftDetected` | simorgh/growth/monitors/service.py | combined drift score crosses `drift_emit_threshold` at task end, or a task stalls |
| `reflect.patterns.found` | `messages/reflect.py::ReflectPatternsFound` | simorgh/growth/monitors/service.py | the pass mines patterns, or a denial group crosses its threshold (Planning turns it into tasks) |
| `reflect.calibration.updated` | `messages/reflect.py::ReflectCalibrationUpdated` | simorgh/growth/monitors/service.py | each pass, per task type with at least `calibration_min_samples` |
| `reflect.review.reply` | `messages/reflect.py::ReflectReviewReply` | simorgh/growth/monitors/service.py | reply to `reflect.review.request` (via `bus.reply`) |
| `reflect.alert.raised` | `messages/reflect.py::ReflectAlertRaised` | simorgh/growth/monitors/service.py | a monitor or ad-hoc alert is delivered (allow-listed one-sided) |
| `reflect.alert.cleared` | `messages/reflect.py::ReflectAlertCleared` | simorgh/growth/monitors/service.py | an open alert is resolved (allow-listed one-sided) |
| `self.observation` | `messages/self_.py::SelfObservation` | simorgh/growth/monitors/service.py | every terminal task, self-patch, skill, restart, and each mined pattern (`kind: limitation`) |
| `memory.store` | `messages/memory.py::MemoryStore` | simorgh/growth/monitors/service.py | one `procedural` critique per terminal patch/skill/research/project task |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/growth/monitors/service.py | request/reply for the drift review and the critique (`purpose: review`) |
| `task.create` | `messages/task.py::TaskCreate` | simorgh/growth/monitors/service.py | a distillation candidate passes the daily cap (`kind: skill`, `origin: reflection`) |
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/growth/monitors/service.py | an alert or the daily digest goes out as an irreversible `notify` |

`system.tick.sleep` is built in `_reflect_periodically` (`service.py:555`) but handed to `_run_pass` directly, never published.

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `reflect:health` | simorgh/growth/monitors/service.py | - | 90d (`reflect:` prefix) |
| `reflect:drift:{task_id}` | simorgh/growth/monitors/service.py | - | 90d (`reflect:` prefix) |
| `reflect:critique:{task_id}` | simorgh/growth/monitors/service.py | - | 90d (`reflect:` prefix) |
| `reflect:distillation` | simorgh/growth/monitors/service.py | - | 90d (`reflect:` prefix) |
| `reflect:patterns` | simorgh/growth/monitors/service.py | - | 90d (`reflect:` prefix) |
| `reflect:calibration` | simorgh/growth/monitors/service.py | - | 90d (`reflect:` prefix) |
| `reflection:alerts` | simorgh/growth/monitors/service.py | simorgh/interface/dispatch.py | 90d (its own `DEFAULT_RETENTION` entry, `ledger/compaction.py`) |

There is no `reflect:self` stream (a `SELF_STREAM` constant naming one was never written and was removed 2026-09-19); `self.observation` is a bus message only. Reflection reads no stream: all its state (task metas, miners, calibration, alert router) is in memory and starts empty on every boot.

## Config

`[growth.monitors]` in simorgh.toml (`[reflection]` before the 2026-09-20 merge; nothing reads that name now); dataclass in `simorgh/growth/monitors/config.py`. Some keys are nested in the TOML: `health_*` under `[growth.monitors.health]` (e.g. `window`, `oscillation_flips_warn`), `pattern_*` under `[growth.monitors.pattern]`, `calibration_*` under `[growth.monitors.calibration]` (`config.py:120-151`). An explicitly constructed `Config` wins over `ctx.config`.

| Key | Default | Read in the package |
|---|---|---|
| `health_window` | `12` | yes |
| `health_extreme` | `0.9` | yes |
| `health_pinned_n` | `5` | yes |
| `health_load_ceiling` | `0.95` | yes |
| `health_oscillation_warn` | `6` | yes |
| `health_oscillation_critical` | `8` | yes |
| `drift_check_every_steps` | `8` | yes |
| `drift_heuristic_threshold` | `0.5` | yes |
| `drift_emit_threshold` | `0.6` | yes |
| `stall_idle_seconds` | `1800.0` | yes |
| `critique_max_tokens` | `400` | yes |
| `distillation_enabled` | `True` | yes |
| `max_distillations_per_day` | `3` | yes |
| `skill_dir` | `'simorgh_skills'` | yes |
| `pattern_window_seconds` | `86400.0` | yes |
| `pattern_min_rate` | `0.5` | yes |
| `pattern_min_samples` | `3` | yes |
| `denial_window_seconds` | `3600.0` | yes |
| `denial_min_repeats` | `5` | yes |
| `monitors_enabled` | `True` | yes |
| `alert_warn_window_s` | `3600.0` | yes |
| `quiet_hours` | `''` | yes |
| `digest_enabled` | `True` | yes |
| `digest_hour` | `8` | yes |
| `announce_critical` | `False` | yes |
| `calibration_bins` | `10` | yes |
| `calibration_min_samples` | `10` | yes |
| `review_timeout_s` | `90.0` | yes -- it is the deadline Cognition SHARES between candidates (`router._share_of`), not one provider's timeout: at 8.0 each of the `review` route's two providers got the 5 s floor and the call died on it (`after 5.1s of 5.0s`, live 2026-09-22), leaving the monitor to read a floor "unknown" |
| `max_concurrent_reviews` | `2` | yes |
| `reflect_after_start_s` | `120.0` | yes |
| `reflect_every_s` | `3600.0` | yes |

## Public Python surface

- `simorgh.growth.monitors.service.Service` (a part of `growth`, keyed `monitors` in `growth/service.py::PARTS`): the Subsystem (`start`, `stop`, `health` always `ok`). Two extra public methods, `register_monitor(monitor)` and `raise_alert(alert: digest.Alert)`, are the designed entry points for domains to add checks. Nothing outside the package calls either, and the service registers no monitor of its own: in a running Sim the registry is empty, no `reflect.alert.*` is ever published, no alert `notify` is proposed, and the daily digest renders empty and is skipped. The alert and digest path runs only in `tests/simorgh/growth/monitors/test_service_alerts.py`. There is no obvious caller to wire: a domain cannot import `simorgh.growth` (`tests/simorgh/test_module_boundaries.py`), so a live caller needs a bus-level entry point (a topic) first, which is a contracts change.
- `Config` (`config.py`), read by the Kernel's config check.
- Nothing is exported through `simorgh.contracts`; other packages see Reflection only through the topics above.
- No module-level mutable singletons. Module constants: stream names, `_CRITIQUE_KINDS`. `_repo_root()` duplicates `execution/config.py::find_repo_root` (`service.py:44-69`) to resolve `skill_dir`.

## Invariants

- Every subscription is declared in `Service.consumes`, and every topic in `consumes`/`produces` is referenced in the package (`tests/simorgh/test_manifests_match_the_code.py`).
- Reflection never subscribes to `action.proposed` or `action.approved` and never publishes `action.approved`, `action.denied`, `self.model.updated` or `plan.proposed` (`SUBSCRIBE_ONLY_BY` / `PUBLISH_ONLY_BY` in `contracts/topics.py`; no policy entry names Reflection itself).
- Every `action.proposed` it publishes has `tool: notify`, `reversibility: irreversible` and `proposed_by` set to its source; it never invokes a tool itself.
- A health finding is published only when the severity differs from the last one seen; a steady critical state publishes once.
- A drift model reply that is missing, failed or unparseable yields verdict `unknown` and never lowers the heuristic score.
- A critique is always stored, as `memory.store{kind: procedural}` tagged `self_critique`, never as `episodic` (C7); with no model reply it is the mechanical floor with `floor: true`.
- At most `max_distillations_per_day` `task.create{kind: skill}` per UTC day; the counter resets when the day changes.
- A stalled task is reported once per stall episode; a new `task.step` re-arms it.
- While paused (`system.state.changed` paused/stopping/stopped) no model calls, no monitor runs and no periodic pass run.
- The reflection pass runs `reflect_after_start_s` after start and every `reflect_every_s`, independent of the six-hourly sleep tick.
- A malformed `quiet_hours` is logged and alerting still runs (without quiet hours); it never takes the subsystem down.
- A confidence that is not a probability (NaN, inf, out of range) is refused by `CalibrationTable.record` and logged, never folded in.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract growth`.

- `tests/simorgh/integration/test_reflection_health_patterns_calibration.py` -- the real Service over a real bus: health finding, patterns found, calibration, critique floor with no Cognition
- `tests/simorgh/integration/test_reflection_pass_without_a_sleep_tick.py` -- the pass publishes patterns, calibration and limitations without a sleep tick
- `tests/simorgh/growth/monitors/test_service_alerts.py` -- idle tick -> monitors -> `reflect.alert.*`, ledger rows and a `notify` `action.proposed`
- `tests/simorgh/growth/monitors/test_service_stall.py` -- `stall_idle_seconds` produces one `behavior`/`note` drift per stall episode
- `tests/simorgh/growth/monitors/test_config.py` -- every dataclass field is read by `from_mapping` (the completeness check)
- `tests/simorgh/growth/monitors/test_distillation.py` -- when a solved task becomes a skill proposal, and the refusals
- `tests/simorgh/growth/monitors/test_drift.py` -- heuristic score and the rule that a model verdict never lowers it
- `tests/simorgh/orchestration/test_critiques_stay_out_of_chat.py` -- critiques are procedural memory, recalled by task sessions and not by chat (C7)

## Known issues (2026-09-18 evaluation)

- C1 -- `learn.self_patch.applied` had no real publisher; fixed 2026-09-18 (`1e486f1`, `_land` publishes it). `learn.self_patch.reverted` still has none (allow-listed until stage 8).
- C6 -- Reflection's calibration finding reaches a Self Model that is volatile across restarts; Reflection's own state is also in-memory only (open, stage 6).
- C7 -- critiques stored as episodic memory leaked into family chat prompts; fixed 2026-09-18 (`aa05475`, stored as `procedural`).
- C14 -- drift review costs model calls and health noise without producing decisions; pattern mining and distillation are the parts that change behaviour (open, stage 8).

## Planned changes (roadmap)

- Stage 1 (telemetry) lists "reflection's trajectory reads" among the `trace:` consumers to port; Reflection reads no ledger stream today (the trajectory reader is `verification/trajectory.py`), so nothing changes here.
- Stage 8 item 1 (done 2026-09-20): Reflection, Learning and Curiosity merged into one `simorgh/growth/` package; every `reflect.*` topic keeps being published so no consumer changes (`docs/plan/stage-8-growth-merge-policy-loop.md`).
- Stage 8 item 3: the pattern and denial miners fold into a deterministic failure-clustering "diagnose" step; the model only phrases a lesson.
- Stage 8 items 5-6: distillation becomes a policy candidate evaluated on a held-out set before adoption, then monitored and retired on regression.
- Stage 8 item 8: the nightly loop on `system.tick.sleep` (evals, trace mining, skill drafting) replaces the current sleep-tick pass.
- Stage 6 item 6: proactive delivery (safety alerts, digests) moves into a new `initiative/` module; the plan does not yet name Reflection's `notify` path, which is the obvious candidate to route through it.

## Working on this module

Lock it first (`python tools/modlock.py claim growth --by <you> --task "..."`), commit the lock, edit only `simorgh/growth/monitors/`, `tests/simorgh/growth/monitors/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py reflection` before committing; commit subject `reflection: <what changed>`.
