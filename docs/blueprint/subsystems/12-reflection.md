# 12 — Reflection (`simorgh/reflection/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). A spec may refine those documents; it
> may not contradict them. If you find a contradiction, fix the governing
> document and note it in `00-README.md`'s changelog.

**Layer:** 3 Growth
**Owner (build):** built (2026 build session — see §12.4 for scope simplifications)
**Status:** built
**Depends on (contracts only):** `persona.state.changed`, `task.started`, `task.step`, `task.completed`, `task.failed`, `task.blocked`, `verify.result`, `plan.proposed`, `plan.approved`, `plan.revised`, `action.denied`, `learn.outcome.recorded`, `learn.competence.updated`, `learn.self_patch.applied`, `learn.self_patch.reverted`, `learn.skill.acquired`, `system.started`, `system.state.changed`, `system.tick.idle`, `system.tick.sleep`, `self.model.updated`
**v1 code that migrates here:** `src/orchestrator/health.py` (`HealthMonitor`), `src/orchestrator/reflection.py` (`ReflectionAgent`, `reflect_on_outcome`, `TAKEAWAY_KIND`, `Proposal`, `AGENT_SOURCE_FILES`), the self-critique-delta and self-model-diffing ideas from v1's self-patched `reflection.py` (re-implemented, not copied — v1's versions were unverified autonomous patches)

## 1. Purpose and responsibilities

Reflection is Simorgh thinking about its own thinking. It is the
architectural home of meta-cognition (AGI-03 §9; AGI-04 §7): the
subsystem that watches every other subsystem's outputs and the system's
own internal state, and turns them into three kinds of knowledge — *is
the system healthy*, *is it drifting from what it meant to do*, and
*what is true about it now that wasn't true before*. It is the **writer
of record for `self.observation`**: nothing else may assert a fact about
Simorgh's own limitations, calibration, or history; other subsystems
emit what happened, Reflection decides what it *means* about the self,
and the World Model folds it into the Self Model. Reflection has no
authority to act. It can only observe, conclude, and tell.

**Responsibilities (owns):**
- Health and stability monitoring of the persona's continuous state (pinned extremes, sustained overload, oscillation) → `reflect.health.finding`.
- Pattern mining over outcomes (recurring failure classes per task type / area / tool) → `reflect.patterns.found`, which Planning turns into tasks.
- Calibration tracking: stated confidence vs empirical outcomes, per task type → `reflect.calibration.updated`.
- Self-critique deltas: after each task, a structured record of what changed, how confident the system is, and what remains open.
- Drift detection for long-running work (goal, scope, behavior) → `reflect.drift.detected`, feeding Planning re-grounding and Guardian tightening.
- Self Model maintenance: `self.observation` events (restart, change, limitation, success, failure) and the sleep-time "what changed about me" diff.

**Explicit non-responsibilities (belongs elsewhere):**
- Holding or rendering the Self Model — **World Model** (06). Reflection emits observations; it never writes `self:model` directly.
- Resetting the persona's state — **Persona** (14) acts on `reflect.health.finding{severity: critical}`; Reflection only reports.
- Re-planning — **Planning** (07) reacts to `reflect.drift.detected`.
- Changing permissions or trust — **Guardian** (09) reads Reflection's findings and *tightens*; Reflection never proposes loosening (§8, principle 4.11).
- Recording outcomes or competence — **Learning** (11); Reflection reads `learn.*`.
- Any action. Reflection never emits `action.proposed`.

**Principles this subsystem is the primary enforcer of** (from `01` §4): 4.7 (re-ground while you act — Reflection is the detector), 4.11 (tightening is automatic; loosening never originates here), 4.12 (every conclusion about the self is a logged, readable event with its evidence).

## 2. Position in the architecture

