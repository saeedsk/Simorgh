# 03 — Contracts and Messaging

> Part of the Simorgh v2 blueprint. This is the *interface definition*
> for the whole system: the message envelope, the topic catalog, delivery
> semantics, the Bus/Ledger/Subsystem protocols, backends, versioning,
> and error handling. `simorgh/contracts/` is the code form of this file;
> when they disagree, the code's checked-in JSON Schemas are the source
> of truth and this file must be updated.

## 1. Why messages

A subsystem that calls another subsystem's function couples to its
signature, its process, its failure modes, and its release schedule.
A subsystem that publishes `task.completed` couples to a schema. The
second kind of coupling is what lets sixteen packages be built by
sixteen agents in parallel, replaced independently, moved to other
processes or hosts, and replayed from the log. Messages are also the
observability model: the trace of a decision *is* the sequence of
messages that produced it.

Three interaction patterns cover every need in the system:

| Pattern | Use when | Delivery | Example |
|---|---|---|---|
| **Event** (pub/sub, broadcast) | Something happened; anyone may care | Every subscriber gets a copy | `task.completed`, `persona.state.changed` |
| **Command** (work queue) | Someone must do this, exactly one of the eligible handlers | One member of a consumer group gets it; ack/nack; redelivery | `task.available` → one Worker; `action.approved` → Execution |
| **Request/Reply** | The caller needs an answer to proceed | Point-to-point with correlation and timeout | `cognition.think`, `memory.retrieve`, `task.claim` |

Rule of thumb from `harness-02`: prefer *events* (decoupled, replayable)
for everything that is a fact; use *commands* for work distribution; use
*request/reply* only when the caller genuinely blocks on the answer and
the round-trip is short.

## 2. The envelope

Every message on the Bus is one `Message` with this envelope. Payloads
are typed per message type (§4). Serialization is canonical JSON
(sorted keys, UTF-8, no NaN) so hashes are stable across backends.

```python
@dataclass(frozen=True)
class Message:
    id: str                    # uuid4
    type: str                  # e.g. "action.proposed"  (domain.noun[.verb])
    schema_version: int        # per-type schema version, starts at 1
    ts: float                  # unix seconds, producer clock
    source: str                # subsystem name, optionally "name@instance" (e.g. "orchestration@w3")
    trace_id: str              # whole causal chain (a turn, a tick, a project)
    causation_id: str | None   # id of the message that directly caused this one
    correlation_id: str | None # request/reply pairing (reply carries the request's id)
    partition_key: str | None  # ordering key, e.g. "task:abc123" — messages with the same key are delivered in order
    priority: int = 5          # 0 (lowest) … 9 (highest); system.pause/stop are 9
    ttl_seconds: float | None = None
    reply_to: str | None = None       # topic to reply on (request/reply)
    idempotency_key: str | None = None # handlers must treat duplicates with the same key as already-done
    payload: dict              # validated against schema/<type>.v<schema_version>.json
```

Invariants enforced by `contracts.envelope.validate()` on publish and on
receive: `type` is in the catalog; `payload` validates against its
schema; `priority` in 0–9; `partition_key`, when set, has the form
`<kind>:<id>`; replies set `correlation_id` and use a `*.reply` type;
messages with `priority >= 9` must not set `partition_key` (a preempting
control message must never queue behind a held partition).

## 3. Topic taxonomy

`type` doubles as the topic. Domains are fixed; adding a domain is a
contracts change reviewed like an API change.

