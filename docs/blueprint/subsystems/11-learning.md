# 11 — Learning (`simorgh/learning/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). A spec may refine those documents; it
> may not contradict them. If you find a contradiction, fix the governing
> document and note it in `00-README.md`'s changelog.

**Layer:** 3 Growth
**Owner (build):** unassigned
**Status:** draft
**Depends on (contracts only):** `task.completed`, `task.failed`, `task.blocked`, `verify.result`, `action.result`, `action.denied`, `tool.invoked`, `tool.registered`, `research.finding.recorded`, `reflect.patterns.found`, `system.tick.sleep`, `system.state.changed`, `learn.pipeline.run` (command, see §3.1 note), `learn.strategy.suggest` (request)
**v1 code that migrates here:** `src/main.py` (`propose_self_patch`, `propose_patch_batch`, `propose_skill`, `propose_skill_batch`, `_relaunch_or_rollback`, `_attempt_hot_swap`, `_patch_commit_message`), `src/orchestrator/self_patch.py` (`SelfPatchAgent` policy half; `run_isolated_test_suite`, `_docstring_regression_reason`, `check_main_py_invariants` go to Verification; `relaunch` goes to Execution), `src/orchestrator/deployment.py` (`DeploymentManager` promote/rollback policy), `src/agents/skills/research.py` (`SkillResearchAgent` policy half), `src/agents/skills/registry.py`, `src/orchestrator/reflection.py` (`OutcomeLog` only)

## 1. Purpose and responsibilities

Learning is the subsystem that turns *what happened* into *what Simorgh
can do next time*. It is the operational answer to AGI-04 §6's
observation that, with weight-level learning out of scope, "much of what
looks like learning in current agent systems is actually happening in
the memory subsystem" — Learning is where that is made explicit and
disciplined: outcomes become competence estimates and strategy
preferences (procedural memory), research findings become durable
knowledge (semantic memory), working code becomes registered skills, and
audited self-patches change the system's own source. Every one of those
is a real, measurable change to future behavior, and every one leaves a
Ledger record that Reflection and the Self Model read.

**Responsibilities (owns):**
- The outcome pipeline: every finished task becomes a `learn.outcome.recorded` event and updates per-task-type / per-strategy competence tables (`learn:competence`).
- Strategy selection as procedural memory: `learn.strategy.suggest` answers "for this kind of task, what has worked" with an explore/exploit-aware ranking.
- The self-patch pipeline (Flow 4) — the *policy* (attempt budgets, gate order, feedback routing, outcome vocabulary, batch/evolve semantics, revert-on-failed-activation). Never the mechanics of reading, writing, testing, or relaunching.
- The skill library: skill research → audited apply → registration as a load-on-demand tool → usage statistics.
- Experiments: A/B trials via hot-swap, promotion or rollback on evidence.
- Knowledge distillation: research findings and repeated lessons written as reviewable markdown under `docs/KnowledgeBase/distilled/` and stored as semantic memory.

**Explicit non-responsibilities (belongs elsewhere):**
- Deciding whether an action may happen — **Guardian**. Learning proposes; it never approves.
- Reading, writing, committing, reverting, relaunching, hot-swapping, running sandboxes — **Execution** (tools). Learning issues `action.proposed` and consumes `action.result`.
- Deciding whether a candidate is *safe* or *correct* — **Verification** (`verify.requested kind=self_patch|skill`), which includes the denylist/immunity review it obtains from Guardian.
- Deciding *what* to improve — **Curiosity** (candidates) and **Planning** (tasks). Learning is handed a task; it does not invent one.
- Maintaining the Self Model — **World Model**; Learning only emits the events the Self Model folds in.
- Storing memories — **Memory**; Learning sends `memory.store` commands.

**Principles this subsystem is the primary enforcer of** (from `01` §4): 4.4 (append-only outcomes; competence is a projection), 4.5 (an outcome with no real provider is recorded as a floor outcome, never as success), 4.8 (nothing is applied without an independent verification verdict), 4.10 (every applied change is a revertible commit; activation failure reverts), 4.11 (Learning never loosens a gate — a repeated failure tightens attempt budgets, a repeated success never widens scope).

## 2. Position in the architecture

