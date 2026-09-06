# 07 — Planning (`simorgh/planning/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). A spec may refine those documents; it
> may not contradict them. If you find a contradiction, fix the governing
> document and note it in `00-README.md`'s changelog.

**Layer:** 2 Agency
**Owner (build):** unassigned
**Status:** built (`simorgh/planning/`; unit + integration tests passing — see section 9/12)
**Depends on (contracts only):** `intent.goal.stated`, `task.claim`, `task.started`, `task.step`, `task.paused`, `task.completed`, `task.failed`, `task.blocked`, `plan.proposed` (own), `plan.reviewed`, `ui.prompt.answered`, `curiosity.candidate`, `research.finding.recorded`, `system.tick.second`, `system.tick.idle`, `system.state.changed`, `cognition.think.reply`, `world.env.query.reply`
**v1 code that migrates here:** `src/orchestrator/tasks.py`, `src/orchestrator/projects.py`, `src/orchestrator/discovery.py`, and from `src/main.py`: `run_task` (status transitions only), `_next_task`, `_resolve_project_task`, `_maybe_roll_up_project`, `_reconsider_blocked_tasks`, `_run_project_task`, `plan_goal`, `_creative_agenda_already_covered`, `MAX_TASK_ATTEMPTS`, `MAX_BLOCKED_RETRY_ATTEMPTS`

## 1. Purpose and responsibilities

Planning is the system's durable intention. It turns goals into a
hierarchical, dependency-aware backlog of tasks, decides which task is
ready to be worked next, hands work to Workers under a lease, tracks
every status transition as an append-only event, computes project rollups
as pure projections, and — for work whose steps cannot be enumerated up
front — runs an explicit plan phase that produces a reviewable, durable
plan artifact before any child executes. It is the deliberative outer
loop from `AGI-04 §4`; Orchestration is the reactive inner loop.

**Responsibilities (owns):**
- The `Task` and `Project` models and their Ledger streams (`task:<id>`,
  `project:<id>`, `plan:<id>`).
- The task status machine, attempt counting, bounded blocked-retry, and
  the terminal give-up policy.
- Claiming with leases (exactly-one-claimant via Ledger CAS) and lease
  expiry re-emission.
- The dependency DAG: validation, readiness, propagation of success and
  failure through dependents.
- Plan Mode: plan artifacts, review routing, approval policy, revision
  with reasons, child creation with edges.
- Project decomposition (the prompt and parser), re-grounding checks,
  rollup projection, stalled-state detection.
- Fuzzy deduplication of incoming candidates against every known task.
- Translating `intent.goal.stated` into a task or a project.

**Explicit non-responsibilities (belongs elsewhere):**
- Running a task's steps, calling tools, or holding a turn's context —
  **Orchestration**.
- Deciding whether an action is permitted — **Guardian**.
- Judging whether a plan or a result is good — **Verification** (Planning
  only routes and applies the verdict).
- Choosing *what* to explore when the backlog is empty — **Curiosity**
  (Planning receives candidates; it does not generate them).
- Rendering the backlog to a human — **Interface** (Planning answers
  `system.status.request` contributions and emits events).

**Principles this subsystem is the primary enforcer of** (`01` §4):
4.4 (append-only state; rollups are projections), 4.7 (plan before you
act; re-ground while you act), and the "plan changed is a loggable event"
half of 4.12.

## 2. Position in the architecture

Layer 2. Participates in flows 2 (autonomous tick → task), 3 (project
lifecycle), 5 (pause: tasks park), 6 (research follow-up task creation),
7 (crash/resume via lease expiry), 8 (consolidation → new tasks from
`reflect.patterns.found`), and 9 (candidate intake with dedupe). Imports
only `simorgh.contracts`, `simorgh.bus.client`, `simorgh.ledger.client`,
and stdlib. Planning never imports Orchestration; the Worker is a
consumer of Planning's events and a requester of `task.claim`.

## 3. Interfaces

### 3.1 Messages consumed

