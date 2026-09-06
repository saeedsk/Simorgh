# 02 — System Architecture

> Part of the Simorgh v2 blueprint. Governing principles are in
> `01-vision-and-principles.md`; the exact message envelope, topic catalog,
> delivery semantics, and Python protocols are in
> `03-contracts-and-messaging.md`. This file is the map: what the
> subsystems are, how they are layered, how safety is made structural,
> how the package is laid out, and — most importantly — how the
> cognitive loop actually flows as messages through the system.

## 1. The system in one picture

```
                         ┌──────────────────────────────────────────────────────────┐
                         │                    Layer 4 · Self & surfaces              │
                         │   persona (identity·emotion·social)   interface (CLI/API) │
                         └──────────────▲──────────────────────────────▲─────────────┘
                                        │                              │
   ┌────────────────────────────────────┼──────────────────────────────┼──────────────────────┐
   │ Layer 3 · Growth                    │                              │                      │
   │   learning (self-improvement)   reflection (meta-cognition)   curiosity (drives/discovery)│
   └────────────────────────────────────▲──────────────────────────────▲──────────────────────┘
                                        │                              │
   ┌────────────────────────────────────┼──────────────────────────────┼──────────────────────┐
   │ Layer 2 · Agency                    │                              │                      │
   │   planning ──proposes──▶ GUARDIAN ──approves──▶ execution ──results──▶ verification        │
   └────────────────────────────────────▲──────────────────────────────▲──────────────────────┘
                                        │                              │
   ┌────────────────────────────────────┼──────────────────────────────┼──────────────────────┐
   │ Layer 1 · Cognitive core            │                              │                      │
   │   cognition (reasoning/LLM)      memory (W/E/S/P)         worldmodel (env + SELF model)   │
   └────────────────────────────────────▲──────────────────────────────▲──────────────────────┘
                                        │                              │
   ┌────────────────────────────────────┴──────────────────────────────┴──────────────────────┐
   │ Layer 0 · Substrate                                                                        │
   │   bus (nervous system)        ledger (append-only memory of everything)       kernel       │
   └───────────────────────────────────────────────────────────────────────────────────────────┘

   Cross-cutting:  orchestration (the harness loop + multi-agent workers) — runs tasks by
                   speaking to every layer above through the bus, never by importing them.
```

Arrows between layers are *messages on the bus*. There are no import
edges between subsystems; there are only `simorgh.contracts` imports and
bus/ledger clients. The picture is layered for comprehension, but the
runtime is a graph: any subsystem may subscribe to any event.

## 2. The sixteen subsystems

