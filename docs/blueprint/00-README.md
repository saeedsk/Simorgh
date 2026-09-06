# Simorgh v2 Blueprint

This directory is the complete design for Simorgh v2: a re-architecture
of Simorgh from a single-process, direct-call Python CLI into a modular,
message-driven, self-improving agent — a functional foundation for
general intelligence with a first-class harness for projects and
everyday work. It was written to be **built from**: a competent engineer
or an AI coding agent (e.g. Claude Code) should be able to take any one
subsystem spec, implement it in parallel with others, and prove
conformance with the provided tests, without further coordination.

The design is grounded in the research under `docs/KnowledgeBase/`
(general AGI: `AGI-00`…`AGI-06`; agent harness design and Claude Code's
own architecture: `harness-00`…`harness-06`) and in the lessons of
Simorgh v1 recorded in `docs/EVOLUTION.md`.

## Reading order

| # | File | What it is | Who reads it |
|---|---|---|---|
| 01 | [`01-vision-and-principles.md`](01-vision-and-principles.md) | Goals, the Simorgh metaphor, 15 binding design principles, non-goals, what v1 contributes | Everyone, first |
| 02 | [`02-system-architecture.md`](02-system-architecture.md) | The sixteen subsystems, layering, the structural safety topology, package layout and module rules, deployment modes, and nine worked message flows | Everyone |
| 03 | [`03-contracts-and-messaging.md`](03-contracts-and-messaging.md) | The message envelope, topic taxonomy, full v1 message catalog, delivery semantics, Bus/Ledger/Subsystem protocols, backends, versioning, security | Every builder |
| 04 | [`04-build-plan-and-roadmap.md`](04-build-plan-and-roadmap.md) | Phases 0–5, dependency graph, parallel tracks for multiple agents, acceptance criteria, definition of done, risks | Whoever coordinates |
| 05 | [`05-agent-build-instructions.md`](05-agent-build-instructions.md) | Exactly how an AI agent builds one subsystem: conventions, hard rules, step-by-step, testing standards, contracts-change process | Every builder, before coding |
| 06 | [`06-migration-from-v1.md`](06-migration-from-v1.md) | v1 → v2 module map, lessons that must survive (with tests), strangler procedure, data migration, cutover checklist | Builders porting v1 code |
| 07 | [`07-post-cutover-review.md`](07-post-cutover-review.md) | Architecture review after the cutover and first real use: what the live evidence showed, layer-by-layer verdict, decisions (wiring completions, governance), the testing-strategy change, the prioritized next wave, and an honest assessment of the build | Everyone, before the next wave |
| — | [`subsystems/TEMPLATE.md`](subsystems/TEMPLATE.md) | The mandatory structure of every subsystem spec | Spec authors |
| 01–16 | [`subsystems/`](subsystems/) | One detailed spec per subsystem (see table below) | The builder of that subsystem |

## The subsystems

| # | Subsystem | Package | Layer | Spec |
|---|---|---|---|---|
| 01 | Bus | `simorgh/bus/` | 0 Substrate | [`subsystems/01-bus.md`](subsystems/01-bus.md) |
| 02 | Ledger | `simorgh/ledger/` | 0 Substrate | [`subsystems/02-ledger.md`](subsystems/02-ledger.md) |
| 03 | Kernel | `simorgh/kernel/` | 0 Substrate | [`subsystems/03-kernel.md`](subsystems/03-kernel.md) |
| 04 | Cognition | `simorgh/cognition/` | 1 Cognitive core | [`subsystems/04-cognition.md`](subsystems/04-cognition.md) |
| 05 | Memory | `simorgh/memory/` | 1 Cognitive core | [`subsystems/05-memory.md`](subsystems/05-memory.md) |
| 06 | World Model (+ Self Model) | `simorgh/worldmodel/` | 1 Cognitive core | [`subsystems/06-worldmodel.md`](subsystems/06-worldmodel.md) |
| 07 | Planning | `simorgh/planning/` | 2 Agency | [`subsystems/07-planning.md`](subsystems/07-planning.md) |
| 08 | Execution | `simorgh/execution/` | 2 Agency | [`subsystems/08-execution.md`](subsystems/08-execution.md) |
| 09 | Guardian | `simorgh/guardian/` | 2 Agency | [`subsystems/09-guardian.md`](subsystems/09-guardian.md) |
| 10 | Verification | `simorgh/verification/` | 2 Agency | [`subsystems/10-verification.md`](subsystems/10-verification.md) |
| 11 | Learning | `simorgh/learning/` | 3 Growth | [`subsystems/11-learning.md`](subsystems/11-learning.md) |
| 12 | Reflection | `simorgh/reflection/` | 3 Growth | [`subsystems/12-reflection.md`](subsystems/12-reflection.md) |
| 13 | Curiosity | `simorgh/curiosity/` | 3 Growth | [`subsystems/13-curiosity.md`](subsystems/13-curiosity.md) |
| 14 | Persona | `simorgh/persona/` | 4 Self & surfaces | [`subsystems/14-persona.md`](subsystems/14-persona.md) |
| 15 | Interface | `simorgh/interface/` | 4 Self & surfaces | [`subsystems/15-interface.md`](subsystems/15-interface.md) |
| 16 | Orchestration | `simorgh/orchestration/` | X Cross-cutting | [`subsystems/16-orchestration.md`](subsystems/16-orchestration.md) |