Layer 3. Participates in Flow 2 (outcome recording at the end of every task), Flow 4 (owner of the self-patch sub-flow), Flow 6 (consumes the research finding), Flow 8 (sleep-time competence recomputation and distillation). It imports only `simorgh.contracts`, `simorgh.bus.client`, `simorgh.ledger.client`, and stdlib. It has no filesystem access of its own beyond its Ledger streams; the one apparent exception — writing distilled knowledge to `docs/KnowledgeBase/` — is an `action.proposed(tool=write_file)` like any other write.

## 3. Interfaces

### 3.1 Messages consumed

| Type | Pattern | Semantics | What this subsystem does with it |
|---|---|---|---|
| `task.completed` | event | fact | Join with the task's `verify.result` (by `verification_ref`); append `learn:outcomes`; update competence; emit `learn.outcome.recorded` |
| `task.failed` | event | fact | Same, `succeeded=false`, `terminal` carried through |
| `task.blocked` | event | fact | Recorded as a non-terminal negative sample (weight 0.5) so a task that blocks three times before succeeding is not scored as a clean win |
| `verify.result` | event | fact | Cached by `verification_id` until its task terminates; for `kind=self_patch|skill` it advances the pipeline state machine (§5.2) |
| `action.result` | event | fact | Advances a pipeline waiting on that `action_id` (draft, apply, commit, activate, hot-swap, write_file) |
| `action.denied` | event | fact | A pipeline step denied by Guardian → pipeline outcome `[rejected]` with the Guardian's reasons as `prior_reasons` for the next attempt, or terminal if `layer ∈ {policy, paused}` |
| `tool.invoked` | event | telemetry | Per-skill usage counters (`learn:skills`) |
| `tool.registered` | event | fact | Confirms a skill applied by this subsystem is now callable → `learn.skill.acquired` |
| `research.finding.recorded` | event | fact | Queue for distillation (§5.5) |
| `reflect.patterns.found` | event | fact | A pattern seen ≥ `distill_pattern_threshold` times becomes a distilled lesson |
| `system.tick.sleep` | event | schedule | Recompute competence snapshots; run the distillation queue; emit `learn.competence.updated` for every changed task type |
| `system.state.changed` | event | lifecycle | `paused`/`stopping`: pipelines checkpoint (§8) |
| `learn.pipeline.run` | **command** (group `learning`) | work | Run the self-patch or skill pipeline for one task (§5.2, §5.3). *Contracts note: this command and its completion event `learn.pipeline.completed` are not in the `03` §4.11 catalog and must be added (optional-field-free, new types → non-breaking addition).* |
| `learn.strategy.suggest` | request | query | Reply `learn.strategy.suggest.reply` (§3.3) |

### 3.2 Messages produced

| Type | Semantics | Payload summary | Consumers (informational) |
|---|---|---|---|
| `learn.outcome.recorded` | event | `{task_id, task_type, succeeded, verdict, cost_usd, duration_s, strategy?, confidence?}` | worldmodel, reflection, curiosity |
| `learn.competence.updated` | event | `{task_type, success_rate, calibration, samples, strategies: [{strategy, success_rate, n}]}` | worldmodel, curiosity, planning |
| `learn.skill.acquired` | event | `{name, path, tests}` | worldmodel, persona (growth), interface |
| `learn.self_patch.applied` / `.reverted` | event | `{subject, commit, tests: {baseline, patched}, reason?, activation: hot_swap\|relaunch\|none}` | reflection, worldmodel, persona, interface, memory |
| `learn.experiment.result` | event | `{experiment_id, variant, metric, promoted}` | reflection, worldmodel |
| `learn.pipeline.completed` | event | `{task_id, outcome: applied\|researched\|rejected\|floor, message, artifacts: [ref], attempts}` (*contracts addition*) | orchestration (finishes the task), planning |
| `action.proposed` | event → Guardian | tools: `self_patch.draft`, `skill.draft`, `apply_source_patch`, `apply_skill`, `git_commit`, `git_revert_range`, `relaunch`, `hot_swap`, `write_file` | guardian |
| `verify.requested` | event | `{verification_id, task_id, kind: self_patch\|skill, subject_ref: candidate blob, checklist_hint}` | verification |
| `memory.store` | command | `{kind: semantic\|procedural, content, tags, confidence, source_ref}` | memory |
| `learn.strategy.suggest.reply` | reply | §3.3 | requester |