Layer 3. Participates in Flow 1 (a turn's outcome is a self-observation source), Flow 2 (post-task critique and outcome patterns), Flow 3 (drift checks on project children), Flow 7 (restart observation), Flow 8 (sleep-time pattern mining, calibration, change diff), Flow 9 (its `self.gaps` inputs originate from what Reflection observed). Imports only `simorgh.contracts`, bus/ledger clients, stdlib.

## 3. Interfaces

### 3.1 Messages consumed

| Type | Pattern | Semantics | What this subsystem does with it |
|---|---|---|---|
| `persona.state.changed` | event | fact | Append to the health window; run `HealthMonitor.inspect()`; emit finding on change of severity |
| `task.started` | event | fact | Open a `DriftTracker` for the task (goal, declared scope, step counter) |
| `task.step` | event | fact | Feed the tracker; every `drift_check_every_steps` steps run a drift check (§5.4); collect `confidence` if present |
| `task.completed` / `task.failed` / `task.blocked` | event | fact | Close the tracker; run self-critique (§5.3); emit `self.observation{success\|failure}`; take stated confidence for calibration |
| `verify.result` | event | fact | Calibration sample (evaluator confidence vs later outcome); trajectory stats (`wasted`, `recovered_errors`) into behavior-drift baselines |
| `plan.proposed` / `plan.approved` / `plan.revised` | event | fact | Register the plan's goal and per-step `why` for drift checks; a `plan.revised` without a reason is itself a `reflect.drift.detected{kind: behavior}` |
| `action.denied` | event | fact | `layer == scope` → immediate drift check for that task (scope-boundary crossing, harness-03 §3) |
| `learn.outcome.recorded` / `learn.competence.updated` | event | fact | Pattern mining inputs; calibration join |
| `learn.self_patch.applied` / `.reverted` / `learn.skill.acquired` | event | fact | `self.observation{kind: change}`; change-history buffer for the sleep diff |
| `system.started` | event | lifecycle | `self.observation{kind: restart}` with continuity facts (uptime gap, last known task) |
| `system.state.changed` | event | lifecycle | Pause: stop model-backed checks; keep heuristic health running |
| `system.tick.idle` | event | schedule | Cheap heuristic drift pass over any task idle-but-in-progress (stall detection) |
| `system.tick.sleep` | event | schedule | Pattern mining, calibration recompute, self-diff, emit summaries |
| `self.model.updated` | event | fact | Refresh the cached self-summary version used in critique prompts |

### 3.2 Messages produced

| Type | Semantics | Payload summary | Consumers |
|---|---|---|---|
| `reflect.health.finding` | event | `{severity: info\|warn\|critical, detail, action_taken?: "reset_requested"\|null, window: [..]}` | persona (reset), interface, worldmodel |
| `reflect.patterns.found` | event | `{window, patterns: [{kind, agent?, task_type?, rate, samples, proposal, subject?}]}` | planning, learning (distillation), worldmodel |
| `reflect.calibration.updated` | event | `{task_type, stated_confidence, empirical_accuracy, brier, bins: [[lo,hi,n,hits]], samples}` | worldmodel, cognition (confidence hints), interface |
| `reflect.drift.detected` | event | `{task_id\|plan_id, kind: goal\|scope\|behavior, evidence: [str], score: 0..1, recommendation: reground\|tighten\|pause\|note}` | planning, guardian, interface |
| `self.observation` | event | `{kind: restart\|change\|limitation\|success\|failure, detail, ref, evidence: [ref], confidence}` | worldmodel, memory |
| `memory.store` | command | `{kind: episodic, content: <critique>, tags: [self_critique, task:<id>], confidence}` | memory |
| `cognition.think` | request | `purpose ∈ {review, self_critique, pattern_mining}`, `require_real_provider: false`, small budgets | cognition |

### 3.3 Request/reply APIs served
None in v1. (A `reflect.status` request for the Interface's vitals is served by the Kernel's generic `system.status` snapshot, to which Reflection contributes `health()` detail.)

### 3.4 Python protocol (`api.py`)

```python
class HealthMonitor(Protocol):                      # port of v1 health.py
    def observe(self, state: PersonaState, source: str, ts: float) -> None: ...
    def inspect(self) -> HealthFinding | None: ...   # pinned extreme / sustained load / oscillation

class DriftTracker(Protocol):                       # one per in-progress task/plan
    def register_goal(self, goal: str, scope_paths: list[str], why: dict[str, str]) -> None: ...
    def observe_step(self, step: TaskStep) -> None: ...
    def heuristic_score(self) -> DriftScore: ...     # no model: scope crossings, repeated tool calls, off-goal file touches
    async def review(self, think: ThinkFn) -> DriftVerdict: ...   # model-backed; falls back to heuristic

class CalibrationTable(Protocol):
    def record(self, task_type: str, stated: float, hit: bool) -> None: ...
    def summary(self, task_type: str) -> Calibration: ...
    async def rebuild(self, ledger: LedgerClient) -> None: ...

class PatternMiner(Protocol):                        # port of ReflectionAgent.reflect()
    def add(self, outcome: OutcomeEvent) -> None: ...
    def mine(self, window_s: float, *, min_rate: float, min_samples: int) -> list[Pattern]: ...

class SelfCritic(Protocol):
    async def critique(self, task: TaskTerminal, trajectory: TrajectorySummary, think: ThinkFn) -> Critique: ...
    # Critique = {what_changed: str, confidence: float, open_questions: [str], lesson: str | None, floor: bool}

class SelfDiffer(Protocol):
    def diff(self, since_ts: float) -> SelfChangeDiff: ...  # from change buffer: patches, skills, competence deltas, limitations added/removed
```

### 3.5 Configuration

| Key (`[reflection]`) | Type | Default | Controls |
|---|---|---|---|
| `health.window` | int | 12 | Persona state transitions kept for inspection (v1 `HealthMonitor` default) |
| `health.extreme` | float | 0.9 | \|valence\| or \|arousal\| ≥ this for `health.pinned_n` transitions → critical |
| `health.pinned_n` | int | 5 | |
| `health.load_ceiling` | float | 0.95 | Sustained cognitive load threshold |
| `health.oscillation_flips` | int | 6 | Sign flips within window → warn (8 → critical) |
| `drift_check_every_steps` | int | 8 | Model-backed drift review cadence per task |
| `drift_heuristic_threshold` | float | 0.5 | Heuristic score above which a model review is requested immediately |
| `drift_emit_threshold` | float | 0.6 | Combined score above which `reflect.drift.detected` is emitted |
| `stall_idle_seconds` | float | 1800 | In-progress task with no step for this long → `behavior` drift `note` |
| `critique_max_tokens` | int | 400 | Budget of the self-critique call |
| `pattern.window_seconds` | float | 86400 | Sleep-time mining window |
| `pattern.min_rate` | float | 0.5 | Failure/correction rate to flag (v1 `ReflectionAgent` threshold) |
| `pattern.min_samples` | int | 3 | |
| `calibration.bins` | int | 10 | |
| `calibration.min_samples` | int | 10 | Below this no `reflect.calibration.updated` is emitted (avoid noise) |

## 4. Data model and Ledger streams

| Stream | Event types | Payload |
|---|---|---|
| `reflect:health` | `finding` | `{severity, detail, window_snapshot, action_taken}` |
| `reflect:drift:<task_id>` | `goal_registered`, `step_seen`, `heuristic`, `review`, `detected`, `closed` | The tracker's evidence trail; `review.verdict ∈ {on_track, drifting, unknown}` |
| `reflect:critique:<task_id>` | `critique` | `{what_changed, confidence, open_questions, lesson, floor, trajectory: {steps, wasted, recovered_errors}}` |
| `reflect:calibration` | `sample`, `snapshot` | `{task_type, stated, hit}` / bins |
| `reflect:patterns` | `mined` | `{window, patterns}` per sleep tick |
| `reflect:self` | `observation`, `diff` | mirrors emitted `self.observation`; `diff` is the sleep-time change record |

Projections: `HealthMonitor` (ring buffer; rebuildable from the last `health.window` `persona.state.changed` events read via Memory or the trace), `CalibrationTable` (snapshotted each sleep tick), `DriftTracker` per open task (rebuilt from `reflect:drift:<id>` on restart), change buffer (rebuilt from `reflect:self` since the last `diff`).

## 5. Internal design

```
service.py
  ├── HealthMonitor            (pure, synchronous; v1 port)          → reflect.health.finding
  ├── DriftService { task_id → DriftTracker }                        → reflect.drift.detected
  │      heuristic every step; model review every N steps / on scope crossing / on idle stall
  ├── CritiqueService          (bounded model call per terminal task) → memory.store, self.observation
  ├── CalibrationTable         (projection)                            → reflect.calibration.updated
  ├── PatternMiner             (sleep tick; v1 ReflectionAgent port)   → reflect.patterns.found
  └── SelfDiffer               (sleep tick)                            → self.observation{change}, reflect:self diff
```

Concurrency: all handlers are cheap and synchronous except the two
model-backed ones (drift review, critique), which run as bounded asyncio
tasks with a semaphore (`max_concurrent_reviews = 2`) so a burst of task
completions never floods Cognition. `start()` rebuilds projections;
`stop()` cancels reviews (their absence is recorded as `review{verdict:
unknown}`); `health()` reports `degraded` if the calibration snapshot is
older than two sleep ticks.

### 5.1 Health (v1 `HealthMonitor`, unchanged semantics)
Window of the last `health.window` states. `critical` if any dimension is
pinned at ≥ `health.extreme` for `health.pinned_n` consecutive transitions,
or cognitive load ≥ `health.load_ceiling` across the window, or ≥ 8 sign
flips; `warn` at 6 flips or 3 pinned. A critical finding carries
`action_taken: "reset_requested"`; Persona performs the reset and emits
the resulting `persona.state.changed{source: "health_reset"}`, which
Reflection recognizes and does not re-inspect (loop guard).

### 5.2 Pattern mining (v1 `ReflectionAgent.reflect` + takeaways)
Over `learn.outcome.recorded` in the window, group by `(task_type, area,
strategy, tool)`; any group with `n ≥ min_samples` and failure-or-
corrected rate ≥ `min_rate` becomes a `Pattern{kind: failure_rate,
proposal: "…keeps failing on…", subject: AGENT_SOURCE_FILES/area}`.
Per-turn takeaways (v1 `reflect_on_outcome`) become `self.observation{kind:
failure, detail}` at the time of the failure, and are counted here.

### 5.3 Self-critique (structured deltas)
On a terminal task event, gather: the task's goal, its `task.step`
summaries, `verify.result` (checklist + trajectory), and the outcome.
One `cognition.think(purpose=self_critique, max_tokens=critique_max_tokens)`
asks for JSON `{what_changed, confidence (0-1), open_questions, lesson}`;
parse leniently (first JSON object in the reply; missing keys → null).
Floor (no provider or unparseable): a template critique built from
mechanical facts only (`what_changed` = verification summary,
`confidence` = null, `lesson` = null, `floor: true`) — recorded as
such, never dressed up. Emit `memory.store{kind: episodic, tags:
[self_critique]}` and `self.observation{success|failure}`. Stated
`confidence` is a calibration sample resolved by the outcome.

### 5.4 Drift detection

```
task.started ──▶ tracker(goal, scope, why) ──▶ each task.step: heuristic h ∈ [0,1]
   h = 0.5·scope_crossings/steps + 0.3·repeated_identical_calls/steps + 0.2·off_goal_touch_ratio
   ├─ h ≥ drift_heuristic_threshold  → immediate model review
   ├─ every drift_check_every_steps  → model review
   └─ action.denied{layer: scope}    → immediate model review
model review: cognition.think(purpose=review): "Goal: …  Declared scope: …  Last K steps: …  Is the next step
   still serving the goal? Answer on_track|drifting|unknown, then one sentence."   (scan for the token; unknown on silence)
combined = 0.5·h + 0.5·(1 if drifting else 0 if on_track else h)
combined ≥ drift_emit_threshold → reflect.drift.detected{kind, evidence, score, recommendation}
   kind: scope  if scope_crossings dominate;  goal if the review said drifting;  behavior if cycles/stall dominate
   recommendation: reground (goal), tighten (scope, repeated crossings), pause (behavior with cycles ≥ 3), note (otherwise)
```

For projects, the same tracker runs at plan level (children as steps),
with `plan.revised` lacking a `reason` counted as a behavior signal
(harness-03 §"treat the plan changed as a loggable event").

### 5.5 Self diff (sleep tick)
From the change buffer since the last diff: patches applied/reverted
(subjects, commits), skills acquired, competence deltas (from
`learn.competence.updated`), limitations added (patterns), calibration
shifts. Emit `self.observation{kind: change, detail: <rendered diff>,
evidence: [refs]}` and append `reflect:self diff`. This is the "what has
changed about me" record the Self Model exposes and Persona can share as
a growth highlight.

## 6. Key behaviors — worked scenarios

**S1 — Scope crossing caught mid-task (Flow 2/3).** Task `t7`
(`patch`, scope `src/memory/**`) issues `action.proposed` for
`read_file src/guardian/policy.py`; Guardian denies `layer=scope`.
Reflection's tracker records a crossing (`h` rises to 0.5) and requests a
review; Cognition replies "drifting — the task is inspecting guardian
policy, unrelated to memory retrieval." Combined 0.75 → `reflect.drift.detected{t7,
kind: scope, recommendation: tighten}`. Planning re-grounds `t7`
(Flow 3), Guardian narrows `t7`'s effective scope to the declared paths
for the rest of the run, Interface shows a notice. All of it is in
`reflect:drift:t7`.

**S2 — Calibration update after a batch of tasks.** Ten patch tasks
completed with critiques stating confidence 0.8; six succeeded. Sleep
tick: bin [0.8,0.9) shows 6/10; Brier 0.24; `reflect.calibration.updated{task_type:
patch, stated_confidence: 0.8, empirical_accuracy: 0.6}`. World Model
records "over-confident on patches by ~0.2" in the Self Model; Cognition
uses the hint to temper stated confidence in future critiques; Curiosity
sees a gap.

**S3 — Restart continuity (Flow 7).** `system.started` arrives; the
last `reflect:self` event is 3 hours old and `task.started{t3}` never
closed. Reflection emits `self.observation{kind: restart, detail: "gap
3h02m; t3 was in progress at step 4"}`; the tracker for `t3` is rebuilt
from `reflect:drift:t3`; when a Worker resumes `t3`, drift checks
continue from step 4, not from zero.

**S4 — Failure: persona pinned and the reviewer is down.** Five
consecutive `persona.state.changed` with valence −0.95 → `critical`
finding with `reset_requested`; Persona resets; Reflection ignores the
`health_reset`-sourced change. Simultaneously a drift review request
times out (provider outage): the tracker records `review{verdict:
unknown}`, the heuristic alone decides (below threshold → no emission),
and nothing is fabricated. `health()` stays `ok`; the outage is
Cognition's to report.

**S5 — The sleep diff.** Since the last diff: 2 patches applied (one
later reverted), 1 skill acquired, `patch:src/memory` competence
0.55→0.71, one new limitation pattern ("web_fetch fails on paywalled
feeds", 4/5). `self.observation{kind: change}` renders these five lines;
Persona later volunteers "I got noticeably better at memory patches this
week, and I've learned I can't read paywalled feeds."

## 7. Design considerations and tradeoffs

- **Observer, never actor** (AGI-04 §7, §9): keeping Reflection out of the action path means it can watch everything, including Guardian denials, without becoming a second policy engine. Cost: it must persuade via events; Planning/Guardian decide what to do with a drift finding.
- **Heuristic first, model second** (harness-03 "bound the exploration budget"; harness-06 gap #3): cheap per-step heuristics run always; a model review runs on cadence or on signal. This bounds Reflection's own cost to roughly one call per N steps plus one per terminal task, and keeps drift detection alive when providers are down.
- **Silence is `unknown`, never `drifting`** (harness-04; v1 milestone 92). A review that doesn't answer contributes the heuristic, not a verdict.
- **Critique as JSON with lenient parsing** rather than free text: cheap to store, joinable for calibration; the floor template exists so the record is complete even when the model isn't (principle 4.5).
- **Calibration needs stated confidence to exist.** `task.step`, `task.completed`, and `verify.result` should carry an optional `confidence` field (contracts note for `03` §4: optional, non-breaking). Without it, calibration falls back to critique-stated confidence only.
- **Reflection can only tighten** (harness-05 §5; harness-06 "graduated trust"). A long streak of good calibration is *reported* to the Self Model; turning that into looser gates is a human `simorgh.toml` change. This is a deliberate asymmetry, not an oversight.
- **v1's autonomous self-patched "self-model diffing" and "confidence tracker"** in `reflection.py` were live-applied but never reviewed for correctness; this spec re-derives both from the harness research rather than porting their code.

## 8. Safety, degradation, and failure modes

- **Provider down / budget exhausted**: critiques become floor templates; drift reviews return `unknown`; health and heuristics continue. No `reflect.drift.detected` is emitted on `unknown` alone.
- **Malformed input**: dropped with a `system.health{degraded}` counter; a tracker never crashes on a missing field (all fields optional in the heuristic).
- **Handler crash**: the tracker for that task is rebuilt from its stream on the next event.
- **Restart mid-review**: the missing `review` is recorded `unknown` at `start()`.
- **Duplicates**: critiques are idempotent by `task_id` (one per terminal event id); calibration samples by `(task_id, source)`.
- **Ledger unavailable**: findings are still emitted on the bus (they are transient signals) but not appended; `health()` → `degraded`.
- **Corrigibility**: `paused` → no model calls; `stopping` → cancel reviews, append `closed{reason: shutdown}` to open trackers. Reflection never blocks shutdown.
- **What Reflection may conclude on its own**: health severities; drift with recommendations `reground|tighten|pause|note`; patterns; calibration; changes and limitations. **What it may never do**: emit `action.proposed`; recommend `loosen`; assert a capability the Ledger has no success evidence for; modify `self:model` directly.
- **Floor**: heuristic drift, health, calibration arithmetic, pattern mining, and the self diff all run with zero providers.

## 9. Testing strategy

- Contract tests for every produced/consumed type; invalid `persona.state.changed` (out-of-range values) is dropped without a finding.
- Unit: `HealthMonitor` (all three critical conditions, warn thresholds, `health_reset` loop guard, window eviction); `DriftTracker` (heuristic arithmetic per component; cadence; immediate review on scope denial; combined-score threshold; `unknown` never emits alone; project-level variant with reasonless `plan.revised`); `CritiqueService` (JSON parse leniency, floor template, calibration sample creation, idempotency); `CalibrationTable` (bins, Brier, `min_samples` gate, rebuild == incremental); `PatternMiner` (v1 `ReflectionAgent` cases: rate threshold, min samples, grouping keys); `SelfDiffer` (buffer boundaries, reverted patch shown as reverted).
- Property/invariant: "no `reflect.drift.detected` without at least one non-`unknown` evidence source"; "calibration rebuild from `reflect:calibration` equals the incremental table"; "Reflection emits zero `action.proposed` in any scenario" (assert on the fake bus).
- Integration: `test_flow_2_drift_and_critique.py` (fake Guardian scope denial → detected → Planning receives), `test_flow_7_restart_observation.py`, `test_flow_8_sleep_calibration_and_diff.py`, `test_health_reset_roundtrip.py` with a fake Persona.
- Fakes: `FakeProvider` scripted with `on_track`/`drifting`/silence; `FakeClock` for cadence and stall timers.

## 10. Build steps

Size **M**; health/patterns (v1 ports) and drift/critique (new) can proceed in parallel.

1. Skeleton; consumes/produces; boundary + contracts tests. Note the optional `confidence` fields as a contracts proposal (`05` §6).
2. Port `HealthMonitor` and its tests; wire `persona.state.changed` → `reflect.health.finding`; `reflect:health` stream.
3. Port `ReflectionAgent`/takeaways as `PatternMiner`; sleep-tick handler; `reflect.patterns.found`.
4. `CalibrationTable` + `reflect:calibration`; samples from critique and `verify.result`; sleep-tick emission.
5. `DriftTracker` heuristic; then model review; `reflect:drift:*`; `reflect.drift.detected`; project-level tracking.
6. `CritiqueService` + `memory.store` + `self.observation{success|failure}`; `SelfDiffer` + `self.observation{change}` + `restart` observation.
7. §8 failure modes; integration scenarios; v1 adapters (`HealthMonitor`, `ReflectionAgent` re-exported); README/EVOLUTION entry.

## 11. Migration notes

| v1 | v2 | Change |
|---|---|---|
| `health.py` `HealthMonitor.inspect/observe`, thresholds | `HealthMonitor` | Same thresholds; reset becomes a request to Persona instead of a direct `PersonaState` write |
| `reflection.py` `ReflectionAgent.reflect`, `reflect_on_outcome`, `TAKEAWAY_KIND`, `AGENT_SOURCE_FILES` | `PatternMiner`, `self.observation{failure}` | Outcomes arrive as `learn.outcome.recorded` instead of `OutcomeLog` reads; proposals become `reflect.patterns.found` for Planning (was `discover_improvements` reading proposals directly) |
| v1 autonomous patches to `reflection.py` (self-model diff, confidence tracker, self-critique deltas) | `SelfDiffer`, `CalibrationTable`, `CritiqueService` | Re-implemented to spec; not ported |
| `main.py` `handle_turn` HealthMonitor wiring | Flow 1 via `persona.state.changed` | None visible |
| Tests: `test_health.py`, `test_reflection.py` | `tests/simorgh/reflection/` | Event-driven fixtures |

## 12. Open questions

1. Should drift reviews use a *different* provider than the one that produced the steps (an independent reviewer, harness-04)? **Default:** request `cognition.think{purpose: review}` and let Cognition's routing prefer a different provider when available; do not hard-require it.
2. Where do per-turn chat critiques go — every chat turn is a task, so critiquing each would be costly. **Default:** critique only `kind ∈ {patch, skill, research, project}`; chat turns get `self.observation` only on `verify.result{fail}` or a Guardian denial.
3. Should a `critical` health finding also pause autonomous work? **Default:** emit `recommendation: pause` as a drift-style hint to Guardian; Guardian decides per its posture rules.

4. Contract gaps and scope simplifications found during the build session (`simorgh/reflection/`, tested — see the package README's build log for detail):
   - `reflect.patterns.found`'s and `reflect.calibration.updated`'s actual schemas (`simorgh/contracts/messages/reflect.py`) are narrower than this spec's own payload-table prose: no per-pattern `task_type` field (patterns carry `kind`/`rate`/`proposal`/optional `agent` only — `task_type` is folded into `proposal`'s text instead), and no `brier`/`bins`/`samples` on the calibration event (those stay internal to `CalibrationTable`/`Calibration`, recorded to the `reflect:calibration` Ledger stream but not published on the bus). Either widen the schemas or accept the narrower wire contract.
   - `action.denied` carries no `task_id` in its current schema, so this build never wired `action.denied{layer: scope}` to a task's `DriftTracker` at all (not even the immediate-review path from §5.4's flow diagram) — `Service.consumes` does not include `ACTION_DENIED`. Needs either a `task_id` added to `action.denied` or an explicit decision that scope-crossing drift signal only ever arrives via a later terminal-task review, never live.
   - `task.started` (`TaskStarted`) carries no goal/scope, so `DriftTracker` registration moved to `task.created` instead (which does carry `description` and optional `scope`) — a strict superset of what was asked for, not a narrowing, but worth confirming as the intended anchor point.
   - `plan.revised`'s `plan_id` is never guaranteed to equal any task's `task_id` in the current contracts, so the project-level tracker described in §5.4's closing paragraph ("the same tracker runs at plan level") is not actually reachable — `_on_plan_revised` is wired but is a documented no-op unless a caller happens to key them the same.
   - Drift review is evaluated once, at task-terminal time over the whole accumulated trajectory, rather than live every `drift_check_every_steps` mid-task — a deliberate scope cut for this build session, not a design change; the heuristic, the combined-score formula, and the never-fabricate-on-`unknown` rule are all implemented exactly as specified.