## The design in five sentences

1. Sixteen small subsystems, one package each, share exactly one
   dependency — `simorgh/contracts` — and communicate only through typed,
   traceable messages on an async Bus with pluggable backends (in-memory,
   SQLite, optional AWS SNS/SQS).
2. All state is an append-only Ledger of events (JSONL/SQLite, optional
   DynamoDB); every status, rollup, competence estimate, and the Self
   Model are projections that can be rebuilt from the log.
3. Safety is structural: every action is *proposed*, only the Guardian
   can *approve* (with an HMAC-bound token), only Execution can *run*, and
   pause/stop/Plan Mode/protected files/budgets are enforced at that one
   chokepoint regardless of what any reasoning concluded.
4. The harness is Claude Code's shape — a minimal gather→act→verify loop
   surrounded by a rich operational harness: graduated context
   compaction, Plan Mode, a durable hierarchical backlog with a
   dependency DAG and re-grounding, checklist-and-trajectory verification
   with an evaluator-optimizer loop, and isolated sub-agent delegation.
5. Growth is a loop, not a feature: outcomes feed Learning (competence,
   strategies, skills, audited self-patches), Reflection (calibration,
   drift, the Self Model), and Curiosity (diversified exploration of real
   competence gaps) — so the system measurably learns what it can do,
   what it can't, and what to try next.

## Status and ownership

**All sixteen subsystems are built.** `tests/simorgh/integration/test_kernel_boots_all_sixteen_subsystems.py`
boots the real, unpatched `simorgh.kernel.registry.build_factories()` --
every real `Service`, in the real six-layer order -- and asserts all
fifteen non-kernel subsystems report healthy, twice in a row on the same
data directory. 1976+ tests passing across the whole build (v1's
original suite intact throughout). See `docs/EVOLUTION.md` milestones
98-103 for how it was built: Phase 0 (contracts, bus, ledger, kernel)
sequentially by dependency; the remaining twelve subsystems concurrently,
by nine parallel agents building against nothing but the frozen Phase 0
contracts (the blueprint's own graceful-degradation principle made this
safe); then one integration pass wiring every subsystem into the
Kernel's registry and proving the whole system boots together.

| Package | Spec status | Notes | Phase |
|---|---|---|---|
| contracts | **built** | v1 catalog: 123 types, 21 domains | 0 |
| bus | **built** | memory/sqlite/aws backends, all delivery semantics | 0 |
| ledger | **built** | memory/jsonl/sqlite/dynamodb backends, projections, blobs, compaction, `migrate-v1` | 0 |
| kernel | **built** | config, secrets, state machine, scheduler, supervisor, registry (all 15 subsystems wired), context, metrics/status, `--self-check`, CLI | 0 |
| cognition | **built** | provider routing/failover, budget accounting, tool-call parsing, compaction layers 1-2 | 1A |
| memory | **built** | working/episodic/semantic/procedural, retrieval, confidence/decay, consolidation | 1A |
| worldmodel | **built** | env facets (capability map, file index, git state, tools); static Self Model shell | 1C |
| guardian | **built** | 8-rule pipeline, real HMAC tokens, posture that only tightens | 1B |
| execution | **built** | independent token re-verification, ported tools incl. `git_commit`/`git_revert` | 1B |
| verification | **built** | mechanical + semantic + trajectory verdict pipeline, idempotent replay | 2E |
| planning | **built** | Task/Project model, dependency DAG, rollup, fuzzy dedupe, Plan Mode, re-grounding | 2D |
| learning | **built** | competence tables, outcome recording, self-patch pipeline (policy only) | 3 |
| reflection | **built** | health monitor, pattern mining, calibration (Brier score), drift detection, self-critique | 3 |
| curiosity | **built** | diversified sampling (proven by regression test), interests, project proposals | 3 |
| persona | **built** | continuous mood, emotion floor, voice, user model, share pacing | 1C |
| interface | **built** | command dispatch, Flow 5 (pause/resume/stop), vitals projection, honest degradation | 1C |
| orchestration | **built** | Worker (gather-act-verify loop), turn/task sessions, sub-agent delegation, resume | 2D |

