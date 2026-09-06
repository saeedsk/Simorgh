# 04 — Build Plan and Roadmap

> Part of the Simorgh v2 blueprint. This is the order of work, what can
> run in parallel, the acceptance criteria that gate each phase, and how
> to hand pieces to multiple agents at once. Sizes are rough
> (S ≈ a day of focused agent work, M ≈ 2–4 days, L ≈ a week+).

## 1. Strategy in one paragraph

Build the substrate first (Bus, Ledger, Kernel, contracts) because
every other subsystem is written against it and nothing can be
integration-tested without it. Then port v1's existing capabilities into
subsystems behind the new contracts, in three parallel tracks, keeping
v1's ~890 tests green through adapters the whole time (strangler
pattern, `06-migration-from-v1.md`). Only after the ported system runs
Flows 1–9 end to end do we add the genuinely new capabilities (Plan
Mode, DAG scheduling, compaction pipeline, evaluator-optimizer loop,
Self Model, drift detection, trust posture), because each of those is
easier to build and verify on a working bus than on paper. Finally,
harden, add optional backends, and cut over.

## 2. Dependency graph

```
Phase 0 ─ contracts ─┬─ bus ─────┐
                     ├─ ledger ──┼─ kernel ─┬─ Phase 1 tracks (parallel):
                     └─ schemas ─┘          │   A: cognition, memory
                                            │   B: guardian, execution
                                            │   C: worldmodel, persona, interface(CLI)
                                            └─ Phase 2 (needs A+B): planning, orchestration, verification
                                                  └─ Phase 3 (needs 2): learning, reflection, curiosity
                                                        └─ Phase 4: new capabilities across subsystems
                                                              └─ Phase 5: multi-process, AWS adapters, cutover
```

Within a phase, tracks are independent: they touch different packages
and share only `contracts/`. Two agents on the same track must split by
component inside the subsystem spec's §10.

## 3. Phases

### Phase 0 — Substrate (L; 1–2 agents, sequential-ish)

**Deliverables**
- `simorgh/contracts/`: envelope, topics, all v1 message dataclasses +
  generated JSON Schemas, protocols, `compat.py` stub. `tests/simorgh/contracts/`.
- `simorgh/bus/`: `memory` and `sqlite` backends; consumer groups;
  partition ordering; priority; TTL; ack/nack/DLQ; request/reply; trace
  writer. Property tests for ordering and at-least-once.
- `simorgh/ledger/`: `jsonl` and `sqlite` backends; CAS append;
  snapshots; blob store; `tail`.
- `simorgh/kernel/`: config loader (`simorgh.toml` + env overrides),
  secrets, subsystem discovery/lifecycle/supervision with backoff,
  reserved-topic enforcement, scheduler (`system.tick.*`), metrics,
  `python -m simorgh` with `run`, `status`, `trace <id>`, `--self-check`.
- `tests/simorgh/test_module_boundaries.py` (AST import checker).
- A `NullSubsystem` example and an integration test that boots the
  kernel with two toy subsystems exchanging a request/reply over each bus backend.

**Acceptance**: all of the above green; `python -m simorgh --self-check`
boots and exits 0 with zero real subsystems; the boundary test passes on
an empty tree; a forged `approval_token` round-trip test exists in
contracts (HMAC helper) even before Guardian exists.

### Phase 1 — Port the core (three parallel tracks; M each)

**Track A — Cognitive core: `cognition`, `memory`**
- Cognition: port `src/cognition/{provider,budget,claude_code_provider,gemini_provider,tool_protocol}.py`
  behind `cognition.think`; keep `CognitionRouter` failover; expose
  provider/budget status events; implement tool-call parsing with the
  v1 lessons (`first_line_argument`, non-answer detection). Compaction
  pipeline stub with layers 1–2 only (budget reduction, snip).
- Memory: port `src/memory/{long_term,short_term}.py` and
  `consolidation.py` onto the Ledger; `memory.retrieve` with lexical
  scoring + the v1 hashing-trick embedding; confidence/decay preserved.

**Track B — Agency floor: `guardian`, `execution`**
- Guardian: port `src/orchestrator/audit.py` (denylist, adaptive
  immunity, protected subjects, sandbox scoping) + budget enforcement +
  pause/stop + approval tokens; modes `observe|plan|guarded|locked`
  (no `trusted` yet).