### 3.3 Request/reply APIs served

**`learn.strategy.suggest`** — request `{task_type, subject?, budget_hint?: {max_cost_usd}}`; reply within 200 ms (pure projection read, no model call):

```json
{"ok": true, "suggestions": [
  {"strategy": {"provider": "claude_code_cli", "purpose": "patch", "edit_mode": "search_replace"},
   "success_rate": 0.71, "n": 17, "mean_cost_usd": 0.04, "score": 0.83, "reason": "best observed; exploration bonus 0.12"},
  {"strategy": {"provider": "gemini", "purpose": "patch", "edit_mode": "full_rewrite"}, "success_rate": 0.40, "n": 5, "score": 0.61, "reason": "under-sampled"}],
 "floor": false}
```
With no samples for `task_type`, `suggestions` is empty and `floor: true` — the caller uses its default. Failure reply `{ok: false, error: {code: "ledger_unavailable", retryable: true}}`.

### 3.4 Python protocol (`api.py`)

```python
class OutcomeRecorder(Protocol):
    async def record(self, task: TaskTerminal, verdict: VerifyResult | None) -> Outcome: ...

class CompetenceTable(Protocol):            # projection over learn:outcomes
    def get(self, task_type: str) -> Competence | None: ...
    def suggest(self, task_type: str, *, explore: float) -> list[StrategyScore]: ...
    def apply(self, event: Event) -> None: ...
    async def rebuild(self, ledger: LedgerClient) -> None: ...

class PatchPipeline(Protocol):              # one instance per task_id, state in learn:patch:<task_id>
    async def run(self, task: TaskRef, *, prior_reasons: list[str] | None) -> PipelineOutcome: ...
    async def on_action_result(self, result: ActionResult) -> None: ...
    async def on_verify_result(self, result: VerifyResult) -> None: ...
    async def checkpoint(self) -> None: ...

class SkillPipeline(PatchPipeline): ...     # same shape; different tools and verification kind

class Distiller(Protocol):
    async def enqueue(self, source: FindingRef | PatternRef) -> None: ...
    async def flush(self, *, budget: Budget) -> list[DistilledRef]: ...

@dataclass(frozen=True)
class Strategy:
    provider: str; purpose: str; edit_mode: str      # the tuple competence is keyed on
```

### 3.5 Configuration