Every package's own `Status:` header in `subsystems/NN-*.md` and each
build's own contract-gap notes (`§12` of each spec) are the authoritative
detail; this table is the index.

Claim a package by editing this table and the spec's header (see `05` §7).

## Changelog

- 2026-09-06 — Initial blueprint: 01–06 core documents, spec template,
  sixteen subsystem specs (~54,000 words) written in parallel by five
  agents from the core documents.
- 2026-09-06 — Integration pass after the specs landed. Contract
  additions folded into `03` §4 (all non-breaking, catalog stays v1):
  `turn.completed`; `task.create`/`task.list.request`/`task.work_next.request`;
  `task.created.scope`; `task.step` trajectory fields and optional
  `confidence` on steps/results/verdicts; `system.pause/resume/stop.scope`;
  `system.restart`/`system.reload`; `system.schedule.*`; a `guardian`
  domain (`guardian.review`, posture changed/request); `learn.pipeline.run/
  .completed` and `learn.strategy.suggest`; `cognition.compact.*` and
  optional `cognition.think` fields; `memory.contradiction.flagged` and
  retrieval budget/filters; `self.gaps`/`world.env.query` reply fields
  incl. a bounded `file_index` preview; `percept.text.received`
  `channel: command`/`steer`; `reflect.review.request`; Curiosity's
  command requests; `Ledger.put_blob/get_blob/compact`; `Context`
  identity fields. Ownership rules made explicit in `02`/`03`: one
  writer per stream (`self:model` → World Model, `plan:<id>` → Planning),
  publish restrictions on `action.approved`/`action.denied`, subsystem
  identity authentication in multi-process modes, no `partition_key` on
  priority-9 messages, dead letters mirrored to the Ledger, per-type
  trace sampling, the Learning↔Execution↔Verification split for the
  drafting loop (Flow 4), and Interface owning every human-facing status
  surface. Open questions the spec authors recorded (each with a default)
  live in each spec's §12.
- 2026-09-06 — All sixteen subsystems built and integrated. Phase 0
  (contracts, bus, ledger, kernel) built sequentially by dependency;
  the remaining twelve subsystems (cognition, memory, worldmodel,
  guardian, execution, verification, planning, learning, reflection,
  curiosity, persona, interface) built concurrently by nine parallel
  agents against the frozen Phase 0 contracts alone, each proving
  itself against a real Kernel boot before this session verified and
  pushed it. A final integration pass wired all fifteen non-kernel
  subsystems into `kernel/registry.py`'s `build_factories()` (left
  untouched by every build, per a coordination note the Phase 0 build
  left there) and added `test_kernel_boots_all_sixteen_subsystems.py`,
  which boots the real, unpatched registry end to end and confirms
  every subsystem reports healthy. One real module-boundary violation
  (an unauthorized push carried Planning out with an internal
  `ledger.api` import instead of the public `ledger.client` boundary)
  was found and fixed during verification. See `docs/EVOLUTION.md`
  milestones 102-103 for the full account, including every real bug
  found while porting v1 behavior into the new architecture. Full
  status table above; every package's own spec header and §12 carry
  its build's own detail and contract-gap notes.
- 2026-09-06 — `simorgh/contracts/` built (Phase 0, first package). Doc
  fix while building: `turn` and `project` are their own first segment on
  the wire, so they are domains; added to `03` §3's table (the prose had
  listed them under `task.*`/`plan.*` only). Two shapes the prose left
  open were pinned in code, non-breaking: `task.completed.verification_ref`
  is a required-but-nullable key (a plan-mode completion has no review),
  and `system.status.reply` is a minimal open object (`state`, `mode`,
  `run_id`, `subsystems`, `uptime_seconds`, optional `metrics`) pending
  the Kernel build. Every `*.reply` admits the §9 error shape as a second
  `anyOf` branch, and its success branch forbids `ok: false`.