| Type | Pattern | Semantics | What Planning does with it |
|---|---|---|---|
| `intent.goal.stated` | event | fact | creates a `project` task (mode=plan) if `wants_project`, else a single task of inferred kind |
| `curiosity.candidate` | event | fact | fuzzy-dedupes against all task descriptions; creates a `patch`/`research` task or drops with `ui.notice(level=debug)` |
| `task.claim` | request (`task.claim.reply`) | req/rep | CAS-appends `claimed` with a lease; grants or refuses |
| `task.started` | event | fact | transition `claimed → in_progress`, refresh lease |
| `task.step` | event | fact | refresh lease (`lease_until = now + lease_seconds`); no other state |
| `task.paused` | event | fact | transition to `paused`, record `resume_from_step` |
| `task.completed` | event | fact | transition to `completed`; propagate to dependents and parent rollup |
| `task.failed` | event | fact | if `terminal` → `failed`; else attempt accounting → `available` or `blocked` |
| `task.blocked` | event | fact | transition to `blocked`, schedule reconsideration |
| `plan.reviewed` | event | fact | apply verdict: approve → children; revise → bounded replan; reject → task failed; insufficient_evidence → treated as revise once, then human |
| `ui.prompt.answered` | event | fact | resolves a pending human approval (`prompt_id` ↔ `plan_id`) |
| `research.finding.recorded` | event | fact | if `follow_up` present, create a child `patch` task under the research task |
| `reflect.patterns.found` | event | fact | port of `discover_improvements`: each pattern's proposal becomes a `patch` task (deduped) |
| `system.tick.second` | event | tick | lease-expiry scan, stalled detection, reconsideration timers |
| `system.tick.idle` | event | tick | if any task is `available`, re-emit `task.available` for the highest-priority ready one (idempotent) |
| `system.state.changed` | event | fact | `paused`: stop emitting `task.available`; `stopping`: same and flush |
| `cognition.think.reply` | reply | rep | decomposition and re-grounding answers (correlated) |
| `world.env.query.reply` | reply | rep | file listing for decomposition prompts |

### 3.2 Messages produced