| Key (`[learning]`) | Type | Default | Controls |
|---|---|---|---|
| `max_draft_attempts` | int | 3 | Draft→verify retries within one pipeline run (v1 `DEFAULT_*_MAX_ATTEMPTS`) |
| `max_pipeline_wall_seconds` | float | 900 | Whole-pipeline ceiling; exceeding → `[rejected] timed out`, checkpointed |
| `edit_mode_line_threshold` | int | 100 | Passed to `self_patch.draft`: SEARCH/REPLACE above this |
| `evolve_max_count` | int | 10 | Max patches per `propose_patch_batch` run |
| `hot_swap_slots` | list[str] | `["logic","emotion","skills"]` | Subjects eligible for in-process hot-swap instead of relaunch |
| `hot_swap_trial_requests` | int | 3 | Trial requests run against the cloned slot before promotion |
| `explore_bonus` | float | 0.15 | UCB-style bonus weight in `suggest` |
| `min_samples_for_trust` | int | 5 | Below this a strategy's rate is shrunk toward 0.5 |
| `blocked_sample_weight` | float | 0.5 | Weight of a `task.blocked` negative sample |
| `distill_pattern_threshold` | int | 3 | Repeats of a reflection pattern before it is distilled |
| `distill_dir` | str | `docs/KnowledgeBase/distilled` | Target of distillation writes (must be inside Guardian's writable scope) |
| `skill_dir` | str | `simorgh_skills/` | Where applied skills live (Execution registers this dir) |
| `providers_allowed_for_patch` | list[str] | `[]` (any) | Restrict drafting to specific providers |

Env overrides: `SIMORGH_LEARNING_MAX_DRAFT_ATTEMPTS`, `SIMORGH_LEARNING_EVOLVE_MAX_COUNT`.

## 4. Data model and Ledger streams

| Stream | Event types | Payload |
|---|---|---|
| `learn:outcomes` | `outcome` | `{task_id, task_type, strategy, succeeded, weight, verdict, cost_usd, duration_s, stated_confidence?, ts}` — one per terminal task event; idempotency key = `task_id` + terminal event id |
| `learn:competence` | `snapshot` (via `ledger.snapshot`) | The projection: `{task_type: {n, successes_w, cost_sum, dur_sum, calib_bins: [[lo,hi,n,hits]], strategies: {strategy_key: {n, successes_w, cost_sum}}}}` |
| `learn:patch:<task_id>` | `started`, `draft_proposed`, `draft_result`, `verify_requested`, `verify_result`, `apply_proposed`, `applied`, `commit_result`, `activation_proposed`, `activated`, `reverted`, `attempt_failed`, `checkpoint`, `finished` | The pipeline's own state machine, replayable; `finished.outcome ∈ {applied, rejected, floor, timed_out}` |
| `learn:skills` | `acquired`, `usage`, `retired` | `{name, path, tests, usage_n, last_used}` |
| `learn:experiments:<id>` | `started`, `trial_result`, `promoted`, `rolled_back` | hot-swap trials |
| `learn:distill` | `enqueued`, `written`, `skipped` | `{source_ref, target_path, sha256}` |

Projections: `CompetenceTable` (rebuilt from `learn:outcomes`, snapshotted every sleep tick), `SkillIndex` (from `learn:skills`), `PipelineState` (from `learn:patch:<id>`; a pipeline resumes from its last event on restart). No state outside the Ledger except an in-memory cache of the competence table.

**Competence math.** For task type *t* and strategy *s*: weighted success rate `p = (successes_w + 1) / (n + 2)` (Laplace), shrunk toward 0.5 when `n < min_samples_for_trust` by `p' = (n·p + k·0.5)/(n + k)`, `k = min_samples_for_trust`. Suggest score `= p' + explore_bonus · sqrt(ln(N_t + 1) / (n_s + 1))` (UCB1 shape; `N_t` = total samples for *t*). Calibration is a 10-bin table of stated confidence vs hit rate, plus Brier score; both are also what Reflection reads (12).

## 5. Internal design

```
service.py ── OutcomeRecorder ──▶ learn:outcomes ──▶ CompetenceTable ──▶ learn.competence.updated
          ├── PipelineManager { task_id → PatchPipeline | SkillPipeline }   (asyncio tasks, one per run)
          │       └── steps issue action.proposed / verify.requested and await correlated results
          ├── ExperimentRunner (hot-swap trials)
          ├── Distiller (queue + sleep-time flush)
          └── StrategyService (learn.strategy.suggest)
```

Concurrency: one asyncio task per running pipeline, bounded by
`max_concurrent_pipelines` (default 2 — self-patches share the repo);
results are routed by `action_id`/`verification_id` → pipeline via a
correlation map persisted as `checkpoint` events. `start()` rebuilds
projections and resumes any `learn:patch:*` stream whose last event is
not `finished`. `stop()` checkpoints and cancels. `health()` is
`degraded` if the Ledger is unreachable or any pipeline exceeded its
wall clock.

### 5.1 Outcome recording
`task.completed|failed|blocked` → look up the cached `verify.result`
(or, if it arrives later, join on `verification_ref`) → derive
`task_type` (`task.kind`, plus `subject` area for patches: `patch:src/memory`)
and `strategy` (from the task's `learn:patch:<id>` stream if it ran
here, else `task.completed.artifacts` metadata, else `unknown`) → append
→ `learn.outcome.recorded`. A `[floor]` outcome (no real provider) is
recorded with `succeeded=false, weight=0` — it counts for nothing
either way (principle 4.5).

### 5.2 Self-patch pipeline (Flow 4) — state machine

```
IDLE ─learn.pipeline.run─▶ DRAFTING ─action.result(ok)─▶ VERIFYING ─verify.result(pass)─▶ APPLYING
  ▲                          │ result.err / denied                │ fail + attempts<max            │ action.result(ok)
  │                          ▼                                   ▼                                 ▼
  │                    attempt++ ── prior_reasons ──▶ DRAFTING   (feedback = verify.feedback)   COMMITTING
  │                          │ attempts == max                                                    │ ok (or "nothing to commit" → see §8)
  │                          ▼                                                                    ▼
  └────────────────── FINISHED(rejected) ◀──── verify.result(fail, attempts==max)         ACTIVATING
                                                                                                │ hot_swap ok | relaunch self-check ok
                                                                                                ▼
                                                                    FINISHED(applied) ◀─── RECORDED ─── learn.self_patch.applied
                                                                    (activation failed) ─▶ REVERTING ─git_revert_range─▶ FINISHED(rejected) + learn.self_patch.reverted
```

Step details (each an `action.proposed` with `reversibility` set honestly):
1. **DRAFTING** — `tool=self_patch.draft`, `args={subject, description, prior_reasons, max_steps: 6, edit_mode_line_threshold}`, `reversibility=read_only`, `scope.paths=[subject, "src/**", "docs/**"]`. The tool (spec 08) runs the READ/LIST/DRAFT loop with `_FINAL_TURN_HINT`, SEARCH/REPLACE for large files, and returns `{candidate_ref, provider, reasons?}`; `reasons` non-empty means a retryable draft failure (invalid Python, docstring regression, edit blocks didn't apply). `floor: true` → FINISHED(floor) immediately — retrying a deterministic template is pointless (v1 lesson).
2. **VERIFYING** — `verify.requested kind=self_patch, subject_ref=candidate_ref, checklist_hint={description, subject}`. Verification (10) runs Guardian review (denylist, immunity, protected subject), docstring-regression, `main.py` invariants, and the isolated full test suite. `fail` with `feedback` → next attempt with `prior_reasons=[feedback]`; `insufficient_evidence` → treated as fail *without* consuming an attempt more than once (a reviewer that cannot judge is not evidence against the draft — harness-04).
3. **APPLYING** — `tool=apply_source_patch`, `reversibility=reversible`, `scope.paths=[subject]`. Guardian re-checks protected subjects here (defense in depth, principle 4.3).
4. **COMMITTING** — `tool=git_commit`, args `{paths:[subject], message: _patch_commit_message(...)}`. Never push.
5. **ACTIVATING** — if `subject` ∈ `hot_swap_slots`: `tool=hot_swap` with `{slot, module_path, trial_requests}`; else `tool=relaunch` (self-check subprocess, then exec). `reversibility=reversible` because the previous commit is the rollback point.
6. **REVERTING** — on activation failure: `tool=git_revert_range` from the pre-pipeline HEAD (recorded at `started`). The candidate file is thereby restored on disk too.
7. **RECORDED** — `learn.self_patch.applied|reverted`, `memory.store kind=episodic`, `learn.pipeline.completed`.

`propose_patch_batch` (evolve) is `EvolvePipeline`: brainstorm targets (`cognition.think` via the same draft tool in `mode=brainstorm`), run N single pipelines with `activation=none`, then one activation; on self-check failure `git_revert_range` reverts *every* commit of the batch together (v1's `revert_commits_since`), and each child outcome is re-recorded as reverted.

### 5.3 Skill pipeline
Same machine with `tool=skill.draft` (READ/DRAFT loop, port of `SkillResearchAgent`), `verify.requested kind=skill` (Guardian review + sandboxed smoke run — the sandbox check applies to *skills only*, v1 milestone 84), `tool=apply_skill` (scope `skill_dir`), `git_commit`, no activation. On `tool.registered` for the new module → `learn.skill.acquired`. `batch <count> <theme>` is a fan-out of N skill pipelines sharing one brainstorm.

### 5.4 Experiments
`ExperimentRunner.start(slot, candidate_ref, metric)` → `hot_swap` with `trial=true`: Execution clones slot state, runs `hot_swap_trial_requests` synthetic requests, returns per-request outcomes; Learning compares `metric` (success rate, latency) to the incumbent's recorded competence; promote (`hot_swap trial=false`) or rollback; `learn.experiment.result`.

### 5.5 Distillation
Queue sources: `research.finding.recorded` (always), `reflect.patterns.found` whose `(kind, agent)` has recurred ≥ `distill_pattern_threshold`. On sleep tick, per item: one bounded `cognition.think(purpose=distill)` producing a short markdown note with a Sources line → `action.proposed(tool=write_file, path=distill_dir/<slug>.md, reversibility=reversible)` → `git_commit` → `memory.store kind=semantic, tags=[distilled, <area>]`. Floor: skip (never write a template note). Duplicates are prevented by `sha256` of the source ref in `learn:distill`.

### 5.6 Outcome vocabulary → messages

| v1 string | `learn.pipeline.completed.outcome` | Also emits |
|---|---|---|
| `[APPLIED] … committed (not pushed)` | `applied` | `learn.self_patch.applied` / `learn.skill.acquired` |
| `[APPLIED] … NOT committed: …` | `applied` with `artifacts.commit=null` and `message` carrying the git output (see §8 on the "nothing to commit" anomaly) | same |
| `[REVERTED] …` | `rejected` (`reason=activation_failed`) | `learn.self_patch.reverted` |
| `[rejected after N attempt(s)] …` | `rejected` | — |
| `[rejected] isolated test suite did not pass` | `rejected` | — |
| `no real drafting intelligence available` | `floor` | — |
| `[RESEARCHED] …` | (owned by Orchestration/Flow 6; Learning only distills) | — |

Orchestration maps `applied|researched → task.completed`, `rejected → task.blocked|failed` per Planning's retry policy, `floor → task.blocked (retry_after = provider backoff)`.

## 6. Key behaviors — worked scenarios

**S1 — A clean self-patch (Flow 4).** Worker claims task `t1` (`kind=patch`, subject `src/memory/retrieval.py`, "add recency weighting") → `learn.pipeline.run{t1}`. Learning appends `started{head=abc123}`, proposes `self_patch.draft`; Guardian approves (read-only, in scope); result `{candidate_ref: blob:9f…, provider: claude_code_cli}`; `verify.requested kind=self_patch`; Verification replies `pass` with `mechanical.tests={baseline: 889, patched: 892}`; `apply_source_patch` approved and applied; `git_commit` → `commit: def456`; subject not a hot-swap slot → `relaunch`; Execution's self-check exits 0 and execs. On restart, Learning rebuilds `learn:patch:t1`, sees `activation_proposed` without `activated`, checks `git_state` via `world.env.query` (HEAD == def456, process uptime small) → appends `activated`, emits `learn.self_patch.applied`, `learn.pipeline.completed{applied}`. Orchestration completes `t1`; `task.completed` returns to Learning as an outcome with `strategy={claude_code_cli, patch, search_replace}`.

**S2 — Draft rejected, retried with feedback, then succeeds.** Attempt 1 verify → `fail`, feedback "the original module docstring (412 chars) is missing in your draft". Learning appends `attempt_failed`, re-proposes `self_patch.draft` with `prior_reasons=[…]`. Attempt 2 passes. Outcome `applied`, `attempts=2`; the competence sample records `attempts` so Reflection can see that this strategy tends to need a retry.

**S3 — Skill acquisition.** `learn.pipeline.run{t2, kind=skill, description="tf-idf keyword extractor"}` → `skill.draft` → `verify kind=skill` (sandbox smoke run passes) → `apply_skill` writes `simorgh_skills/tf_idf_keyword_extractor.py` → `git_commit` → Execution's registry scan emits `tool.registered{name, provider=skill, read_only=true}` → Learning emits `learn.skill.acquired`; later `tool.invoked` events increment its usage.

**S4 — Failure: activation fails and the batch is reverted.** `evolve 3 "faster retrieval"` → three pipelines apply and commit (`c1,c2,c3`) with `activation=none`; the final `relaunch` self-check fails (`ModuleNotFoundError` in a patched module). Learning proposes `git_revert_range{from: head_before}`; Execution reverts as three new commits; Learning re-records each child as `reverted`, emits `learn.self_patch.reverted ×3` and `learn.pipeline.completed{rejected, reason: activation_failed}`; Persona receives a growth notice that says so plainly; the three outcome samples are negative, and `learn.competence.updated` lowers the strategy's rate.

**S5 — Degradation: paused mid-pipeline.** `system.state.changed{paused}` arrives while `t1` is VERIFYING. Learning appends `checkpoint`, stops awaiting; Guardian denies any new proposal. On `resume`, the pipeline re-issues only the step whose result never arrived (verification is idempotent by `verification_id`).

## 7. Design considerations and tradeoffs

- **Policy here, mechanics in Execution** (harness-01 "minimal scaffolding, maximal operational harness"; AGI-04 §5/§9). Splitting `SelfPatchAgent` into a tool (draft loop) and a pipeline (attempt policy) costs one extra message hop per step, but it is what makes "Learning can never write a file" a structural fact rather than a convention, and lets the draft tool be tested with a fake provider independently of retry policy.
- **Competence as procedural memory, not weight updates** (AGI-04 §6, AGI-03 §3). The honest limit: this learns *which strategy to pick*, not *how to be better at the strategy*. That is stated in the Self Model rather than hidden.
- **UCB exploration in `suggest`** vs pure greedy: greedy locks in the first strategy that ever worked (the same thematic collapse seen in idea generation, harness-06); the bonus keeps under-sampled strategies alive at a bounded cost (`explore_bonus` is small and Curiosity can lower it under budget pressure).
- **Bounded attempts with feedback, then give up** (harness-04 "bounded retry with an explicit terminal state"). Three attempts inside one run, and Planning's blocked-retry rounds outside it, are two different budgets on purpose: the inner one iterates while context is hot (harness-06 gap #5), the outer one lets a fresh round try later.
- **`insufficient_evidence` does not consume an attempt twice** (harness-04 "non-answers must never be silently graded as failures"). It costs one re-verify, not a re-draft.
- **Whole-batch revert for evolve** (harness-04 "rollback when a multi-step effort fails partway") — accepted cost: a batch where only the last patch broke activation loses the good ones too; the alternative (bisecting) is a Phase-5 refinement.
- **Distillation writes are reversible git commits under a reviewable path** rather than opaque memory rows (principle 4.12; harness-01 "transparent, file-based memory"). Cost: one model call per note at sleep time, bounded by the sleep tick's budget.

## 8. Safety, degradation, and failure modes

- **Provider down / budget exhausted**: the draft tool returns `floor: true` → `[floor]`, no attempt consumed, `task.blocked` with `retry_after` from `cognition.provider.status`. Never a fabricated draft.
- **Guardian denies a step**: `layer ∈ {policy, protected, paused}` is terminal for this task (`rejected`, reasons recorded); `layer ∈ {budget, scope}` is retryable after backoff.
- **Malformed `action.result`**: nack; pipeline stays in its state; after `max_deliveries` the pipeline finishes `rejected(reason=transport)`.
- **Handler crash**: the pipeline task dies; `start()`/a supervisor tick resumes from `learn:patch:<id>`'s last event.
- **Restart mid-activation** (S1) is resolved by consulting git state, never by re-applying.
- **Duplicate messages**: every step result is idempotent by `action_id`/`verification_id`; a duplicate `task.completed` is dropped by outcome idempotency key.
- **Ledger unavailable**: pipelines refuse to start (`nack, retry_after=30`); outcomes buffer in memory up to 1,000 then drop with `system.health degraded`.
- **The "nothing to commit" anomaly** (v1 milestone 93): the `git_commit` tool (08) must compare the written file's sha256 to HEAD before committing and report `{changed: bool}`; Learning records both cases and treats `changed=false` as `applied` with `commit=null` — the content is on disk and will ride the next commit to that file — but flags `learn.self_patch.applied{commit: null}` so Reflection can count recurrences.
- **Corrigibility**: on `paused`, checkpoint and idle; on `stopping`, checkpoint and cancel; a pipeline never holds a lock that would block shutdown. Learning never proposes an action that modifies `guardian/`, `execution/`, `contracts/`, `kernel/`, or `docs/SOUL.md` — Guardian denies it anyway (protected subjects), but Learning refuses first so the denial never appears as a "bug."
- **Floor**: with no provider, Learning still records outcomes, serves `suggest`, and registers skills already on disk. It just cannot draft anything.

## 9. Testing strategy

- Contract tests: every produced type (§3.2) validates; handler tests for each consumed type with valid/invalid payloads (invalid → nack, no Ledger append).
- Unit: `CompetenceTable` (Laplace + shrinkage + UCB ordering; rebuild from log equals incremental apply; snapshot/restore), `OutcomeRecorder` (join with late `verify.result`; blocked weight; floor weight 0), `PatchPipeline` state machine (every transition in §5.2, driven by fake results; attempts exhausted; insufficient_evidence not double-charged; paused checkpoint/resume; restart after `activation_proposed`), `EvolvePipeline` whole-batch revert, `Distiller` (threshold, sha dedupe, floor skip), vocabulary mapping table.
- Property/invariant: "an `applied` outcome always has a preceding `verify.result{pass}` in its stream"; "no pipeline ever emits `action.proposed` with `tool ∈ {write_file, apply_*}` before a `verify_result{pass}` event"; "competence rebuild is order-independent for commutative events".
- Integration: `test_flow_4_self_patch.py` (fake Guardian that approves in-scope read-only and reversible actions, fake Execution tools, fake Verification), `test_flow_8_sleep_competence.py`, `test_evolve_batch_revert.py`, `test_pause_mid_pipeline.py`.
- Fakes: `FakeProvider` via the draft tool fake, `FakeClock` for wall-clock ceilings. No real git in unit tests; the git tool fake records calls.

## 10. Build steps

Size **L**; steps 2–3 and 4–6 parallelizable by two agents (outcomes/competence vs pipelines).

1. Skeleton (`service.py` with consumes/produces, `config.py`, README); register in kernel; boundary + contracts tests pass. *(Contracts addition first: `learn.pipeline.run`, `learn.pipeline.completed` per `05` §6.)*
2. `learn:outcomes` + `CompetenceTable` + `OutcomeRecorder`; `learn.outcome.recorded`, `learn.competence.updated`; `StrategyService`. Tests. Port `OutcomeLog` semantics.
3. `PatchPipeline` state machine with fake tools/verification; checkpoint/resume; `learn:patch:*` stream. Port `propose_self_patch` policy, `_patch_commit_message`, attempt/feedback logic.
4. `EvolvePipeline` (whole-batch revert) and `SkillPipeline`; port `propose_patch_batch`, `propose_skill`, `propose_skill_batch`, registry hooks.
5. `ExperimentRunner` (port `DeploymentManager` promote/rollback semantics; the swap itself is Execution's tool).
6. `Distiller` + sleep tick handling.
7. §8 failure modes; integration scenarios; v1 adapters in `src/main.py` delegating to `learn.pipeline.run`; README/EVOLUTION entry.

## 11. Migration notes

| v1 | v2 component | Behavior change |
|---|---|---|
| `propose_self_patch` (attempt loop, printing, commit, relaunch/hot-swap decision) | `PatchPipeline` | Printing → `ui.notice` via Orchestration's step events; every gate a message; identical attempt semantics |
| `propose_patch_batch` | `EvolvePipeline` | Identical revert-range behavior |
| `SelfPatchAgent.draft_patch` | split: policy here, loop → Execution tool `self_patch.draft` | None |
| `run_isolated_test_suite`, `_docstring_regression_reason`, `check_main_py_invariants` | Verification (10) | Called via `verify.requested`, not directly |
| `relaunch`, `DeploymentManager.hot_swap` | Execution tools; promote/rollback policy here | None |
| `propose_skill*`, `SkillResearchAgent` | `SkillPipeline`; loop → tool `skill.draft` | Sandbox check remains skills-only |
| `OutcomeLog` | `learn:outcomes` | Same fields plus strategy/weight |
| Tests: `TestProposeSelfPatch*`, `TestEvolve*`, `TestProposeSkill*`, `test_self_patch.py` policy tests | `tests/simorgh/learning/` | Driven by fake messages instead of fake agents |

## 12. Open questions

1. Should `learn.strategy.suggest` be consulted by Orchestration automatically for every patch task, or only when Planning marks a task `strategy: auto`? **Default:** automatically, with the task able to pin a strategy.
2. Should distilled notes be proposed as a *research-reviewed* write (Verification `kind=doc`) before commit? **Default:** no in Phase 3 (reversible commit is enough); add in Phase 4 if low-quality notes appear.
3. Bisecting a failed evolve batch instead of reverting all. **Default:** revert all; revisit in Phase 5.
4. Task-type granularity for competence (`patch` vs `patch:src/memory` vs per-file). **Default:** both `kind` and `kind:area`, with `suggest` backing off to the coarser key when the fine one has < `min_samples_for_trust`.