- 2026-09-06 — `simorgh/bus/` built (Phase 0): event/command/request-reply
  over `memory` (asyncio, the guaranteed floor), `sqlite` (one WAL file,
  multi-process, proven with a real `multiprocessing` test), and `aws`
  (SNS+SQS+DLQ, driven end-to-end against a fake boto3 session, never the
  network). Reserved-topology enforcement (`enforcement.py`) plus
  subsystem-token identity for multi-process modes; the trace writer
  (Ledger `trace:<trace_id>`, per-type sampling, blob refs, buffer-and-
  replay on a ledger outage). Two real bugs found by the spec's own
  property tests, fixed before commit: `BusClient.new()` was passing
  `partition_key=None` explicitly to a caused-by message, which defeated
  `Message.caused()`'s inherit-from-parent default (a follow-on message
  silently lost its parent's ordering key); the sqlite reaper's lock
  release required an exact `delivery_id` match on a table already keyed
  by `(grp, partition_key)`, so a lock could survive its own reap if the
  two ever disagreed. Also made `TraceWriter` lazily self-starting on
  first `write()` rather than requiring an explicit `start()` first --
  found by a test that (correctly) never called it, which is exactly the
  kind of silent-no-tracing bug a real subsystem could hit too.
  1041 tests passing (v1 + contracts + 68 new for the bus).
