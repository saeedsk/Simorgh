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

| Package | Spec status | Build owner | Phase |
|---|---|---|---|
| contracts | built (v1 catalog: 123 types, 21 domains) | Phase 0 agent | 0 |
| bus, ledger, kernel | complete draft | unassigned | 0 |
| cognition, memory | complete draft | unassigned | 1A |
| guardian, execution | complete draft | unassigned | 1B |
| worldmodel, persona, interface | complete draft | unassigned | 1C |
| planning, orchestration | complete draft | unassigned | 2D |
| verification | complete draft | unassigned | 2E |
| learning, reflection, curiosity | complete draft | unassigned | 3 |

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