| Type | Semantics | Payload summary | Consumers |
|---|---|---|---|
| `task.created` | event | full `Task` (see §4) | orchestration, guardian (mode projection), interface, reflection |
| `task.available` | command (group `workers`) | `{task_id, kind, lease_seconds}` | orchestration Workers |
| `task.claim.reply` | reply | `{granted, lease_until, task}` or `{granted:false, reason}` | requester |
| `task.dependency.satisfied` | event | `{task_id, satisfied_by}` | orchestration, interface |
| `task.failed` (re-emitted with `terminal: true` on give-up) | event | `{task_id, reason, terminal, attempts}` | learning, reflection, interface |
| `task.blocked` (with `retry_after`) | event | `{task_id, reason, retry_after}` | interface, reflection |
| `plan.proposed` | event | `{plan_id, task_id, goal, steps[], risk, estimated_cost}` (Planning emits this on behalf of the plan-mode Worker's result — see §5.4) | verification, interface |
| `plan.approved` | event | `{plan_id, approved_by, children}` | orchestration, interface, learning |
| `plan.revised` | event | `{plan_id, reason, diff}` | interface, reflection, ledger |
| `plan.reground` | request (`cognition.think` wrapper) | `{plan_id, task_id, changes_since}` | cognition (Planning issues `cognition.think(purpose=reground)` and republishes the answer as `plan.reground.reply` for observability) |
| `project.completed` / `project.failed` | event | `{project_id, done, total, summary}` | learning, reflection, interface, persona |
| `ui.prompt` | command | `{prompt_id, question, options, default, timeout_s}` | interface (human approval) |
| `ui.notice` | event | dedupe drops, stalled warnings, give-ups | interface |
| `cognition.think` | request | decomposition / re-grounding prompts | cognition |
| `world.env.query` | request | `{what: file_index}` | worldmodel |

### 3.3 Request/reply APIs served

- **`task.claim` → `task.claim.reply`.** Timeout expectation 2 s. Grants
  iff the task's projected status is `available`, no unexpired lease
  exists, and the CAS append succeeds. Refusal reasons:
  `not_available`, `leased_to_other`, `unknown_task`, `paused`.
- **`system.status.request`** contribution (via Kernel aggregation):
  `{backlog: {available, in_progress, blocked, stalled, paused}, projects: [{id, rollup, done, total}]}`.

### 3.4 Python protocol (`api.py`)

```python
class TaskStore(Protocol):
    async def create(self, spec: TaskSpec) -> Task
    async def get(self, task_id: str) -> Task | None
    async def transition(self, task_id: str, status: Status, *, note: str = "", attempt: bool = False,
                         expected_seq: int | None = None) -> Task
    async def claim(self, task_id: str, worker_id: str, lease_seconds: float) -> ClaimResult
    async def children(self, parent_id: str) -> list[Task]
    async def ready(self, *, limit: int = 10) -> list[Task]          # available AND all deps completed
    async def unfinished(self) -> list[Task]

class DependencyGraph(Protocol):
    def validate(self, task_id: str, depends_on: list[str], known: Mapping[str, Task]) -> None  # raises CycleError/UnknownDependency
    def dependents_of(self, task_id: str) -> list[str]
    def is_ready(self, task: Task, known: Mapping[str, Task]) -> bool

class Decomposer(Protocol):
    async def decompose(self, goal: str, files: list[str], count: int) -> list[Step]
    def parse_steps(self, text: str, expected: int) -> list[Step]       # port of parse_project_steps

def project_status(children: Sequence[Task]) -> Status                     # pure; port of v1
def is_duplicate(candidate: str, existing: Iterable[str], threshold: float) -> bool  # port of _creative_agenda_already_covered
```

### 3.5 Configuration (`[planning]`)

| Key | Type | Default | Controls |
|---|---|---|---|
| `lease_seconds` | float | 600 | claim lease; refreshed on every `task.step` |
| `max_task_attempts` | int | 3 | attempts within one round before `blocked` (v1 `MAX_TASK_ATTEMPTS`) |
| `max_blocked_retries` | int | 9 | total attempts before terminal `failed` (v1 `MAX_BLOCKED_RETRY_ATTEMPTS`) |
| `blocked_retry_delay_seconds` | float | 300 | minimum wait before a blocked task is reconsidered |
| `dedupe_similarity_threshold` | float | 0.45 | `difflib.SequenceMatcher` ratio above which a candidate is a duplicate |
| `project_step_count` | int | 4 | steps requested from decomposition |
| `max_plan_revisions` | int | 2 | replans allowed before a plan is rejected |
| `auto_approve_max_risk` | `low\|medium\|high` | `medium` | plans at or below this risk auto-approve after a passing review |
| `human_approval_timeout_seconds` | float | 3600 | unanswered `ui.prompt` → plan stays `awaiting_human`, task `paused` |
| `regrounding_age_seconds` | float | 21600 | a child older than this is re-grounded before being made available |
| `reground_after_sibling_failure` | bool | true | re-ground remaining children when any sibling fails terminally |
| `stalled_after_seconds` | float | 1800 | blocked with no retry scheduled, or in_progress past lease with no worker → `stalled` |
| `priority_weights` | table | `{human: 3, reflection: 2, curiosity: 1}` | ordering among ready tasks |
| `SIMORGH_PLANNING_LEASE_SECONDS` | env | — | override for `lease_seconds` |

## 4. Data model and Ledger streams

```python
@dataclass(frozen=True)
class Task:
    id: str; kind: Literal["chat","patch","skill","research","project"]
    description: str; subject: str | None
    mode: Literal["plan","execute"]; risk: Literal["low","medium","high"]
    origin: Literal["human","curiosity","reflection","research","project","planner"]
    parent_id: str | None; depends_on: tuple[str, ...]
    status: Status; attempts: int; note: str
    lease: Lease | None                      # {worker_id, until}
    created_at: float; updated_at: float; priority: int
    scope: Scope | None                      # {paths: [...], network: bool} — derived from subject/parent (see §12 Q1)
    plan_id: str | None                      # for kind=project
```

**Streams**

- `task:<id>` — events: `created` (full spec), `available`, `claimed {worker_id, until}`,
  `lease_refreshed`, `lease_expired`, `status_changed {status, note, attempt}`,
  `dependency_satisfied {by}`, `dependency_failed {by}`, `regrounded {still_valid, reason}`.
  v1's `task_event` records map onto `created`/`status_changed` one-to-one, so
  `simorgh migrate-v1` is a straight replay.
- `project:<id>` — `created {goal, origin}`, `decomposed {plan_id, children}`, `rollup_changed {status, done, total}` (appended only on change, and only for terminal rollups — see §5.3).
- `plan:<id>` — `proposed {steps...}`, `reviewed {verdict, checklist}`, `awaiting_human {prompt_id}`, `approved {by, children}`, `revised {reason, diff}`, `rejected {reason}`.
- `planning:index` — a compaction stream: every 500 task events Planning
  writes a `snapshot` of `TaskIndex` (id → status, deps, lease, parent) so
  rebuild is O(snapshot + tail), not O(all history).

**Projections**

- `TaskIndex.apply(event)` / `rebuild(ledger)` — the in-memory map used
  for readiness, leases, and dedupe (`descriptions` set).
- `ProjectRollup` — `project_status(children)` computed on read; the
  `rollup_changed` event exists only to make terminal transitions
  visible to consumers, never as the source of truth.
- `PlanState` — current plan version, revisions used, pending prompt.

Only caches (readiness heap, dedupe descriptions) live outside the
Ledger; both are rebuilt from `TaskIndex`.

## 5. Internal design

```
planning/
  service.py        Service: wiring, background loops (leases, stalled, reconsideration)
  model.py          Task, Step, Plan dataclasses; Status enum; transitions table
  store.py          TaskStore over Ledger; CAS claim; snapshot cadence
  dag.py            DependencyGraph: validate (DFS cycle check), readiness, propagation
  rollup.py         project_status (pure) + ProjectRollup projection
  planmode.py       plan artifact lifecycle, approval policy, revision diff
  decomposer.py     prompt + parser (port of decompose_project/parse_project_steps)
  reground.py       staleness rule + prompt + answer parsing
  intake.py         intent.goal.stated / curiosity.candidate / reflect.patterns.found → tasks; dedupe
  scheduler.py      ready-task selection, priority, task.available emission (idempotent)
```

### 5.1 Status machine

```
                 ┌────────────────────────────────────────────────────────────┐
                 ▼                                                            │
 created ──▶ available ──claim──▶ claimed ──task.started──▶ in_progress ──────┤
   │             ▲                  │ lease expired            │  │  │        │
   │   deps not  │                  └────────────────▶─────────┘  │  │ task.paused
   │   ready     │ reconsider (bounded)                           │  ▼
   │             │                                                │ paused ──resume──▶ available
   ▼             │                                                │
 pending ────────┘ (deps satisfied)                               ├─ task.completed ──▶ completed  (terminal)
                                                                  ├─ task.failed(terminal) ──▶ failed (terminal)
                                                                  └─ task.failed / verify fail ──▶ blocked ──▶ available (after delay, if attempts < max_blocked_retries)
                                                                                                          └──▶ failed "gave up after N attempts" (terminal)
 dependency failed terminally ──▶ blocked{reason=dependency_failed}, never retried unless the dependency is replanned
```

`pending` is the DAG waiting state (v1 had no equivalent; creation-order
sequencing was the only ordering). A task is `available` only when every
`depends_on` id is `completed`. Attempt accounting is unchanged from v1:
`max_task_attempts` failures in a round → `blocked`; total attempts ≥
`max_blocked_retries` → terminal `failed` with the give-up note.

### 5.2 Claiming and leases

`task.claim` handler: read `TaskIndex[task_id]`; if status ≠ `available`
or a lease with `until > now` exists → refuse. Otherwise `ledger.append(
"task:<id>", claimed{...}, expected_seq=head_seq)`. A CAS conflict means
another Worker won; refuse with `leased_to_other`. The lease loop
(`system.tick.second`) expires leases: append `lease_expired`, status →
`available`, re-emit `task.available` with a new `idempotency_key`
(`task_id:lease_generation`). A Worker's `task.step` refreshes the lease;
a Worker that stops sending steps loses the task — this is Flow 7.

### 5.3 DAG and rollup

`dag.validate` runs at creation: unknown dependency → reject with
`ui.notice`; cycle (DFS over the parent project's children) → reject.
On `task.completed`, for each dependent: if all of its deps are
`completed` → append `dependency_satisfied`, emit
`task.dependency.satisfied`, and if it is `pending` → `available`. On
terminal `task.failed`, dependents become `blocked{dependency_failed}`;
the project rollup becomes `failed` once all children are terminal
(v1's `project_status` semantics: `DONE` iff all `completed`; `FAILED` if
all terminal and any failed; else `IN_PROGRESS`/`BLOCKED`/`PENDING`).
Rollup is recomputed on every child event; `rollup_changed` is appended
only on a *terminal* transition, then `project.completed`/`project.failed`
is emitted once (idempotent on the project stream).

### 5.4 Plan Mode

1. `intent.goal.stated(wants_project=true)` or a `curiosity`/`interface`
   project request → `task.created(kind=project, mode=plan, risk)`.
2. Orchestration runs the plan-mode Worker (Guardian permits read-only
   tools only). Its result is a `Plan` artifact carried in
   `task.completed.artifacts[0]` (a blob ref of `{steps, risk, cost}`);
   Planning validates it (`decomposer.parse_steps` on the blob, DAG
   validation on `depends_on`) and republishes it as `plan.proposed`.
   *Planning, not the Worker, owns the plan stream.*
3. Verification answers `plan.reviewed`. Policy:
   - `approve` and `risk ≤ auto_approve_max_risk` → `plan.approved(by=auto)`.
   - `approve` and higher risk → `ui.prompt` (`plan_id` recorded as
     `awaiting_human`); `ui.prompt.answered(yes)` → approved; `no` →
     `rejected`; timeout → project task `paused` with reason.
   - `revise` (or `insufficient_evidence` on the first pass) → replan via
     `decomposer.decompose` seeded with the feedback; `plan.revised` with
     a computed diff (added/removed/reordered by step description);
     bounded by `max_plan_revisions`, then `rejected`.
   - `reject` → `plan.rejected`, project task `failed(terminal)`.
4. `plan.approved` creates one child `task.created` per step with
   `depends_on` from the plan's explicit edges (default: a research step
   is a dependency of every later patch step, per the decomposition
   prompt's ordering rule) and `parent_id = project_id`.

### 5.5 Re-grounding

Before making a child `available`, `reground.needs_check(child)` is true
if `now - child.created_at > regrounding_age_seconds`, or a sibling
failed terminally since the plan was approved. The check is one
`cognition.think(purpose="reground", require_real_provider=false)` with
the project goal, the child's description and `why`, and a compact
`changes_since` list (sibling outcomes, `learn.self_patch.applied`
subjects touching the child's `subject`). Answer parsing: a standalone
`STILL_VALID: yes|no` line (same scan-every-line rule as Verification);
floor or no clear line → treat as valid (a non-answer is not evidence of
drift; `01` §4.5) and append `regrounded{still_valid: null}`. A `no` with
a suggested revision → `plan.revised` (reason = the model's sentence) and
the child's description is updated by creating a replacement child
(events, never mutation) with the old one `failed{reason: superseded}`.

### 5.6 Intake and dedupe

`intake.py` maps sources to tasks. Dedupe uses
`difflib.SequenceMatcher(None, a, b).ratio() ≥ dedupe_similarity_threshold`
against every known task description (all statuses — an already-done
idea must not resurface, v1 lesson). Duplicates are dropped with a
`ui.notice(level=debug)` and a `planning:index` `deduped` event so
Curiosity can learn its miss rate.

### 5.7 Concurrency

One asyncio task per background loop (leases, stalled scan,
reconsideration, snapshot). All Ledger writes to one `task:<id>` stream go
through `TaskStore.transition` under a per-task `asyncio.Lock`; cross-task
consistency relies on CAS, not locks, so multiple Planning instances are
safe (only one should run the emitter loops — Kernel config `[planning]
leader = true`).

## 6. Key behaviors — worked scenarios

**S1 — Project with a research step feeding two patches (Flows 3, 2).**
`intent.goal.stated{goal:"self-correcting memory", wants_project:true}` →
`task.created{id:P, kind:project, mode:plan, risk:medium}` →
`task.available` → Worker claims, explores read-only, completes with a
plan blob → Planning `plan.proposed{steps:[R1(research), A2(patch,
depends_on:[R1]), A3(patch, depends_on:[R1])]}` → `plan.reviewed{approve}`
→ risk medium ≤ auto → `plan.approved{children:[R1,A2,A3]}` →
`task.created×3`; R1 `available`, A2/A3 `pending` → R1 completes →
`task.dependency.satisfied{A2,by:R1}`, `{A3,by:R1}` → both `available`
(two Workers may claim in parallel) → both complete → rollup `completed`
→ `project.completed{done:3,total:3}`.

**S2 — Worker dies mid-task (Flow 7).** A2 `claimed{w1, until:T+600}` →
`task.started` → two `task.step`s (lease refreshed) → Worker process
killed → no steps → at `until` the lease loop appends `lease_expired`,
status `available`, emits `task.available{idempotency_key:"A2:2"}` → w2
claims; the Worker resumes from A2's last durable step (Orchestration
reads `task:A2`). `attempts` is *not* incremented by a lease expiry (the
work was interrupted, not attempted and failed).

**S3 — Plan review keeps asking for revision (failure).** `plan.proposed`
→ `plan.reviewed{revise, feedback:"step 2 depends on step 3's finding"}`
→ replan → `plan.revised{diff:{reordered:[…]}}` → `plan.reviewed{revise}`
→ replan → revisions = 2 = max → `plan.rejected` → `task.failed{P,
terminal:true, reason:"plan rejected after 2 revisions"}` → `ui.notice`.
No child was ever created; nothing executed.

**S4 — Duplicate candidate.** `curiosity.candidate{"Add embedding-based
semantic retrieval …"}` while a task "Add embedding-based semantic
retrieval (vector similarity over stored memories) …" exists (any
status) → ratio 0.71 ≥ 0.45 → dropped; `deduped` event; no `task.created`.

**S5 — Stale child re-grounded after a sibling failure.** A3 pending for
8 h; A2 fails terminally → `reground_after_sibling_failure` → Planning
`cognition.think(purpose=reground)` → reply `STILL_VALID: no — A2's
approach was rejected as unsafe; A3 assumed it` → `plan.revised{reason}`,
A3 `failed{superseded}`, A3' created with the revised description.

## 7. Design considerations and tradeoffs

- **DAG vs. creation order.** v1 honored only creation order
  (`next_unfinished_child`), which cannot represent fan-in and cannot
  notice a wrongly-ordered plan (`harness-06` gap #5). Explicit edges cost
  a validation step and a readiness computation but make parallel Workers
  safe and make "step C needs A and B" representable. Cycles are rejected
  at creation rather than detected at runtime.
- **Rollup as projection.** A stored parent status that can diverge from
  its children will (`harness-03`, "Rollup status is computed, not
  separately tracked"). The cost is recomputation on every child event —
  O(children), trivial.
- **Plan Mode is a harness guarantee, not a prompt.** The plan-mode task
  is what makes Guardian's read-only enforcement possible (`harness-01`,
  "Plan Mode: a hard constraint"). The cost is one extra Worker run and
  one Verification review per project; `auto_approve_max_risk` keeps
  humans out of the loop for low/medium-risk plans (`harness-05` §2
  tradeoff).
- **Re-grounding is cheap and rare.** One bounded call per stale child,
  gated by age and sibling failure, implements `harness-03`'s
  "re-state the goal" mitigation without a per-step cost; a non-answer
  defers to the existing plan rather than stalling it.
- **Fuzzy dedupe threshold 0.45.** Measured in v1 against real
  near-duplicate pairs (0.45–0.72) vs. unrelated ones (0.13–0.27); kept
  as the second line of defense behind Curiosity's diversified sampling.
- **Leases over heartbeats.** A lease refreshed by `task.step` needs no
  extra message type and makes crash recovery a timer, not a protocol.

Alternatives rejected: a separate scheduler service (one more moving
part, no benefit at this scale); storing plans as mutable documents
(loses "why did the plan change"); letting Workers create children
directly (would bypass DAG validation and dedupe).

## 8. Safety, degradation, and failure modes

- **Provider down / budget exhausted:** decomposition returns no steps →
  project stays `pending` with note "decomposition produced no real
  steps — will retry" (v1 behavior); re-grounding treats floor as valid.
- **Malformed `curiosity.candidate` / `intent.goal.stated`:** schema
  rejection at receive; `ui.notice(level=warn)`; nothing created.
- **Handler crash:** Kernel marks Planning degraded; the event is nacked
  (commands) or dropped; state is rebuilt from the Ledger on restart —
  all transitions are idempotent by `event.id`.
- **Restart mid-operation:** `TaskIndex.rebuild` from snapshot + tail;
  in-flight leases continue to their `until`; pending human prompts are
  re-issued if older than `human_approval_timeout_seconds/2`.
- **Duplicate messages:** every transition checks the current status
  first; a duplicate `task.completed` is a no-op with a debug notice.
- **Ledger unavailable:** Planning refuses claims (`reason:
  ledger_unavailable`) and stops emitting `task.available` — the system
  stops taking on work rather than losing track of it.
- **Corrigibility:** on `system.pause`, no `task.available` is emitted and
  claims are refused; in-flight tasks receive `task.paused` from their
  Workers and park; on `system.stop`, the snapshot loop flushes. Nothing
  in Planning can execute an action; it only ever asks Orchestration to.
- **Floor:** with no provider at all, Planning still queues, claims,
  rolls up, and expires leases — only decomposition and re-grounding are
  model-dependent.

## 9. Testing strategy

- Contract tests for every produced type; handler tests (valid/invalid)
  for every consumed type.
- Unit: `TaskStore` transitions table (every legal/illegal edge),
  claim CAS race (two claimants, one Ledger), lease expiry, attempt
  accounting, give-up; `dag.validate` (unknown dep, self-dep, 3-cycle,
  diamond readiness); `project_status` property test — pure function of
  children, ported v1 cases; `parse_steps` (ported v1 tests incl. the
  RESEARCH-not-a-path case); dedupe threshold cases (ported pairs);
  approval policy matrix (risk × verdict × config); revision bound;
  re-grounding parsing (yes/no/none/floor); diff computation.
- Integration: `test_flow_3_project_plan_mode.py` (S1), `test_flow_7_lease_resume.py`
  (S2), `test_flow_9_candidate_dedupe.py` (S4), `test_planning_pause_stops_dispatch.py`.
- Invariants: no task is `available` with an unsatisfied dependency; no
  two live leases on one task; `project.completed` emitted at most once.
- Mocks: `FakeClock` for leases/timers, `FakeCognition` returning scripted
  decomposition/reground text, in-memory Bus/Ledger.

## 10. Build steps (an agent picks this up here)

Size: **L**. Parallelizable after step 2: (dag + rollup) ∥ (planmode + decomposer + reground) ∥ (intake + scheduler).

1. Skeleton: package, `Service` with `consumes`/`produces` from §3, stub handlers, boundary + contracts tests green. *Accept:* `--self-check` boots with Planning loaded.
2. `model.py`, `store.py`, `TaskIndex` + snapshot: create/transition/claim/lease. *Accept:* transitions table tests; CAS race test; snapshot rebuild equals full replay.
3. `dag.py` + `rollup.py`. *Accept:* cycle rejection; diamond readiness; ported `project_status` tests pass unchanged.
4. `scheduler.py` + lease/stalled loops; `task.available` idempotency. *Accept:* S2 integration passes on `memory` and `sqlite`.
5. `intake.py` (goal/candidate/patterns/research follow-up) + dedupe. *Accept:* S4; ported dedupe pair tests.
6. `decomposer.py` + `planmode.py` + human prompt handling. *Accept:* S1, S3; approval matrix.
7. `reground.py`. *Accept:* S5; non-answer → still valid.
8. Port v1 adapters: `src/orchestrator/tasks.py`, `projects.py`, `discovery.py` re-export from `simorgh.planning`; v1 suite green. *Accept:* both suites green.
9. Docs: README build log, config table, EVOLUTION milestone.

## 11. Migration notes

- `TaskStore.add/update_status/get/all/unfinished/children` → `store.py`
  with identical semantics; `Task` gains `mode`, `risk`, `origin`,
  `depends_on`, `lease`, `scope`, `plan_id`, `priority`.
- `project_status`, `next_unfinished_child`, `parse_project_steps`,
  `decompose_project` → `rollup.py`/`dag.py`/`decomposer.py` (readiness
  replaces creation order; `next_unfinished_child` survives only as a
  fallback for projects created without edges by `migrate-v1`).
- `_next_task`/`_resolve_project_task` → `scheduler.select_ready`;
  `_maybe_roll_up_project` → `ProjectRollup.on_child_event`;
  `_reconsider_blocked_tasks` → reconsideration loop with
  `blocked_retry_delay_seconds` (v1 had no delay).
- `discover_improvements` → `intake.on_patterns_found`; `plan_goal` →
  `intake.on_goal_stated` (v1's parent SKILL_TASK placeholder becomes a
  real `project` with `mode=execute` children when `wants_project=false`
  and count > 1).
- v1 tests move to `tests/simorgh/planning/`; `tests/test_tasks.py`,
  `test_projects.py`, and the planning parts of `test_main.py` keep passing
  through the `src/` adapters until cutover.

## 12. Open questions

1. **Task scope.** `task.created` has `subject` but no `scope`; Guardian
   needs a per-task allowed scope. *Default:* Planning derives
   `scope = {paths: [subject] or parent's paths, network: kind == research}`
   and includes it in `task.created` as an optional field (non-breaking
   addition to the catalog — file a contracts change).
2. **Who emits `plan.proposed`?** `02` Flow 3 shows Orchestration; this
   spec has Planning republish from the Worker's artifact so the plan
   stream has one owner. *Default:* this spec's reading; update Flow 3.
3. **Priority among ready tasks.** *Default:* `priority_weights[origin]`
   then age; humans first.
4. **Chat turns as tasks.** Should `kind=chat` sessions be Ledger tasks
   at all? *Default:* yes but with `lease_seconds = 60` and no
   reconsideration, so a turn interrupted by `system.stop` is visible.
5. **`task.create`'s `depends_on` is unused by the built `Service`.**
   The catalog (`contracts/messages/task.py`) carries an optional
   `depends_on` on `task.create`, but `Service._on_task_create` routes
   every non-project request through `Intake.on_candidate`, which has no
   `depends_on` parameter and always creates the task `available` —
   an external caller cannot currently request a task with a dependency
   edge; edges only ever arise internally, from Plan Mode decomposition
   (`Service._approve_plan`), which already handles them correctly
   (`PENDING` when a step has `depends_on`, `AVAILABLE` otherwise) and is
   what this build's DAG/dependency-ordering integration coverage
   exercises. Wiring `task.create`'s `depends_on` through — and deciding
   what `task.create.reply` should carry on a cycle/unknown-dependency
   rejection, since today's reply schema has no error field — is left
   for whoever next touches intake.