| # | Subsystem | Package | Layer | One-line job | Spec |
|---|---|---|---|---|---|
| 01 | Bus | `simorgh/bus/` | 0 | Typed, durable, async pub/sub + work queues + request/reply; backends: memory, SQLite, AWS SNS/SQS | `subsystems/01-bus.md` |
| 02 | Ledger | `simorgh/ledger/` | 0 | Append-only event streams with projections/snapshots; backends: JSONL, SQLite, DynamoDB | `subsystems/02-ledger.md` |
| 03 | Kernel | `simorgh/kernel/` | 0 | Process supervisor: config, secrets, subsystem lifecycle, scheduler/ticks, `system.*` commands (pause/stop/status), observability | `subsystems/03-kernel.md` |
| 04 | Cognition | `simorgh/cognition/` | 1 | Reasoning engine: provider routing + budgets + ensemble; prompt assembly; the graduated context-compaction pipeline; tool-call protocol; deterministic floor | `subsystems/04-cognition.md` |
| 05 | Memory | `simorgh/memory/` | 1 | Working/episodic/semantic/procedural memory; retrieval (lexical + embedding); confidence/decay; consolidation ("sleep") | `subsystems/05-memory.md` |
| 06 | World Model | `simorgh/worldmodel/` | 1 | The environment model (codebase, tools, user, world) and the **Self Model** (capabilities, competence, limitations, change history) | `subsystems/06-worldmodel.md` |
| 07 | Planning | `simorgh/planning/` | 2 | Goals → projects → tasks with a dependency DAG; Plan Mode; re-grounding; replanning; durable backlog and rollups | `subsystems/07-planning.md` |
| 08 | Execution | `simorgh/execution/` | 2 | Tool registry and invocation, sandboxes, file/git/shell/web adapters; runs **only** Guardian-approved actions | `subsystems/08-execution.md` |
| 09 | Guardian | `simorgh/guardian/` | 2 | Constitution enforcement, permission modes, deny-first policy, denylist + adaptive immunity + classifier, protected subjects, budgets, approval tokens, corrigibility | `subsystems/09-guardian.md` |
| 10 | Verification | `simorgh/verification/` | 2 | Checklist + trajectory evaluation, evaluator-optimizer loop, isolated test-suite runs, insufficient-evidence outcome | `subsystems/10-verification.md` |
| 11 | Learning | `simorgh/learning/` | 3 | Outcome → competence/strategy updates; skill library; audited self-patch pipeline; experiments (A/B, hot-swap); knowledge distillation into the KB | `subsystems/11-learning.md` |
| 12 | Reflection | `simorgh/reflection/` | 3 | Meta-cognition: health/stability monitoring, calibration tracking, self-critique deltas, drift detection, Self Model updates | `subsystems/12-reflection.md` |
| 13 | Curiosity | `simorgh/curiosity/` | 3 | Intrinsic motivation: capability-map and competence-gap exploration, interests/news, creative agenda, project proposals; explore/exploit balance | `subsystems/13-curiosity.md` |
| 14 | Persona | `simorgh/persona/` | 4 | Identity, continuous emotional state, voice/style, user model (theory of mind), proactive sharing | `subsystems/14-persona.md` |
| 15 | Interface | `simorgh/interface/` | 4 | CLI, HTTP/WebSocket API, vitals/digests/notifications; reconciles subsystem outputs into coherent, honest responses | `subsystems/15-interface.md` |
| 16 | Orchestration | `simorgh/orchestration/` | X | The harness loop (gather→act→verify) as a Worker; task claiming; sub-agent delegation (fresh/fork) with bounded depth; parallel workers | `subsystems/16-orchestration.md` |

Ownership notes: each Ledger stream has exactly one writer — `self:model`
is written only by World Model (Reflection contributes `self.observation`
events); `plan:<id>` only by Planning (a Worker's plan artifact is
validated and republished by Planning); `guardian:*` only by Guardian.
World Model observes the repository tree and git state directly
(read-only) rather than through Execution tools, the same way Memory
reads its own index. Naming note: v1's `SharedMemoryBus` (persona mood
pub/sub) is **not** the v2 Bus. In v2 the persona's emotional state is owned by Persona and
published as `persona.state.changed` events on the system Bus.

## 3. Structural safety: the action path

This is the single most important topology rule in the system.

```
   any subsystem ──▶ action.proposed ──▶ [ GUARDIAN only ] ──▶ action.approved ──▶ [ EXECUTION only ]
                                              │                      (carries approval_token)
                                              ├──▶ action.denied  ──▶ interface, planning, reflection
                                              └──▶ action.needs_human ──▶ interface (blocks until answered)
```

- **Only Guardian subscribes to `action.proposed`.** The kernel enforces
  this at subscription time (a subscription to `action.proposed` from any
  other subsystem name is rejected and logged).
- **Only Execution subscribes to `action.approved`, and only Guardian
  may publish it** (the Kernel enforces both directions; the `--self-check`
  forged-token drill is the one Kernel-published exception). Execution
  may publish `action.denied` only with `layer: token`.
- **Every approval carries an `approval_token`**: `HMAC-SHA256(kernel_secret,
  action_id | tool | sha256(canonical_args) | expires_at)`. Execution
  recomputes and compares before running anything. A forged or replayed
  approval fails closed. The secret is generated by the Kernel at startup
  and handed only to Guardian and Execution via their start context.