| Domain | Owned (produced) mainly by | Purpose |
|---|---|---|
| `system` | kernel | lifecycle, ticks, pause/stop/resume, metrics, health |
| `percept` | interface, execution | inputs entering the system (text, file, web, tool result, time) |
| `intent` | interface, curiosity | a goal stated by a human or by the system's own drives |
| `plan` | planning, verification | plan proposed/reviewed/approved/revised, re-grounding |
| `task` | planning, orchestration | task lifecycle: created, available, claim, started, step, paused, completed, failed, blocked |
| `turn` | orchestration | `turn.completed` — the chat-turn counterpart of `task.completed` (listed under §4.4; its own first segment on the wire) |
| `project` | planning | `project.completed` / `project.failed` rollups (listed under §4.5; its own first segment on the wire) |
| `action` | any → guardian → execution | the guarded action path: proposed, approved, denied, needs_human, result |
| `guardian` | guardian | `guardian.review` (req/rep, used by Verification on candidate code), trust posture changed/request |
| `tool` | execution | tool registry: registered, unavailable, invoked (telemetry) |
| `verify` | verification | requested, result, plan review |
| `memory` | memory | retrieve (req/rep), stored, consolidated, forgotten |
| `world` | worldmodel | env queries (req/rep), env observed/changed |
| `self` | worldmodel, reflection | self model summary (req/rep), self.model.updated, self.observation, self.gaps |
| `learn` | learning | outcome recorded, competence updated, skill acquired, self_patch applied/reverted, experiment result |
| `reflect` | reflection | patterns found, drift detected, calibration updated, health finding |
| `curiosity` | curiosity | candidate proposed, interest updated, share proposed |
| `persona` | persona | state changed, voice (req/rep), user model updated |
| `ui` | interface | notice, prompt (needs human), rendered |
| `cognition` | cognition | think (req/rep), provider status, budget status |
| `research` | orchestration | finding recorded |

Patterns for subscription use `*` for one segment and `#` for the rest:
`task.*`, `action.#`, `#` (everything — reserved for the trace writer and
tests).

**Reserved topology rules (enforced by the Kernel at subscribe *and* publish time):**
- `action.proposed`: subscribable only by `guardian`.
- `action.approved`: subscribable only by `execution`; publishable only by
  `guardian` (and `kernel`, solely for the `--self-check` forged-token
  drill). This publish restriction is defense in depth alongside the HMAC
  token, not a replacement for it.
- `action.denied`: publishable by `guardian` (policy layers) and by
  `execution` with `layer: token` only (a forged, expired, or replayed
  approval). For `layer: classifier` denials Guardian emits the layer but
  omits detailed `reasons`, so a denied proposer is not handed a recipe
  for evasion.
- `system.pause`, `system.stop`, `system.resume`, `system.restart`,
  `system.reload`: publishable only by `interface`, `kernel`, and — for
  `restart`/`reload` — `execution` (the `relaunch`/`hot_swap` tools).
- `self.model.updated`: publishable only by `worldmodel` (one writer per
  stream); `reflection` contributes via `self.observation`.
- `plan.proposed`: publishable only by `planning` (a Worker's plan
  artifact arrives via `task.completed.artifacts`; Planning validates it
  and republishes, so `plan:<id>` has one owner).

## 4. Message catalog (v1)

The complete list is `simorgh/contracts/messages/*.py` with JSON Schemas
in `simorgh/contracts/schema/`. This section is the human index; each
subsystem spec expands the entries it owns. Payload fields are shown as
`name: type` with `?` for optional.

