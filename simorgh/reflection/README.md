# `simorgh/reflection/` — Meta-cognition

Spec: `docs/blueprint/subsystems/12-reflection.md`. Layer 3, registry.py.

Reflection is an observer. It never publishes `action.proposed`, never
writes `self:model` directly — only `self.observation`; World Model owns
the `self:model` projection and `self.model.updated`.

## Modules

- `health.py` — `HealthMonitor`: pure, synchronous port of v1's
  `src/orchestrator/health.py`. Ring buffer over `persona.state.changed`;
  flags pinned-extreme valence/arousal, sustained cognitive load, and
  oscillation, each with a severity and an `action_taken` hint.
- `patterns.py` — `PatternMiner`: port of v1's `ReflectionAgent.reflect()`.
  Groups task outcomes by `(task_type, strategy)` (the finest key
  `learn.outcome.recorded` actually carries — v1 grouped by `agent`,
  which has no v2 equivalent) and flags a group whose failure rate
  crosses a threshold.
- `calibration.py` — `CalibrationTable`: bins stated confidence against
  actual outcome, tracks empirical accuracy and Brier score per
  `task_type`.
- `drift.py` — `DriftTracker` + `parse_verdict`: a cheap heuristic
  (scope crossings, repeated calls, off-goal touches) that always runs,
  combined with an occasional model-backed verdict that can only push
  the combined score toward "drifting" or leave it as the heuristic
  alone — a non-answer from the model is `unknown`, never a fabricated
  `on_track` (v1 milestone 92, applied here too).
- `critique.py` — lenient JSON parsing of a `cognition.think` self-
  critique reply, with a floor template (`floor_critique`) used whenever
  there's no real answer to parse (principle 4.5, the guaranteed floor).
- `service.py` — `Service`: wires all of the above to the bus/ledger as
  a real `Subsystem`.
- `config.py` — `Config`, all thresholds, `from_mapping()`.
- `api.py` — lightweight `Protocol` stubs for the above (no shared base
  class), matching `simorgh/worldmodel/api.py`'s convention.

## Build log — scope simplifications and contract gaps

Filed in full in the spec's own §12.4. Summary:

- `reflect.patterns.found` / `reflect.calibration.updated` publish only
  the fields their actual message schemas define — narrower than the
  spec's prose payload tables (no per-pattern `task_type`, no
  `brier`/`bins`/`samples` on the wire; those stay in the richer
  internal dataclasses and the Ledger streams).
- `action.denied` is **not** wired at all in this build — its schema
  has no `task_id` to correlate against a `DriftTracker`. The §5.4
  "immediate review on a scope denial" path is unbuilt; only the
  terminal-time review runs.
- Drift review is evaluated once, at task-terminal time over the whole
  trajectory, not live every `drift_check_every_steps` steps mid-task —
  a scope cut for this build session. The heuristic, the combined-score
  formula, and the never-fabricate-on-`unknown` rule are implemented
  exactly as specified; only the review *timing* is simplified.
- `DriftTracker` registration anchors on `task.created` (which carries
  `description`/`scope`), not `task.started` (which carries neither).
- `plan.revised`'s `plan_id` doesn't correlate to any task's `task_id`
  in the current contracts, so the project-level tracker from §5.4's
  closing paragraph isn't reachable yet; `_on_plan_revised` is wired
  but is a documented no-op until that correlation exists.

### Phase 4 Wave 2

- `reflect.drift.detected` is now actually consumed: Planning
  (`simorgh/planning/service.py`) reacts by flagging the drifting
  task's project for re-grounding on its next PENDING->AVAILABLE
  sibling and recording a `plan.revised` with the drift as the reason
  — closes harness-06 gap #3, "no drift/re-grounding check across a
  multi-tick PROJECT_TASK." Previously this event was published and
  never consumed by anything.
- `_on_sleep` now also publishes `self.observation{kind:limitation}`
  for every mined pattern (in addition to the existing
  `reflect.patterns.found`) — the wire path World Model's `SELF.md`
  "What I know I'm bad at" section actually ingests
  (`06-worldmodel.md` section 5's ingestion table); previously nothing
  produced a real `kind:limitation` observation even though the
  contract's `kind` enum already allowed it.
- Reflection still has no wire event carrying a self-critique's
  `open_questions` (only `guardian:critique:<id>`/`memory.store` see
  them) — `simorgh/worldmodel/selfmodel.py`'s docstring names the
  one-line contract addition (a new `self.observation` kind, or a
  dedicated `reflect.critique.recorded` event) that would close it.

## Tests

- `tests/simorgh/reflection/` — pure-logic unit tests for every module
  above (56 tests: health, patterns, calibration, drift, critique).
- `tests/simorgh/integration/test_reflection_health_patterns_calibration.py`
  — `Service` over a real memory-backend Bus/Ledger, no Cognition or
  Learning subsystem running at all. Covers: a pinned-extreme persona
  sequence producing a critical health finding; three same-kind
  `task.failed` events producing `reflect.patterns.found`, with the
  `patch`-kind critique path proving real graceful degradation (a
  `cognition.think` request against nothing times out within
  `review_timeout_s` and falls back to a floor critique — never a
  fabricated one); a `task.completed(confidence=0.9)` later contradicted
  by `learn.outcome.recorded(succeeded=false, confidence=0.9)` producing
  a `reflect.calibration.updated` whose empirical accuracy is honestly
  below its stated confidence.