- **Guardian is the enforcement point for:** permission mode (Plan Mode
  → only tools marked `read_only=true`), `system.pause`/`system.stop`
  (everything denied while paused; stop drains and refuses), protected
  subjects, the static denylist, adaptive immunity (similarity to
  previously rejected proposals), the reversibility class of the action,
  the budget/trust posture, and the constitution's directives as
  checkable rules.
- Guardian never *does* anything. It only decides. Execution never
  *decides* anything. It only does. That separation is the whole point
  (AGI-04 §9: the safety layer must not live inside the process it
  constrains).

Corrigibility is the same mechanism from the other side: `system.pause`
and `system.stop` are Kernel commands with the highest bus priority;
Guardian's first check on every proposal is "is the system paused or
stopping." No reasoning anywhere can route around it, because no
reasoning can reach Execution except through Guardian.

## 4. Package layout and module rules

```
simorgh/                          # the v2 package (v1 stays in src/ until cutover; see 06-migration)
  __init__.py
  __main__.py                     # `python -m simorgh` → kernel.cli
  contracts/                      # THE shared dependency. Message types, topics, protocols. No logic.
    __init__.py
    envelope.py                   # Message dataclass, validation, canonical JSON
    topics.py                     # topic constants + patterns, domain registry
    messages/                     # one module per domain: system.py, percept.py, task.py, plan.py,
                                  #   action.py, tool.py, verify.py, memory.py, world.py, self_.py,
                                  #   learn.py, reflect.py, curiosity.py, persona.py, ui.py
    protocols.py                  # Bus, Ledger, Subsystem, Clock, Provider, Tool Protocols
    schema/                       # generated JSON Schema per message type (checked in)
  bus/                            # 01
  ledger/                         # 02
  kernel/                         # 03
  cognition/                      # 04
  memory/                         # 05
  worldmodel/                     # 06
  planning/                       # 07
  execution/                      # 08
  guardian/                       # 09
  verification/                   # 10
  learning/                       # 11
  reflection/                     # 12
  curiosity/                      # 13
  persona/                        # 14
  interface/                      # 15
  orchestration/                  # 16

tests/simorgh/
  contracts/                      # schema round-trips, catalog completeness
  test_module_boundaries.py       # AST-based: no subsystem imports another subsystem
  <subsystem>/                    # unit + contract tests per subsystem
  integration/                    # scenario tests wiring several subsystems over the in-memory bus
docs/blueprint/                   # this document set
data/ (or ~/.simorgh/)            # runtime data dir: ledger/, config, secrets, self/SELF.md, plans/
```

Every subsystem package has the same shape:

```
simorgh/<name>/
  README.md        # 1 screen: purpose, link to spec, how to run its tests
  __init__.py      # exports Service
  service.py       # class Service(Subsystem): consumes/produces, start/stop/health, handler wiring
  api.py           # in-package interfaces (Protocols/ABCs) — what internals depend on
  config.py        # @dataclass Config with defaults; loaded from simorgh.toml [<name>]
  <internals>.py   # anything else
```

**Module rules (enforced by `tests/simorgh/test_module_boundaries.py`):**

1. `simorgh.<x>` for `x` in subsystems may import: `simorgh.contracts.*`,
   `simorgh.bus.client` / `simorgh.ledger.client` (type-level clients),
   the standard library, and its own package. Nothing else under
   `simorgh.`.
2. `simorgh.contracts` imports only the standard library.
3. `simorgh.bus` and `simorgh.ledger` import only `simorgh.contracts` and stdlib
   (their AWS backends import `boto3` lazily inside the backend module and
   are skipped if unavailable).
4. `simorgh.kernel` may import every subsystem's `Service` (it is the
   composition root) — and nothing else may.
5. Third-party dependencies are forbidden in the core; optional adapters
   guard their imports and register themselves only when importable.

## 5. Key flows (the cognitive loop as messages)

Notation: `A ─t─▶ B` means subsystem A publishes message type `t`, which
B consumes. Requests are `A ⇄ B (req/rep)`. Every message in a flow
shares one `trace_id`; each carries the `causation_id` of the message
that triggered it, so the Ledger's `trace:*` stream reconstructs the
whole causal chain.