- Execution: tool registry + `Tool` protocol; port `sandboxing/sandbox.py`,
  `tools/web_fetch.py`, `apply.py`, `git_ops.py`, shell passthrough,
  read/list tools; token verification; `action.result` with blob refs.

**Track C — Self & surfaces: `worldmodel` (env only), `persona`, `interface` (CLI)**
- World Model: env facets — file index, capability map (port
  `capability_map.py`), tool inventory, git state. Self Model *schema*
  and a static summary (dynamic updates come in Phase 3).
- Persona: port `persona_state.py`, `agents/emotion/base.py`,
  `socializing.py`; publish `persona.state.changed`; serve `persona.voice`.
- Interface: a CLI that speaks only the bus: `percept.text.received`,
  `ui.notice`, `ui.prompt`, `system.*`; vitals as a projection; v1
  command names preserved where semantics survive.

**Acceptance (phase)**: Flow 1 (chat turn) passes end-to-end on the
memory bus with a fake provider; Flow 5 (pause/stop) passes; v1 test
suite still green (adapters in `src/` delegate to the new packages where
ported).

### Phase 2 — Agency (two tracks; M/L)

**Track D — `planning` + `orchestration`**
- Planning: port `tasks.py`, `projects.py`, `discovery.py` onto Ledger
  streams `task:*`/`project:*`; claim with lease via CAS; DAG edges
  (`depends_on`) with `task.dependency.satisfied`; rollup projection;
  blocked-retry and give-up policy.
- Orchestration: the Worker (gather→act→verify loop) as a `Subsystem`
  that can run N instances; turn sessions for chat; sub-agent spawn
  (fresh/fork) with bounded depth; step budgets; resume-from-ledger.

**Track E — `verification`**
- Port `verification.py` (with the non-answer lesson), `self_patch.run_isolated_test_suite`,
  docstring-regression and `main.py` invariants as *checks*; checklist
  generation; trajectory summary; `insufficient_evidence`.

**Acceptance**: Flows 2, 6, 7 pass; a research task's exploration never
appears outside `trace:*`; a Worker killed mid-task is resumed by another.

### Phase 3 — Growth (three parallel tracks; M each)

- **`learning`**: port `self_patch.py` (drafting loop, SEARCH/REPLACE edit
  mode, relaunch/hot-swap via `deployment.py`), `agents/skills/{registry,research}.py`;
  outcome recording → competence tables; skill library registration into
  Execution's tool registry via `tool.registered`.
- **`reflection`**: port `reflection.py`, `health.py`; calibration
  tracking; self-critique deltas; **Self Model updates** (`self.model.updated`).
- **`curiosity`**: port `discover_creative_improvements/_project`,
  `interests.py`, news/growth sharing; diversified sampling via
  `world.env.query(capability_map)` + `self.gaps`.

**Acceptance**: Flows 4, 8, 9 pass; `docs/EVOLUTION.md`-style change
history appears in the Self Model; the repetition regression test (ten
ticks never produce two candidates above the similarity threshold in the
same area) passes.

### Phase 4 — The new capabilities (parallel by subsystem; M each)

Each is a targeted change inside one subsystem, specified in its spec:
1. **Plan Mode + approval policy** (planning, guardian, interface): Flow 3
   with human prompt when `risk ≥ high`, auto otherwise; plan review by
   Verification.
2. **Context compaction layers 3–5** (cognition): reference substitution,
   read-time collapse, model summarization as last resort; per-call
   budget accounting; persistent-instruction protection.
3. **Evaluator-optimizer loop** (orchestration + verification): bounded
   revise-with-feedback inside one attempt before `task.blocked`.
4. **Re-grounding + drift detection** (planning + reflection): staleness
   check before old children; `reflect.drift.detected`; `plan.revised`
   with reasons.
5. **Trust posture** (guardian + reflection): automatic tightening from
   failure streaks/budget pressure; `trusted` mode only via config.
6. **Self Model completeness** (worldmodel + reflection + learning):
   competence per task type, calibration, limitations, open questions;
   `SELF.md` projection in the data dir.
7. **Skill acquisition as procedural memory** (learning + memory +
   execution): skills discoverable by description, loaded on demand.

**Acceptance**: each item has an integration scenario; harness-06's
five gaps are each closed by name in a test.

### Phase 5 — Scale-out, adapters, cutover (M)