- 2026-09-06 — `simorgh/ledger/` built (Phase 0): the `memory` (tests),
  `jsonl` (default -- v1's own fsync-per-append/atomic-rewrite discipline
  carried over verbatim, plus partial-trailing-line recovery on restart),
  `sqlite` (WAL, `BEGIN IMMEDIATE`-serialized writers, PK-based CAS -- the
  recommended `local-multi` engine, proven with a real concurrent-CAS
  test), and `dynamodb` (conditional-put CAS, S3 blobs, lazy `boto3`,
  exercised entirely through in-memory fakes of its two adapter protocols
  -- no credentials, no network) backends behind `LedgerClient`:
  validation (stream grammar, canonical/NaN-free payloads, the blob-
  threshold rule), idempotency-key dedupe, `tail()` with per-stream
  cursors, `Projection`/`rebuild`/`materialize` (snapshot + replay, a
  corrupt snapshot falls back to a full replay rather than getting
  stuck), a content-addressed blob store, and record compaction/
  retention (distinct from context compaction) with an explicit
  protected-prefix list. `migrate_v1.py` makes the Kernel's future
  `migrate-v1` command a plain, idempotent replay of v1's own
  `~/.simorgh/memory.jsonl` shape, routed per `06-migration-from-v1.md`
  section 5. Doc fixes (spec section 12's own open question 1, resolved):
  `contracts.protocols.Ledger` already carries `put_blob`/`get_blob`/
  `compact` from the integration pass, so no further protocol change was
  needed. Spec section 5.5 described the jsonl lock as held for the
  backend's whole lifetime while section 5.4 described it as per-append;
  built per-append (the file lock is taken only around each write/
  rewrite), so `sqlite`/`jsonl` interleave correctly under concurrent
  writers instead of one process locking the other out entirely.
  1188 tests passing (v1 + contracts + bus + 158 new for the ledger).
- 2026-09-06 — `simorgh/kernel/` built (Phase 0, the composition root, and
  the last Phase 0 package): config load/merge/env-override, layered
  secrets (`env`/`file`/`chained`/`scoped`, a `ScopedSecretStore` so a
  subsystem can read only what its config section declares plus, for
  `guardian`/`execution` only, the per-run HMAC secret), the state machine
  (`booting → running ↔ paused → stopping → stopped`, plus terminal
  `failed`, scoped `autonomous` pauses distinct from a full pause), the
  Scheduler (idle/second/sleep tick loops off an injected `Clock`, durable
  `system.schedule.*` timers re-armed from the Ledger on every boot -- a
  v1 reminder was a `threading.Timer` a restart simply forgot), the
  Supervisor (layer-ordered concurrent boot gated on health, restart
  backoff table, a 10-minute restart-budget window, `SAFETY_CRITICAL`
  auto-pause when `guardian`/`execution` exhausts its budget), the
  registry (the one place — besides `contracts`/bus/ledger clients — a
  Kernel module is allowed to import another subsystem's `Service`), the
  `ContextFactory` (one `BusClient` and one scoped secret store per
  subsystem), the status/metrics server, and `--self-check` — the
  structural safety proof required before any real work runs: a stub
  Guardian/Execution speak the real token contract (`contracts.security`)
  over the real Bus/Ledger, proving a legitimate approval executes, a
  forged token is rejected by Execution's own verification before any
  tool runs, a paused system denies new proposals, and a non-Guardian
  source cannot subscribe to `action.proposed` — the reserved-topology
  policy already built into the bus, exercised for real rather than
  hoped for. `python -m simorgh --self-check` now passes for the first
  time (`OVERALL: PASS`, all four steps), completing Phase 0 end to end:
  `contracts → bus/ledger → kernel`, boot to `running` and back to
  `stopped` on a real in-memory bus/ledger pair, verified by four
  integration tests (`tests/simorgh/integration/`): booting two toy
  Phase-1-stand-in subsystems through the real layer-ordered Supervisor,
  `pause` suspending the Scheduler's own tick loops and `resume`
  restoring them, a schedule added before a simulated crash surviving a
  second, independent `Kernel` pointed at the same on-disk Ledger, and a
  toy `guardian` exhausting its restart budget auto-pausing the Kernel
  through the real `Supervisor` restart-budget logic (not just the
  handler in isolation). Doc fix while building: `03`'s self-check
  walkthrough (§5.4) frames step 2 as testing Execution's own token
  verification, not a bus publish-policy violation — the Kernel is an
  allowed publisher of `action.approved` (`PUBLISH_ONLY_BY`), so a
  forged one is a token failure caught downstream, not a policy denial
  caught at publish time; step 4 (a throwaway source subscribing to
  `action.proposed`) is the actual policy-violation proof. Phase 0 is
  now complete; Phase 1A/1B/1C tracks (cognition/memory, guardian/
  execution, worldmodel/persona/interface) can start in parallel, each
  against the same frozen `contracts` catalog and the same Kernel to
  boot into.
  1336 tests passing (v1 + contracts + bus + ledger + 148 new for the
  kernel: 139 unit, 9 integration).
- 2026-09-06 — Phases 1-3 and the full integration pass, condensed (the
  blow-by-blow, including every live-caught bug and its fix, lives in
  `docs/EVOLUTION.md` milestones 102-107; this entry is the changelog's
  own catch-up after several sessions' worth of unbroken build). All
  twelve remaining subsystems (cognition, memory, worldmodel, guardian,
  execution, verification, planning, learning, reflection, curiosity,
  persona, interface) built against the frozen Phase 0 contracts, then
  wired into `kernel/registry.py` and proven to boot together as one
  system for the first time (`test_kernel_boots_all_sixteen_subsystems.py`).
  That proof was necessary but not sufficient: actually *running* Sim
  live (not just its test suite) surfaced two real gaps invisible to
  every existing test because none of them exercised the real entry
  point — `percept.text.received` was never wired to a reply at all
  (milestone 104), and `turn.completed` never triggered Memory's
  episodic write, so there was no continuity across turns (milestone
  105) — both fixed and verified live. A third pass made `python -m
  simorgh run` genuinely interactive for the first time (`run_repl` had
  been hardcoded off since Phase 0) and, once live concurrent chat
  traffic actually existed to expose it, found and fixed a session-id
  cross-wire bug in Interface (milestones 106-107).
- 2026-09-06 — Phase 4 Wave 1 complete: all four independent new-
  capability items (Plan Mode + approval policy, the evaluator-optimizer
  loop, skill acquisition as procedural memory, context-compaction
  layers 3-5) built in isolated git worktrees rather than concurrent
  forks sharing one working tree — zero shared-file collisions this
  time, a clean merge for all four (contrast Phase 1/3's unauthorized
  push and module-boundary violation, both real cleanup work). Full
  detail, including the specific bugs each fork found versus what
  already existed, in `docs/EVOLUTION.md` milestones 108-111. Three of
  the four forks found the session-mechanics for their item already
  substantially built and the real gap narrower than the roadmap's
  one-line description suggested — reading the actual code against the
  actual spec before writing anything is what made each fork close a
  real gap instead of duplicating existing work. Wave 2 (re-grounding +
  drift detection, trust posture, Self Model completeness — all three
  touch `reflection`, so handled as one combined thread rather than
  three colliding parallel forks) is next.