### Flow 1 — A conversational turn

```
interface  ─percept.text.received─▶ persona, memory, orchestration
persona    ─persona.state.changed─▶ (emotion agent reacts; mood nudged)      [floor: rule-based lexicon]
orchestration: opens a TURN session (a lightweight task, kind=chat)
orchestration ⇄ memory   (memory.retrieve req/rep: recent turns, relevant episodic/semantic)
orchestration ⇄ worldmodel (self.summary req/rep: compact Self Model rendering)
orchestration ⇄ cognition (cognition.think req/rep: assembled context → response or tool calls)
   └ if tool calls: orchestration ─action.proposed─▶ guardian ─action.approved─▶ execution ─action.result─▶ orchestration
     (loop, bounded by the turn's step budget)
orchestration ─turn.completed─▶ interface (renders), memory (episodic write), reflection (outcome), curiosity (volunteer?)
curiosity  ─(maybe) persona.share.proposed─▶ persona ─ui.notice─▶ interface      [growth/news volunteering]
```

Persona shapes tone by contributing a *voice* block to the context
assembly (via `persona.voice` req/rep inside cognition's prompt
assembler), not by being in the call path — the loop is unchanged
whether or not Persona is running.

### Flow 2 — An autonomous idle tick becomes finished work

```
kernel     ─system.tick.idle─▶ curiosity, planning
planning   (backlog non-empty?) ─task.available─▶ orchestration
   else: curiosity ─curiosity.candidate─▶ planning ─task.created─▶ …
orchestration (a Worker) ⇄ planning  (task.claim req/rep — exactly-one-claimant via ledger CAS)
orchestration ─task.started─▶ planning, interface, reflection
orchestration runs the harness loop:
   gather:  ⇄ memory.retrieve, ⇄ worldmodel.self.summary, ⇄ worldmodel.env.query
   act:     ⇄ cognition.think → action.proposed ─▶ guardian ─▶ execution ─▶ action.result
   verify:  ─verify.requested─▶ verification ⇄ cognition (checklist + trajectory) ─verify.result─▶ orchestration
            └ if fail with feedback and attempts remain: revise (evaluator-optimizer), loop
orchestration ─task.completed | task.failed | task.blocked─▶ planning (rollup), reflection, learning, memory, interface
learning   ─learn.outcome.recorded─▶ worldmodel (competence update), reflection
reflection ─self.model.updated─▶ worldmodel, interface (vitals), curiosity (new gaps to explore)
```

The Worker is stateless between tasks; everything it needs is in the
Ledger, so a crash mid-task leaves the task `in_progress` with a claim
lease that expires, and another Worker resumes it (Flow 7).

### Flow 3 — A project: plan mode, approval, execution, re-grounding

```
interface|curiosity ─intent.goal.stated─▶ planning
planning ─task.created(kind=project, mode=plan)─▶ orchestration
orchestration (Worker, mode=plan): guardian enforces read-only tools; loop explores; output = Plan artifact
orchestration ─task.completed(artifacts=[plan_ref])─▶ planning
planning: validates the artifact (well-formed steps, acyclic deps, in-scope subjects) and, as the single
          owner of plan:<id>, ─plan.proposed─▶ interface, verification
verification ⇄ cognition  (independent plan review: coverage, ordering, risk) ─plan.reviewed─▶ planning
planning: approval policy — human required if risk ≥ threshold (─▶ interface ⇄ human), else auto
planning ─plan.approved─▶ (children created with dependency edges) ─task.created×N─▶ orchestration
… each child runs Flow 2 as its dependencies complete (DAG scheduling, not just order) …
before working a child older than `regrounding_age` or after any sibling failure:
planning ⇄ cognition (plan.reground: "does this step still serve the goal given what changed?")
   └ if not: planning ─plan.revised(reason)─▶ ledger, interface  (never a silent overwrite)
planning: rollup is a pure function of children → ─project.completed | project.failed─▶ learning, reflection, interface
```

