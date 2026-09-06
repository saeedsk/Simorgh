# 16 — Orchestration (`simorgh/orchestration/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). A spec may refine those documents; it
> may not contradict them. If you find a contradiction, fix the governing
> document and note it in `00-README.md`'s changelog.

**Layer:** X Cross-cutting
**Owner (build):** built this session — see `simorgh/orchestration/README.md` for scope and gaps
**Status:** built (v1 slice)
**Depends on (contracts only):** `task.available`, `task.claim`/`.reply`, `percept.text.received`, `action.result`, `action.denied`, `action.needs_human`, `verify.result`, `system.state.changed`, `system.tick.second`, `cognition.think.reply`, `memory.retrieve.reply`, `self.summary.reply`, `world.env.query.reply`, `persona.voice.reply`, `ui.prompt.answered`
**v1 code that migrates here:** `src/main.py` (`handle_turn`, `run_task` loop half, `work_on_next_task`, turn/relaunch context handoff), `src/agents/logic/base.py` (`LogicAgent` tool loop, markers, `_FINAL_TURN_HINT`, `_MAX_SKILLS_IN_PROMPT`), `src/orchestrator/research_task.py` (`ResearchAgent` loop), `src/orchestrator/self_patch.py` (the READ/DRAFT loop shape, not the checks), `src/agents/skills/research.py` (loop shape)

## 1. Purpose and responsibilities

Orchestration is the harness loop — the deliberately tiny "gather
context → act → verify, repeat" engine (`harness-01` "the core loop is
deliberately small") — packaged as a `Worker` that can run N instances,
claim tasks from Planning, drive them through Cognition, Guardian,
Execution, and Verification purely by messages, and hand back a result.
It owns no policy: what is allowed is Guardian's, what is true is the
Ledger's, whether it is done is Verification's, what to do next is
Planning's. It owns *sequencing, budgets, context assembly, delegation,
and resumability*.

**Responsibilities (owns):**
- The `Worker` (consumer group `workers`): claim → run loop → complete/fail/block, with lease heartbeats.
- Turn sessions for chat (Flow 1) and task sessions per kind (Flow 2/3/4/6) via *profiles* (tool allowlists, budgets, prompt scaffold).
- Context assembly for each `cognition.think` (memory, self summary, env facets, voice) and the per-step trajectory record (`task.step`).
- Translating `tool_calls` into one-at-a-time `action.proposed`, sequenced on `task:<id>`, and feeding `action.result` back.
- The evaluator-optimizer revision loop with Verification, bounded per attempt.
- Sub-agent delegation (`fresh`/`fork`) with bounded depth and concurrency; only summaries return.
- Plan Mode sessions whose output is a `plan.proposed` artifact.
- Checkpoint/resume from the task stream; abandoning in-flight cognition on pause/stop.
- Mapping v1 conversational markers to messages with identical gates.

**Explicit non-responsibilities:**
- Task selection, DAG, rollup, retry policy (Planning). Approval (Guardian). Running tools (Execution). Judging done-ness (Verification). Prompt/compaction internals (Cognition — Orchestration sends messages and a budget; Cognition shapes them). Choosing what to explore (Curiosity).

**Principles this subsystem is the primary enforcer of:** 4.1 minimal loop; 4.9 isolation for delegation; 4.8 iterate with feedback (the loop half); `harness-03` bounded exploration budgets.

## 2. Position in the architecture