- `local-multi` mode: Worker processes on the SQLite bus; crash/resume drills.
- Optional `aws` backends (SNS/SQS/DynamoDB/S3) behind the same tests
  (skipped when `boto3` absent).
- HTTP/WebSocket API in Interface -- the creator's own stated direction
  for where this lands (`02-system-architecture.md` §6.1, captured
  2026-09-06): not just a status/metrics surface (a read-only slice of
  it, the live dashboard, already shipped ahead of this phase), but a
  genuine multi-session API -- a persistently running Kernel that many
  independent sessions can each open their own conversation against,
  through the CLI, a web interface, and this API, all at once. Needs
  Interface generalized from its current single fixed `session_id` to a
  registry of concurrent sessions (the message contracts underneath
  already carry an arbitrary `session_id`, so this is additive) and a
  real two-way transport (WebSocket per session, most likely) rather
  than the dashboard's read-only polling.
- An admin observe-then-control plane on top of the same dashboard --
  the creator's own stated design scope for this same phase
  (`02-system-architecture.md` §6.2, captured 2026-09-06): logs, metrics
  history, LLM usage, and resource allocation first (read-only, mostly
  extending signal that already exists but isn't persisted/surfaced
  yet), then live-adjustable config (timeouts, skill enable/disable,
  worker count) behind admin authentication -- deliberately deferred,
  added later. §6.2 also flags the one constraint this needs to be
  designed against, not just built around: whether admin control
  actions go through Guardian's own guarded action path or become a
  second, parallel, unaudited way to change the system.
- Cutover: `sim.sh` → `python -m simorgh run`; `src/` reduced to a
  compatibility shim, then removed; docs updated; EVOLUTION milestone.

## 4. Parallelization plan for multiple agents

| Wave | Agents | Packages | Coordination needed |
|---|---|---|---|
| 0 | 1–2 | contracts, bus, ledger, kernel | one agent owns contracts; the other builds bus/ledger against it |
| 1 | 3 | A: cognition+memory · B: guardian+execution · C: worldmodel+persona+interface | none beyond contracts; each track has its own integration scenario |
| 2 | 2 | D: planning+orchestration · E: verification | E provides a fake `verify.result` for D's tests until real |
| 3 | 3 | learning · reflection · curiosity | none |
| 4 | up to 7 | one per capability item | each names the subsystem(s) it edits; no two agents edit one package at once |
| 5 | 2 | scale-out/adapters · cutover/docs | sequential at the end |

Rules for agents working in parallel are in `05-agent-build-instructions.md`.
The one hard rule: **never edit `simorgh/contracts/` without a
contracts PR reviewed by whoever owns Phase 0** — that directory is the
API every other agent is building against.

## 5. Definition of done (any subsystem)

- Spec in `docs/blueprint/subsystems/NN-<name>.md` is `reviewed` and the
  package README links to it.
- `Service` declares `consumes`/`produces`; the contracts test confirms
  every declared type exists; the boundary test passes.
- Contract tests: every produced message validates; every consumed type
  has a handler test with a valid and an invalid payload.
- Unit tests cover the spec's §5 components and §8 failure modes.
- At least one integration scenario in `tests/simorgh/integration/`
  runs on the `memory` bus and (if it touches durability) on `sqlite`.
- `python -m simorgh --self-check` still exits 0.
- No new third-party dependency in the core.
- Docs: spec §10 steps checked off; `02` §5 flows updated if changed;
  an `EVOLUTION.md` milestone entry.

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Contracts churn breaks parallel work | Phase 0 freezes v1 of the catalog; changes go through `compat.py` translators and a version bump; agents pin the version they built against |
| Bus adds latency to the chat turn | `memory` backend is in-process asyncio; request/reply is a direct future resolution; measured budget: < 5 ms overhead per hop |
| Over-engineering before value | Phases 1–3 are *ports* of working behavior; new capabilities wait until the bus is proven |
| Losing v1's live-caught lessons | `06-migration-from-v1.md` maps each lesson to its new home; tests carry over |
| Safety regression during migration | Guardian + token check land in Phase 1 before any autonomous work runs on v2; v1's `AuditGate` stays authoritative until Guardian's tests are a superset |
| Agents editing the same files | Package-per-subsystem ownership; Phase 4 items name their package; contracts are single-owner |