### 4.1 `system.*` (kernel)
- `system.started` {mode, subsystems: [name@version], data_dir}
- `system.state.changed` {state: running|paused|stopping|stopped, reason?}
- `system.pause` / `system.resume` / `system.stop` {reason, requested_by, scope?: all|autonomous} — priority 9. `scope: autonomous` pauses only self-initiated work (v1's `autonomous off`): Guardian denies proposals whose task `origin` is not `human`.
- `system.restart` {reason, self_check_passed: bool, commit?} and `system.reload` {subsystem, trial: bool} — requested by Execution's `relaunch`/`hot_swap` tools; the Kernel performs them (in `local-multi`/`aws` modes Execution is not the Kernel process).
- `system.schedule.add` / `.added` / `.cancel` {schedule_id, at|every_seconds, label, payload?} — durable reminders/timers (v1 `reminders.py`); fire as `percept.time.scheduled`.
- `system.tick.second` {n}; `system.tick.idle` {idle_seconds}; `system.tick.sleep` {window_seconds}
- `system.health` {subsystem, status: ok|degraded|down, detail?}
- `system.metrics` {subsystem, counters: {…}, gauges: {…}}
- `system.status.request` / `system.status.reply` {…snapshot…}

### 4.2 `percept.*`
- `percept.text.received` {channel: cli|api|chat|command, text, user_id?, session_id, command?: str, steer?: bool} — Interface sets `channel: command` + `command` for routed commands (e.g. `interest`, `news`) so subsystems can ignore plain chat; `steer: true` marks a mid-task correction (Flow 5 interrupt/steer)
- `percept.file.changed` {path, change: created|modified|deleted, sha256?}
- `percept.web.fetched` {url, status, content_ref, sha256, fetched_at}
- `percept.time.scheduled` {schedule_id, label}

### 4.3 `intent.*`
- `intent.goal.stated` {goal, origin: human|curiosity|reflection, priority, constraints?: {scope?: [paths], deadline?}, wants_project: bool}

### 4.4 `task.*` (payload shapes in `07-planning.md`)
- `task.create` / `task.create.reply` {kind, description, subject?, parent_id?, depends_on?, mode?, origin, risk?, scope?} → {task_id, deduplicated_against?: task_id} — the request/reply form used by Interface commands and by Orchestration's sub-agent delegation; Planning applies fuzzy dedupe and emits `task.created`
- `task.created` {task_id, kind: chat|patch|skill|research|project, description, subject?, parent_id?, depends_on: [task_id], mode: plan|execute, origin: human|curiosity|reflection|research|project, risk: low|medium|high, scope?: {paths: [...], network: bool}} — `scope` is derived by Planning from `subject`/parent/`intent.goal.stated.constraints`; Guardian's scope rule and Execution's constraints read it
- `task.available` (command; consumer group `workers`) {task_id, kind, lease_seconds}
- `task.claim` / `task.claim.reply` {task_id, worker_id} → {granted: bool, lease_until, task: {…}}
- `task.list.request` / `.reply` {filter?: {status, kind, parent_id}} → {tasks: [{…}], projects: [{project_id, rollup, done, total, stalled: bool}]}
- `task.work_next.request` / `.reply` {} → {task_id?, reason?} — v1 `work`
- `task.started` {task_id, worker_id}
- `task.step` {task_id, step_no, phase: gather|act|verify, summary, tool?, action_id?, ok?, confidence?, cost_usd?, tokens?} — the trajectory Verification and Reflection read
- `task.paused` {task_id, reason, resume_from_step}
- `task.completed` {task_id, result_summary, artifacts: [ref], verification_ref, confidence?}
- `turn.completed` {session_id, task_id, text, floor: bool, tool_steps, verification_ref?, confidence?} — the chat-turn counterpart of `task.completed` (Flow 1); consumed by Interface (render), Memory (episodic), Reflection, Curiosity
- `task.failed` {task_id, reason, terminal: bool, attempts}
- `task.blocked` {task_id, reason, retry_after?}
- `task.dependency.satisfied` {task_id, satisfied_by}

### 4.5 `plan.*`
- `plan.proposed` {plan_id, task_id, goal, steps: [{step_id, kind, description, subject?, depends_on, why}], risk, estimated_cost}
- `plan.reviewed` {plan_id, verdict: approve|revise|reject|insufficient_evidence, checklist: [{q, answer, evidence}], feedback?}
- `plan.approved` {plan_id, approved_by: human|auto, children: [task_id]}
- `plan.revised` {plan_id, reason, diff: {added: [...], removed: [...], reordered: [...]}}
- `plan.reground` / `plan.reground.reply` {plan_id, task_id, changes_since: […]} → {still_valid: bool, reason, suggested_revision?}
- `project.completed` / `project.failed` {project_id, done, total, summary}

### 4.6 `action.*` (the guarded path; shapes in `09-guardian.md` and `08-execution.md`)
- `action.proposed` {action_id, task_id?, tool, args, scope: {paths?: [...], network: bool}, reversibility: read_only|reversible|irreversible, rationale, proposed_by}
- `action.approved` {action_id, tool, args_sha256, expires_at, approval_token, mode_at_approval, constraints?: {timeout_s, max_output_bytes}}
- `action.denied` {action_id, reasons: [str], layer: policy|denylist|immunity|budget|paused|scope|classifier}
- `action.needs_human` {action_id, question, options: [...], default?}
- `action.result` {action_id, ok: bool, output_ref, stdout_preview, error?, duration_ms, side_effects: [ref]}

### 4.7 `tool.*`
- `tool.registered` {name, version, description, read_only: bool, reversibility, schema_ref, provider: builtin|skill|mcp}
- `tool.unavailable` {name, reason}
- `tool.invoked` {name, action_id, duration_ms, ok}

### 4.8 `verify.*`
- `verify.requested` {verification_id, task_id, kind: task|plan|self_patch|skill, subject_ref, checklist_hint?}
- `verify.result` {verification_id, task_id, verdict: pass|fail|insufficient_evidence, checklist: [{q, answer, evidence}], trajectory: {steps, wasted, recovered_errors}, feedback?: {items: [{what, why, suggested_fix}]}, mechanical: {tests_passed?, baseline?, patched?}, confidence?} — Verification's own internal check messages use `partition_key = verification:<id>` and `correlation_id = verification_id`; the result is published on the task's partition

### 4.9 `memory.*`
- `memory.retrieve` / `memory.retrieve.reply` {query, kinds: [working|episodic|semantic|procedural], k, budget_tokens?, filters?: {session_id?, task_type?, tags?, since?}} → {items: [{ref, kind, content, score, confidence, ts}], truncated: bool}
- `memory.store` (command) {kind, content, tags, confidence?, source_ref}
- `memory.stored` {ref, kind}
- `memory.contradiction.flagged` {ref_a, ref_b, evidence, confidence_after} — emitted when a store or consolidation pass detects two records that cannot both hold (v1's halving-on-contradiction rule)
- `memory.consolidated` {window, distilled: n, pruned: n}
- `memory.forgotten` {refs, reason}

### 4.10 `world.*` / `self.*`
- `world.env.query` / `.reply` {what: capability_map|file_index|tools|user_profile|git_state, args?} → {facet, as_of, …} — `file_index` accepts `args: {path, max_chars}` and returns a bounded read-only content preview (World Model reads the repository tree and git state directly as observation; it never writes)
- `world.env.observed` {facet, summary, ref}
- `self.summary` / `self.summary.reply` {budget_tokens} → {text, version}
- `self.gaps` / `self.gaps.reply` {k} → {version, gaps: [{competence, task_type, score, samples}], unexplored_areas: [{area, modules: [...], last_touched?, tasks_ever}]}
- `self.model.updated` {version, changed_sections: [...], reason} — published only by `worldmodel`, the single writer of the `self:model` stream
- `self.observation` {kind: restart|change|limitation|success|failure, detail, ref} — published by `reflection` (the writer of record for observations); World Model folds them into the model

### 4.11 `learn.*`
- `learn.pipeline.run` (command; consumer group `learning`) {task_id, kind: patch|skill|evolve, subject?, description, prior_reasons?: [str]} / `learn.pipeline.completed` {task_id, outcome: applied|researched|rejected|reverted|floor, detail, commit?, verification_ref?} — how a Worker hands a `kind=patch|skill` task to Learning (Flow 4); Learning owns policy and sequencing, Execution owns the composite drafting tools (`self_patch.draft`, `skill.draft`), Verification owns the checks
- `learn.strategy.suggest` / `.reply` {task_type, context?} → {strategy?: {approach, provider, purpose_config}, success_rate, samples} — procedural memory consulted by Orchestration before a task
- `learn.outcome.recorded` {task_id, task_type, succeeded: bool, verdict, cost_usd, duration_s, strategy?, confidence?}
- `learn.competence.updated` {task_type, success_rate, calibration, samples}
- `learn.skill.acquired` {name, path, tests: n}
- `learn.self_patch.applied` / `.reverted` {subject, commit, tests: {baseline, patched}, reason?}
- `learn.experiment.result` {experiment_id, variant, metric, promoted: bool}

### 4.12 `reflect.*`
- `reflect.patterns.found` {window, patterns: [{kind, agent?, rate, proposal}]}
- `reflect.drift.detected` {task_id|plan_id, kind: goal|scope|behavior, evidence, recommendation}
- `reflect.calibration.updated` {task_type, stated_confidence, empirical_accuracy}
- `reflect.health.finding` {severity: info|warn|critical, detail, action_taken?: none|request_reset|request_pause_hint}
- `reflect.review.request` / `.reply` {window_seconds?} → {patterns, takeaways} — v1 `reflect` command

### 4.13 `curiosity.*`
- `curiosity.candidate` {kind: patch|research, subject?, description, area, why_this_area, novelty_score}
- `curiosity.interest.updated` {topic, last_followed_up, items_found}
- `curiosity.share.proposed` {kind: growth|news, content_ref}
- `curiosity.discover.request` / `.reply` {} → {created: [task_id]} — v1 `discover`
- `curiosity.share.request` / `.reply` {kind: growth|news} → {shared: bool, content_ref?} — v1 `growth`/`news`
- `curiosity.interest.add` {topic|feed_url}; `curiosity.interest.list.request` / `.reply` → {interests: […]}; `curiosity.interest.follow_up.request` / `.reply` {topic?} → {items_found} — v1 `interest`/`interests`/`curious`

### 4.14 `persona.*`
- `persona.state.changed` {valence, arousal, cognitive_load, source, previous}
- `persona.voice` / `.reply` {context: chat|notice|report} → {style_block, mood_phrase}
- `persona.user_model.updated` {facet, value, confidence}

### 4.15 `ui.*` / `cognition.*` / `research.*`
- `ui.notice` {level, text, source}; `ui.prompt` {prompt_id, question, options, default, timeout_s}; `ui.prompt.answered` {prompt_id, answer}; `ui.rendered` {channel, text}
- `cognition.think` / `.reply` {purpose: chat|draft|plan|review|research|decompose|reground|consolidate, session_id?, messages: [{role, content}], tools?: [name], expected?: text|tool_calls|edit_blocks|verdict, budget: {max_tokens, max_cost_usd}, require_real_provider: bool, allow_summarize?: bool, last_step?: bool} → {text, tool_calls: [{tool, args}], edit_blocks?: [{search, replace}], provider, cost_usd, tokens, floor: bool, non_answer: bool, confidence?, agreement?: bool, compaction?: {layers_applied: [...], tokens_before, tokens_after}}
- `cognition.compact.request` / `.reply` {session_id, target_tokens} → {layers_applied, tokens_before, tokens_after, summary_ref?}; `cognition.compact.pre` / `.done` {session_id, layer} — the `PreCompact` hook events so extensions can react before the model-summarization layer runs
- `cognition.provider.status` {provider, available, budget: {…}}
- `guardian.review` / `.reply` {subject, code_ref, kind: self_patch|skill} → {approved: bool, reasons: [str], layers_run: [...]} — the static denylist + adaptive-immunity check exposed to Verification
- `guardian.posture.changed` {mode, trust_score, reason}; `guardian.posture.request` / `.reply` → {mode, trust_score, tightened_by: [...], paused_scope?} — v1 `autonomous status`
- `research.finding.recorded` {task_id, finding_ref, follow_up?: {subject, description}}

## 5. Delivery semantics

- **At-least-once.** Backends may redeliver after a crash or nack.
  Every handler is idempotent by contract: use `idempotency_key` (or
  `id`) and the Ledger to detect duplicates before side effects.
- **Ordering** is guaranteed only *per `partition_key`*. All messages
  about one task use `task:<id>`; the Bus routes a partition to one
  consumer at a time within a group.
- **Priority** affects dequeue order within a backend's queue;
  `system.*` at 9 preempts.
- **TTL** expires stale commands (e.g. a `task.available` older than its
  lease is dropped and re-emitted by Planning).
- **Ack/nack/retry.** Command handlers ack on success; nack with
  `retry_after` on transient failure; after `max_deliveries` the message
  is moved to the backend's dead-letter queue *and* appended to the
  Ledger stream `dead:<type>` (so it survives backend rotation and is
  queryable), and a `system.health` degraded event fires.
- **Tracing.** The Bus's trace writer appends every message to
  `trace:<trace_id>` subject to a per-type sample rate (`[bus.trace]
  rates`), defaulting to 1.0 for everything and typically lowered only
  for `system.tick.second` and `system.metrics`.
- **Backpressure.** Publishers await; backends bound queue depth per
  consumer group and apply the Kernel's rate policy (also how LLM budget
  pressure slows Curiosity without special code).

## 6. Protocols (`simorgh/contracts/protocols.py`)

```python
class Bus(Protocol):
    async def publish(self, message: Message) -> None
    async def subscribe(self, pattern: str, handler: Callable[[Message], Awaitable[None]],
                        *, group: str | None = None, durable: bool = False) -> Subscription
    async def request(self, message: Message, *, timeout: float) -> Message
    async def reply(self, request: Message, *, type: str, payload: dict) -> None
    async def ack(self, message: Message) -> None
    async def nack(self, message: Message, *, retry_after: float | None = None) -> None

class Ledger(Protocol):
    async def append(self, stream: str, event: Event, *, expected_seq: int | None = None) -> int   # CAS via expected_seq
    async def read(self, stream: str, *, from_seq: int = 0, limit: int | None = None) -> list[Event]
    async def tail(self, stream: str, handler: Callable[[Event], Awaitable[None]]) -> Subscription
    async def snapshot(self, stream: str, state: dict, at_seq: int) -> None
    async def load_snapshot(self, stream: str) -> tuple[dict, int] | None
    async def streams(self, prefix: str) -> list[str]
    async def put_blob(self, data: bytes, *, content_type: str) -> str          # returns "blob:<sha256>"
    async def get_blob(self, ref: str) -> bytes
    async def compact(self, stream: str, *, before_seq: int, keep_snapshot: bool = True) -> int  # record compaction, distinct from context compaction

class Subsystem(Protocol):
    name: str
    version: str
    consumes: tuple[str, ...]      # topic patterns (declared, checked by the Kernel)
    produces: tuple[str, ...]
    async def start(self, ctx: Context) -> None   # ctx: name, instance_id, run_id, mode, bus, ledger, config, secrets, clock, logger, data_dir
    async def stop(self) -> None
    async def health(self) -> Health

class Clock(Protocol):             # injectable for tests
    def now(self) -> float
    async def sleep(self, seconds: float) -> None

class Provider(Protocol):          # cognition adapters (Claude Code CLI, Gemini, …)
    name: str
    def available(self) -> bool
    async def complete(self, messages: list[dict], *, tools: list[dict] | None, max_tokens: int) -> ProviderResponse

class Tool(Protocol):              # execution adapters
    name: str; description: str; read_only: bool; reversibility: str; args_schema: dict
    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult
```

`Event` (Ledger) mirrors `Message` minus routing fields (`seq`, `stream`,
`type`, `ts`, `trace_id`, `causation_id`, `payload`). The Bus's trace
writer appends every message to `trace:<trace_id>` so the two stay
correlated.

## 7. Backends

| Concern | `memory` | `sqlite` | `aws` |
|---|---|---|---|
| Bus | asyncio queues per topic/group; priority heap; in-process only | one WAL-mode DB: `messages`, `subscriptions`, `deliveries`; pollers with lease; multi-process on one host | SNS topic per domain, SQS (FIFO for partitioned commands) per consumer group; DLQ per queue |
| Ledger | dict of lists | `events(stream, seq, …)` with unique (stream, seq) → CAS; `snapshots` | DynamoDB table PK=stream SK=seq, conditional put for CAS; S3 for large payload refs |
| Deps | none | none | `boto3` (lazy import; backend absent if missing) |

Backend selection is purely `simorgh.toml`:

```toml
[runtime]
mode = "single"            # single | local-multi | aws
data_dir = "~/.simorgh"

[bus]
backend = "memory"         # memory | sqlite | aws
[ledger]
backend = "jsonl"          # jsonl | sqlite | dynamodb
```

Large payloads (file contents, transcripts) are never inlined: they are
written to the Ledger's blob area (`blobs/<sha256>`) and referenced by
`*_ref` fields. The `aws` backend maps blobs to S3.

## 8. Versioning and evolution

- Each message type has `schema_version`. Adding optional fields is a
  minor change (same version). Removing/renaming/retyping a field bumps
  the version and requires a translator in `contracts/compat.py` for one
  version back.
- Consumers declare the versions they accept; the Bus routes older
  versions through translators and drops (to `dead:`) anything it cannot
  translate, with a `system.health` event.
- The catalog is tested: every type in `topics.py` has a schema, every
  schema has a Python dataclass, every dataclass round-trips through
  canonical JSON, and every subsystem's declared `consumes`/`produces`
  refers to real types (`tests/simorgh/contracts/`).

## 9. Error handling conventions

- Handlers never raise across the bus boundary. An unhandled exception
  is caught by the Kernel's dispatcher, logged as `system.health`
  degraded for that subsystem, and the message is nacked (commands) or
  dropped (events) — never re-raised into the publisher.
- Request/reply failures are explicit reply types: `<type>.reply` with
  `ok: false, error: {code, detail, retryable}`; timeouts produce a
  synthetic error reply in the requester.
- The deterministic floor is a *value*, not an exception: `cognition.think.reply` with `floor: true`
  tells the caller no real provider answered so it can degrade honestly.
- Malformed messages fail validation at publish time in the producer's
  process (a bug surfaces where it was written, not where it was read).

## 10. Security

- The Kernel generates a per-run secret; `approval_token`s are
  HMAC-SHA256 over the canonical action; Execution verifies before
  running; tokens expire (`expires_at`, default 120 s).
- Subscriptions to and publications on reserved topics are refused by
  subsystem identity (§3). In `single` mode identity is the in-process
  `Service` object. In `local-multi`/`aws` modes a subsystem's process
  authenticates to the Bus with a per-run `subsystem_token` the Kernel
  issues at `start()` (HMAC of `run_id|name|instance_id` under the
  run secret); the backend stamps the verified `source` on every
  message, so a forged `source` field in the envelope cannot bypass the
  reserved-topic rules.
- On the `aws` backend, topics/queues are per-deployment and IAM-scoped;
  the same token check still applies end-to-end because the secret is
  distributed by the Kernel, not by the transport.
- Secrets (provider keys) live only in the Kernel's secret store and are
  handed to the subsystems that declare a need for them in `start()`.

## 11. Minimal example

```python
# planning publishes a task; a worker claims it; guardian approves an action; execution runs it.
await bus.publish(Message.new("task.available", source="planning",
    partition_key=f"task:{tid}", payload={"task_id": tid, "kind": "patch", "lease_seconds": 600}))

reply = await bus.request(Message.new("task.claim", source="orchestration@w1",
    partition_key=f"task:{tid}", payload={"task_id": tid, "worker_id": "w1"}), timeout=5)
assert reply.payload["granted"]

await bus.publish(Message.new("action.proposed", source="orchestration@w1", trace_id=reply.trace_id,
    causation_id=reply.id, partition_key=f"task:{tid}",
    payload={"action_id": aid, "task_id": tid, "tool": "read_file", "args": {"path": "src/x.py"},
             "scope": {"paths": ["src/x.py"], "network": False}, "reversibility": "read_only",
             "rationale": "gather context", "proposed_by": "orchestration"}))
# → guardian emits action.approved with approval_token → execution runs → action.result arrives on task:<tid>
```