### Flow 4 — A self-patch (the system changing its own code)

```
orchestration (Worker claims a kind=patch task) ─learn.pipeline.run─▶ learning     [handoff: Learning owns policy/sequencing]
learning   ─action.proposed(tool=self_patch.draft, subject, description)─▶ guardian   [protected subjects denied here]
guardian   ─action.approved─▶ execution: runs the composite drafting tool (READ/LIST/DRAFT loop; SEARCH/REPLACE for large
             files; cognition access via cognition.think purpose=draft) — the loop *shape* lives in Execution's tool,
             the *checks* live in Verification, the *decisions* live in Learning
execution  ─action.result(candidate)─▶ learning
learning   ─verify.requested(kind=self_patch, candidate)─▶ verification:
              1) static denylist + adaptive immunity (guardian.review req/rep)
              2) docstring-regression + invariants
              3) isolated full test suite in a repo copy (baseline vs patched)
           ─verify.result─▶ learning
learning   ─action.proposed(tool=apply_source_patch)─▶ guardian ─▶ execution (write + git commit, never push)
learning   ─action.proposed(tool=relaunch|hot_swap)─▶ guardian ─▶ execution (self-check subprocess; rollback commit on failure)
learning   ─learn.self_patch.applied|reverted─▶ reflection (Self Model change history), interface (growth notice), memory
learning   ─learn.pipeline.completed─▶ orchestration (which then closes the task via the normal verify/complete path)
```

Nothing about this is new policy — it is v1's pipeline with each gate
made a distinct, observable message and the write made impossible
without an approval token.

### Flow 5 — Stop / pause (corrigibility)

```
interface ─system.pause─▶ kernel (priority 9)
kernel    ─system.state.changed(paused)─▶ everyone
guardian  denies every action.proposed with reason=paused; orchestration workers finish their current
          *approved* action, checkpoint the task (task.paused), and park
kernel    ─system.resume─▶ …  |  ─system.stop─▶ drain: workers task.paused, subsystems stop(), ledger flushed
```

A `system.stop` never waits on a model call: an in-flight cognition
request is abandoned (its result is discarded on arrival) and the task
resumes from its last durable step later.

### Flow 6 — A research task (sub-agent style isolation)

```
planning ─task.created(kind=research)─▶ orchestration
orchestration spawns a Worker with a *fresh* context (only the question + self summary + rules)
   loop: read-only tools only (guardian: research tasks are read-only by policy) → finding
orchestration ─research.finding.recorded─▶ memory (semantic write, kind=research_finding), learning (KB distillation), planning (follow-up task if FOLLOW-UP present)
only the finding crosses back — none of the exploration transcript is retained outside the trace stream
```

### Flow 7 — Crash, restart, resume

```
kernel restarts (or a Worker process dies)
planning projection rebuilds from ledger; tasks with an expired claim lease → task.available again
orchestration Worker claims, reads the task's own stream (steps taken, last verified state), resumes from the last durable step
reflection ─self.observation(restart)─▶ worldmodel (Self Model: uptime/continuity history)
```

### Flow 8 — Consolidation ("sleep")

```
kernel ─system.tick.sleep─▶ memory, reflection, learning
memory:     episodic → semantic distillation (cognition.think, bounded), confidence decay, pruning → memory.consolidated
reflection: reviews the window's outcomes → reflect.patterns.found ─▶ planning (new tasks), worldmodel (limitations)
learning:   competence/strategy tables recomputed → learn.competence.updated ─▶ worldmodel
```

### Flow 9 — Curiosity chooses what to explore next (diversity by construction)

```
kernel ─system.tick.idle─▶ curiosity (only when planning reports an empty backlog)
curiosity ⇄ worldmodel (self.gaps req/rep: weakest competences, least-explored capability areas)
curiosity ⇄ worldmodel (env.capability_map req/rep: real src/ areas and modules)
curiosity samples an area/target (weighted: gaps > staleness > interests > uniform), THEN
curiosity ⇄ cognition ("propose ONE improvement/question for THIS target": PATCH | RESEARCH)
curiosity ─curiosity.candidate─▶ planning (fuzzy-deduped against every task description) ─task.created─▶ …
rarely (configurable chance, only if no active project): curiosity ─intent.goal.stated─▶ planning (Flow 3)
```