Cross-cutting: talks to every layer, imports none. Participates in Flows 1, 2, 3, 4 (as Learning's drafting sub-flow runner), 5, 6, 7, 9 (runs candidates once created). It never subscribes to `action.proposed`/`action.approved` (reserved), never touches files, never calls a provider directly.

## 3. Interfaces

### 3.1 Messages consumed
| Type | Pattern | Semantics | Use |
|---|---|---|---|
| `task.available` | command (group `workers`) | A claimable task; TTL = lease | Attempt `task.claim`; on `granted:false` ack and ignore |
| `percept.text.received` | event | Chat input (or `steer=true` correction) | Open/continue a turn session; a steer is injected into the active session's next step |
| `action.result` / `action.denied` / `action.needs_human` | events on `task:<id>` | Outcome of the proposed action | Feed back as a tool result; denied → tool result with the reasons (the model may adapt); needs_human → wait for `ui.prompt.answered` (bounded) |
| `verify.result` | event | Evaluator verdict + feedback | Complete, revise, or block |
| `cognition.think.reply`, `memory.retrieve.reply`, `self.summary.reply`, `world.env.query.reply`, `persona.voice.reply` | replies | Context/reasoning | Loop internals |
| `system.state.changed` | event | paused/stopping | Checkpoint + park; abandon in-flight |
| `system.tick.second` | event | Heartbeat | Lease renewal, wall-clock budgets |
| `ui.prompt.answered` | event | Human answer to a needs_human | Resume the step |

### 3.2 Messages produced
| Type | Semantics | Payload summary | Consumers |
|---|---|---|---|
| `task.claim` | request | `{task_id, worker_id}` | planning |
| `task.started` / `task.step` / `task.paused` / `task.completed` / `task.failed` / `task.blocked` | events | per `03` §4.4; `task.step{phase, summary, cost_usd, tokens, tool?, ok?}` | planning, verification, reflection, interface, memory, learning |
| `turn.completed` | event | `{session_id, text, floor, tool_steps, verification_ref?}` (see §12 Q1) | interface, memory, reflection, curiosity |
| `action.proposed` | event | `{action_id, task_id, tool, args, scope, reversibility, rationale, proposed_by:"orchestration@wN"}` | guardian |
| `verify.requested` | event | `{verification_id, task_id, kind, subject_ref, checklist_hint, trajectory_ref}` | verification |
| `plan.proposed` | event | Plan Mode output | planning |
| `intent.goal.stated` / `task.created` (via `task.create` request) | events/requests | from markers PLAN/EVOLVE/BATCH/PROJECT | planning |
| `research.finding.recorded` | event | research profile output | memory, learning, planning |
| `cognition.think`, `memory.retrieve`, `self.summary`, `world.env.query`, `persona.voice` | requests | context/reasoning | respective subsystems |
| `system.metrics` | event | workers busy/idle, steps/min, revisions, delegation depth | kernel |

### 3.3 Request/reply APIs served
None externally; Orchestration is a requester. (A `worker.status.request` for the Kernel's status view is optional — §12 Q3.)

### 3.4 Python protocol (`api.py`)
```python
class Worker:
    id: str
    async def run_forever(self) -> None                # claim loop
    async def run_session(self, session: Session) -> Outcome

@dataclass
class Session:
    task_id: str; kind: str; mode: Literal["plan","execute"]; profile: Profile
    depth: int = 0; parent_id: str | None = None; context: ContextSnapshot | None = None  # fork
    steps: list[Step] = field(default_factory=list)   # trajectory (also appended to task:<id>)
    budget: Budget                                     # remaining steps/tokens/cost/seconds per phase

@dataclass(frozen=True)
class Profile:                                         # per task kind
    name: str; tools: tuple[str, ...]; read_only: bool
    max_steps: int; max_revisions: int; phase_budgets: dict[str, int]
    scaffold: str                                       # prompt scaffold key handed to cognition
    last_step_hint: str                                 # the _FINAL_TURN_HINT lesson

class ContextAssembler(Protocol):
    async def assemble(self, session: Session, purpose: str) -> list[dict]   # messages for cognition.think

class ToolCallRouter(Protocol):
    def to_action(self, session: Session, call: ToolCall) -> ActionProposal | IntentOrTask
    # markers PROPOSE/PATCH/BATCH/PLAN/EVOLVE/USE/NEWS/GROWTH/FETCH/RUN/READ/LIST/RECALL/REMIND → messages

class Delegator(Protocol):
    async def spawn(self, parent: Session, child_task_id: str, *, context: Literal["fresh","fork"]) -> Summary
```

### 3.5 Configuration
`simorgh.toml [orchestration]`

| Key | Type | Default | Controls |
|---|---|---|---|
| `workers` | int | 1 (single mode) / N | Worker instances |
| `lease_seconds` / `heartbeat_s` | int | 600 / 30 | claim lease; renewal cadence |
| `max_depth` | int | 3 | delegation depth (`harness-01`) |
| `max_children_concurrent` | int | 4 | per parent session |
| `profiles.<kind>.max_steps` | int | chat 6, patch 6, research 6, plan 8, decompose 4, skill 5 | v1 values kept |
| `profiles.<kind>.max_revisions` | int | 2 | evaluator-optimizer bound |
| `profiles.<kind>.tools` | list | see §5 | allowlist (Guardian still decides) |
| `think_timeout_s` | float | 120 | per cognition request |
| `needs_human_timeout_s` | float | 600 | then treat as denied |
| `steer_check_every_steps` | int | 1 | read queued steers each step |
| `reground_every_steps` | int | 3 | re-state goal (harness-03 §1) inside long sessions |

## 4. Data model and Ledger streams

Orchestration writes to `task:<id>` (owned by Planning, appended by Workers with `expected_seq` CAS): `session.started{worker, profile, mode, depth}`, `step{no, phase, summary, tool?, action_id?, tokens, cost}`, `context.snapshot{ref}` (blob; used by fork and resume), `revision{no, feedback_ref}`, `session.paused{resume_from_step}`, `session.finished{outcome}`. Resume reads the stream, restores the last `context.snapshot`, replays steps after it. Trajectory = the `step` events; Verification reads them by `trajectory_ref`. Nothing else is persisted; Worker state is otherwise in-memory and disposable.

## 5. Internal design

```
service.py           Service: starts N Workers, subscribes group "workers"
 ├─ worker.py        claim loop, lease heartbeat, session dispatch, metrics
 ├─ session.py       the state machine below; budgets; steer queue
 ├─ context.py       ContextAssembler: memory.retrieve(k by profile), self.summary(budget), world.env.query(facets by profile), persona.voice; returns messages; Cognition compacts
 ├─ tools.py         ToolCallRouter: marker/tool_call → action.proposed | intent | task.create; scope/reversibility tags per tool from world.env.query(tools)
 ├─ verify.py        verify.requested + revision loop
 ├─ delegate.py      spawn(fresh|fork), depth/concurrency guards, summary-only return
 ├─ profiles.py      chat/patch/skill/research/plan/decompose profiles
 └─ resume.py        rebuild Session from task:<id>
```

Profiles (tools are *requests*; Guardian is the authority):
- `chat`: read_file, list_dir, web_fetch, run_python_sandboxed, recall, remind, skill.run + intent-producing markers; `max_steps 6`.
- `patch`: read_file, list_dir, draft_candidate (quick-check via `verify.requested{kind:quick}`); final = candidate; `max_steps 6`.
- `research`: read_only=true; read_file, list_dir, web_fetch; final = finding; `max_steps 6`.
- `plan` (mode=plan): read_only=true; read/list/search/web; final = `plan.proposed` artifact; `max_steps 8`.
- `decompose`: single think; output steps (used by Planning through a Worker).
- `skill`: read_file, list_dir, draft_candidate; `max_steps 5`.

Session state machine:
```
CLAIMED ──▶ GATHER ──▶ THINK ──┬─ text (final) ──▶ VERIFY ──┬─ pass ─────────▶ COMPLETED
   ▲          ▲                │                             ├─ fail+feedback & revisions<max ─▶ REVISE ──▶ THINK
   │          │                ├─ tool_calls ──▶ PROPOSE ──▶ (await result|denied|needs_human) ──▶ GATHER
   │          │                └─ floor:true ──▶ FLOOR_RESULT ──▶ COMPLETED(floor) | BLOCKED (per profile)
   │          └── steps ≥ max_steps-1: next THINK carries last_step_hint; steps == max ─▶ VERIFY with what exists
   │
 RESUME (from task:<id>) ──┘        PAUSED ◀── system.pause at any await (abandon in-flight think; checkpoint)
 any state ─ unrecoverable ─▶ FAILED/BLOCKED (Planning decides terminal vs retry)
```

Every transition appends a `step` event *before* the next await, so a crash loses at most one step. Actions are proposed one at a time; the next `THINK` sees the result. A steer percept is inserted as a user message at the next `THINK`. Every `reground_every_steps`, the assembler prepends a one-line restatement of the task goal and asks the model to confirm the next action serves it (`harness-03` mechanism 1), and the confirmation is a `step{phase:"gather", summary:"reground"}`.

Delegation: `spawn` creates the child via `task.create{parent_id, kind, depth+1}` then runs it *in the same Worker* (or lets another Worker claim it when `max_children_concurrent` allows) and awaits `task.completed|failed` for that id; `fork` snapshots the parent's assembled messages to a blob and passes `context_ref`; `fresh` passes only the question, self summary, and rules. Depth ≥ `max_depth` → the delegate tool is withheld from the profile (structural, `harness-01`).

## 6. Key behaviors — worked scenarios

**S1 — Chat turn with one tool call (Flow 1).** `percept.text.received{"what does audit.py protect?"}` → session(chat) → GATHER: `memory.retrieve(k=8)`, `self.summary(300 tokens)`, `persona.voice` (250 ms timeout) → THINK → `tool_calls:[read_file(src/orchestrator/audit.py)]` → `action.proposed{reversibility:read_only}` → Guardian approves → Execution `action.result{output_ref}` → `step{2, act, "read audit.py", ok}` → THINK → final text → VERIFY is skipped for `chat` profile unless `verify_chat=true` → `turn.completed{text, floor:false, tool_steps:1}` → Interface renders; Memory stores episodic.

**S2 — Patch task with one revision (Flow 2 + evaluator-optimizer).** claim → GATHER → THINK → candidate (via `draft_candidate` quick-check) → final → `verify.requested{kind:task}` → `verify.result{fail, feedback:"docstring dropped; restore module docstring"}` → REVISE (feedback appended as a user message, `revision{1}`) → THINK → final → `verify.result{pass}` → `task.completed{verification_ref}` → Planning rolls up; Learning records outcome.

**S3 — Plan Mode project (Flow 3).** claim task(kind=project, mode=plan) → profile `plan` (read-only) → 5 read/list steps → final = plan JSON → `plan.proposed{steps:[…], risk}` → Planning/Verification/human decide → children created; this session ends `COMPLETED(plan)`.

**S4 — Research delegation (Flow 6).** A `patch` session's model emits `delegate(research, "does a cache already exist?")` → `spawn(fresh)` → child session (research profile, read-only) → `research.finding.recorded` → summary returned as a tool result to the parent's next THINK; the child's 5 READ steps exist only in `task:<child>` and `trace:*`.

**S5 — Failure: pause mid-think, then resume on another Worker (Flows 5/7).** Worker w1 awaiting `cognition.think.reply` receives `system.state.changed(paused)` → cancels the await (reply later arrives and is discarded by `correlation_id`), appends `session.paused{resume_from_step:3}`, emits `task.paused`, stops heartbeat; lease expires → on `system.resume` Planning re-emits `task.available` → w2 claims, `resume.py` restores from `context.snapshot` at step 3, continues. No step is executed twice: action ids are idempotency keys and Execution dedupes.

**S6 — Denied action.** THINK → `web_fetch(http://169.254.169.254/…)` → Guardian `action.denied{layer:scope}` → fed back as a tool error; model adapts or finishes; `step{ok:false}`; Reflection sees the denial via the event.

## 7. Design considerations and tradeoffs

- **One action per step, sequenced.** Simpler resume and exact trajectories (`harness-04` "evaluate the trajectory"); cost: no parallel tool calls inside a step. Parallelism comes from delegation and multiple Workers instead.
- **Verification is a separate subsystem, revision loop is here.** `harness-02` evaluator-optimizer: the evaluator must be a separate prompt; the *loop* belongs to the thing holding the session. Bounded `max_revisions` avoids endless polishing.
- **Hard step ceilings plus `last_step_hint`.** `harness-03` mechanism 2 and v1 milestone 83: a model that spends its last step on a tool call produced garbage; the hint fixed it live.
- **Steer as a message, not a flag.** `harness-01` interrupt/steer; the correction is just another percept the assembler places in front of the next think.
- **Fork snapshots are blobs.** Cheap to implement, exact, resumable; cost: storage — bounded by Cognition's compaction before snapshot.
- **Orchestration does not compact.** Cognition owns the pipeline (`harness-01` five layers); Orchestration passes a budget. Keeps the loop minimal (`01` §4.1).

## 8. Safety, degradation, and failure modes

- Provider down: `cognition.think.reply{floor:true}` → chat completes with the floor text and `floor:true`; patch/research → `task.blocked{reason:"no real provider"}` (retryable, Planning schedules).
- Budget exhausted: same as above via `floor:true`/error reply.
- Malformed replies: tool-call parse failure → step recorded, model re-asked once with the parse error, then final text.
- Handler crash: session marked `FAILED(crash)` by the Worker's supervisor; Planning retries; Kernel counts it.
- Restart mid-op: lease expiry + resume (S5).
- Duplicate `task.available`/`action.result`: dedupe by `task_id`+claim seq / `action_id`.
- Ledger unavailable: the Worker pauses the session (`task.paused{reason:ledger}`) rather than proceed without a durable trajectory.
- Corrigibility: pause/stop handled at every await; an in-flight think is abandoned; no new `action.proposed` after `paused`; Guardian denies regardless.
- Delegation depth/concurrency are structural caps; a child can never outlive its parent's lease.

## 9. Testing strategy

- Contract tests for all produced types; handler tests for consumed types (valid/invalid).
- Unit: state machine transitions (table-driven); budgets and `last_step_hint` injection at `max_steps-1`; steer insertion; reground cadence; profiles' tool allowlists; marker router for all 14 v1 markers (rambling-after-marker lesson: `first_line_argument` behavior is Cognition's, but the router must handle `payload` shapes); revision loop bound; delegation depth cap; fork snapshot/restore equality.
- Integration: `test_flow_1_turn.py`, `test_flow_2_task_with_revision.py`, `test_flow_3_plan_mode_read_only.py` (asserts no non-read-only `action.proposed` in plan mode), `test_flow_5_pause_abandons_think.py`, `test_flow_6_research_isolation.py` (parent trace contains only the summary), `test_flow_7_resume_on_second_worker.py`.
- Property: "no `action.proposed` without a preceding `step`", "every session ends in exactly one terminal event", "resume never re-proposes an already-resulted action_id".
- Fakes: `FakeCognition` scripted replies; `FakeGuardian`/`FakeExecution` echo approvals/results; `FakeVerification`; `FakeClock`.

## 10. Build steps (an agent picks this up here)

1. Skeleton; `Profile`/`Session`/`Budget` dataclasses; `profiles.py`. *(S)*
2. `worker.py`: claim loop, lease heartbeat, single-Worker run; `task.started/completed` for a no-tool chat with `FakeCognition`. *(S)*
3. `context.py`: assembler with the four requests and timeouts; `session.py` state machine (GATHER/THINK/final only); `task.step` events; tests. *(M)*
4. `tools.py`: tool_calls → `action.proposed`; results feedback; marker mapping; denied/needs_human handling. *(M)*
5. `verify.py`: `verify.requested` + revision loop; Flow 2 integration. *(S)*
6. Plan Mode profile → `plan.proposed`; research profile → `research.finding.recorded`. *(S)*
7. `resume.py` + pause handling; Flows 5/7 tests. *(M)*
8. `delegate.py` (fresh/fork, caps); Flow 6 test. *(M)*
9. Port v1 loop tests (`test_logic_agent`, `test_research_task`, `test_main` turn/`run_task` halves); adapters in `src/`; README; `EVOLUTION.md`. *(M)*

Parallelizable: 4/5/6 after 3; 7/8 after 3. Size: **L**.

## 11. Migration notes

- `handle_turn` → chat session; `LogicAgent._build_prompt` → `context.py` (persona/skills/self blocks now come from messages); its marker handlers → `tools.py` (same gates, now via `action.proposed`/`intent`/`task.create`).
- `run_task`'s loop half → `session.py`; its status half stays in Planning. `work_on_next_task` → Worker claim loop. `_FINAL_TURN_HINT` → `Profile.last_step_hint`.
- `ResearchAgent` → research profile; `SelfPatchAgent.draft_patch`'s READ/DRAFT loop → patch profile (`draft_candidate` tool routes to Verification quick-check); its checks move to Verification.
- `relaunch_context.json` handoff → `context.snapshot` in the task stream.
- v1 tests keep passing through `src/` adapters that run a Worker on the memory bus.

## 12. Open questions

1. `turn.completed` missing from `03` §4. **Default:** add under `task.*` (see `15-interface.md` Q1).
2. `task.create` request/reply missing from `03` §4 (Planning exposes creation). **Default:** add `task.create`/`task.create.reply{task_id}`.
3. Should chat turns be verified? **Default:** no (`verify_chat=false`), except when the turn produced actions with side effects.
4. Should `delegate` be a tool visible to the model or only harness-initiated? **Default:** a tool, present only when `depth < max_depth`, so the model can ask for isolated research.
5. `action.denied` feedback: full reasons or a sanitized subset? **Default:** full `reasons` for `policy|scope|budget`; only `layer` for `classifier` (avoid teaching evasion).
6. **Conversational intent has no path to the real pipeline — decision (post-cutover review, 2026-09-06 — `07-post-cutover-review.md` §3.1).** `tools.py` routes only `tool_calls → action.proposed`; §5's "marker/tool_call → intent | task.create" half was never built. So "propose an outcome-feedback skill" typed as chat produces a convincing draft and touches nothing, while the *typed* `propose <topic>` command reaches `task.create` — two paths for one request, only one real. This is the project's worst finding: a self-improving agent that role-plays the capability through its most natural surface. **Decision:** no marker protocol. The chat profile's tool list gains `propose{topic}` and `patch{path, description}` as ordinary tools in `_TOOL_POLICY`, routed through `to_action_payload` into `action.proposed` (`reversibility="reversible"`), gated by Guardian exactly like `read_file`; Execution's handler does what `dispatch.py`'s typed commands already do (`task.create`). One more named tool for the model, zero new trust paths. Acceptance: chat text "propose a skill for X" yields a real Guardian/`activity` event. Until it lands, treat any "Sim proposed X in chat" as unverified.
7. **Context assembly has one owner (same review, §3.2).** Orchestration's `Assembler` stops fetching `self.summary`/`persona.voice` (`context.py` lines 28–34); Cognition's `PromptAssembler` is the sole fetcher of those protected blocks. Orchestration contributes memory retrieval (now including `working` with `filters.session_id` — `05` §12 q6), `session.messages`, and `user_text`. Halves that content's token cost per turn and makes §7's "Orchestration does not compact; Cognition owns the pipeline" literally true. Also noted from the review: `Worker.current_task_id/current_kind` are shared unguarded attributes — status-only today, a real race the moment concurrent sessions per Worker exist (`local-multi`, delegation); guard or drop before either lands.