## 6. Process and deployment model

| Mode | What runs where | Bus backend | Ledger backend | When |
|---|---|---|---|---|
| `single` (default) | One process; every subsystem is an asyncio task inside the Kernel | `memory` | `jsonl` (or `sqlite`) | Dev, tests, a laptop |
| `local-multi` | Kernel + N Worker processes (orchestration) + optional separate cognition process | `sqlite` (WAL, one file) | `sqlite` | One host, parallel task work, isolation of crashes |
| `aws` | Any of the above across hosts | `aws` (SNS topics + SQS queues per consumer group) | `dynamodb` | Multi-host; optional, never required |

Selecting a mode is configuration (`simorgh.toml [runtime] mode = ...`),
not code. Every subsystem is written once against the Bus/Ledger
protocols. Integration tests run every scenario on the `memory` bus, and
a smaller smoke set on `sqlite` to prove durability semantics.

### 6.1 Where this is headed: a persistent, multi-session service

Captured directly from the creator (2026-09-06, ahead of the Phase 5
work it actually belongs to -- written down now so it survives to
whichever model reviews the roadmap next): Sim's intended end state is
not "a CLI you invoke," it's a daemon that stays alive and running
continuously, with people establishing independent *sessions* against
one long-running Kernel -- through the CLI, through a web interface,
through a plain HTTP/WebSocket API -- each session getting its own
back-and-forth, all of them talking to the same Sim underneath.

`single` mode's Kernel already *is* this daemon in embryonic form --
`python -m simorgh run` boots once and runs until stopped, exactly the
long-lived process this end state needs; nothing about the Kernel/Bus/
Ledger substrate assumes a single client. What's actually missing is
narrower than a re-architecture:

- **Interface hardcodes one session.** `self.session_id` is set once
  per process (`Service.__init__`) and every REPL turn reuses it. The
  message contracts this rides on already don't have this limit --
  `percept.text.received`, `turn.completed`, and (since milestone 105)
  Memory's own episodic writes are already correlated by an arbitrary
  `session_id` string, not by anything process-scoped. Generalizing
  Interface from one fixed session to a registry of N concurrent ones
  is additive, not a redesign of the message layer underneath it.
- **No transport for a second, independent client yet.** The dashboard
  built this session (`simorgh/interface/httpapi.py`) is deliberately
  read-only -- status, not conversation. A real two-way surface (a
  WebSocket per session for streaming turns, or an HTTP endpoint a web
  UI or external API client can open its own session against) is the
  next slice of the same Phase 5 "HTTP/WebSocket API in Interface"
  item, not a new item.
- **Session continuity already has a foundation.** Memory's episodic
  writes already tag records by `session_id` (milestone 105); a
  genuine multi-session daemon would extend that same mechanism to give
  each session (or each returning user, if sessions are meant to
  persist across a reconnect) its own continuity rather than one shared
  stream.

This is not a build instruction for the current wave -- it's context
for whoever plans Phase 5 next: the destination is a persistently
running Sim that many sessions, through many surfaces, can each
independently talk to, and the pieces already built (session-scoped
contracts, session-scoped memory, a daemon-shaped Kernel) point at that
destination more than they need to change to reach it.

### 6.2 Where this is headed, part two: an admin observe-then-control plane

Captured directly from the creator in the same conversation as §6.1
(2026-09-06), immediately after seeing the read-only dashboard
(`simorgh/interface/httpapi.py`) run live for the first time. Explicit
framing from the creator: **observe first, control second** -- as the
system's owner ("someone with extensive computer knowledge"), the
creator wants to first see everything, then be able to change things,
behind admin authentication that is deliberately *not* part of the
first pass ("for beginning, the authentication can be ignored, but
later we can add it"). This is design scope for whoever picks up Phase
5 -- likely Fable, per the creator's own plan to switch review models
after cutover -- not an implementation instruction for right now.

**Observe tier -- extending the dashboard §6.1's transport already
enables:**
- **Logs.** Already true today, just not surfaced anywhere: "structured
  logs are Ledger events; there is no separate log file that can drift
  from the record" (§7 below). An admin log view is a Ledger query UI,
  not new capture.
- **Metrics history, not just the live snapshot the dashboard shows
  today.** The Bus already writes every message -- including every
  `system.metrics` event -- to `trace:<trace_id>` (§7). A real
  history view needs a queryable time series, which likely means
  either mining the trace stream directly or (more likely, given trace
  sampling exists for high-volume topics) a dedicated low-frequency
  metrics-history stream Kernel writes to on its own schedule,
  independent of the per-request trace sampling rate.
- **LLM usage.** The creator explicitly flagged this one as postponable
  if it's a lot of work. Cognition's `RollingWindowBudget` (built this
  session, milestone 111) already estimates and tracks per-call cost in
  memory for budget enforcement -- the raw signal already exists; what's
  missing is persisting it somewhere queryable across restarts and a
  view over it.
- **System health/sanity and resource allocation.** Per-subsystem
  health status and `restarts` are already in the dashboard (this
  session's `StatusServer.snapshot()` work). Actual OS-level resource
  usage (process memory/CPU) is not tracked anywhere yet -- a real gap,
  not just an unsurfaced signal.

**Control tier -- explicitly deferred, and explicitly needs auth before
any of it ships for real:** live-adjustable timeouts and other config
knobs, enabling/disabling individual skills, memory-size limits, and
the maximum number of concurrent Orchestration workers (`Config.
workers`, static today, read once at Kernel boot). None of `simorgh.
toml`'s config surface is currently mutable at runtime -- every
subsystem reads its `Config` once, at construction. Making any of this
live needs either a runtime config-update mechanism with subsystems
that re-read config dynamically, or reusing what the Supervisor already
knows how to do (restart one subsystem in place) to apply a changed
config by restarting just the affected subsystem, not the whole Kernel.

**One architectural constraint worth handing to whoever designs this,
not just a feature list**: an admin control action is still an action
with real consequences -- disabling a skill, raising the worker count,
changing a timeout that governs how long Guardian waits for a human
prompt. `01-vision-and-principles.md`'s own structural-safety principle
(4.3) exists precisely so nothing bypasses the guarded `action.proposed
-> guardian -> action.approved -> execution` path. An admin channel that
writes runtime state directly, outside that path, would be a second,
parallel, unaudited way to act on the system -- worth deciding
*deliberately* whether admin actions are simply another category of
guarded action (logged, reversible, subject to the same topology) or a
genuinely separate privileged path, rather than defaulting into the
latter by not thinking about it.

## 7. Observability (built into the substrate)

- Every message is appended to `trace:<trace_id>` by the Bus itself
  (configurable sampling for high-volume ticks). `simorgh trace <id>`
  prints the causal tree.
- Kernel exposes counters/gauges per subsystem (messages in/out, handler
  latency, errors, budget usage) as `system.metrics` events and answers
  `system.status.request`; every human-facing surface for them — the CLI
  `status` command, the HTTP `/status` endpoint — is owned by Interface.
- The vitals panel (mood, energy, load, memory size, skills, interests,
  backlog, trust posture, budget) is a projection over these — not a
  special code path.
- Structured logs are Ledger events; there is no separate log file that
  can drift from the record.

## 8. What "done" looks like for the whole system

The system is v2-complete when Flows 1–9 each run end-to-end in the
integration suite on the in-memory bus, the v1 CLI behaviors are
reachable through Interface, the boundary test passes, every subsystem
has a spec + README + tests, and `python -m simorgh --self-check` boots
every subsystem, runs one synthetic task through Guardian and Execution
with a valid approval token, refuses one with a forged token, and exits
0.
