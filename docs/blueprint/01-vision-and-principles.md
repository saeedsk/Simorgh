# 01 — Vision and Principles

> Part of the Simorgh v2 blueprint. Read `00-README.md` first for how this
> set fits together. This file states *what we are building and why*, and
> the design principles every later file and every subsystem spec must
> obey. When a subsystem spec and this file disagree, this file wins.

## 1. The name is the architecture

In Attar's *Conference of the Birds*, thirty birds (*si morgh*) set out to
find the mythical Simorgh, and at the end of the journey discover that the
Simorgh is nothing other than themselves, together. That is precisely the
architectural thesis of this blueprint:

**Simorgh v2 is not one mind. It is a conference of specialized
subsystems — each small, testable, independently evolvable — that
together, through a shared nervous system of messages, behave as one
coherent, self-aware, self-improving agent.**

Everything in this document set follows from taking that seriously:

- The subsystems are the birds. Each has one job, one interface, one
  directory, its own tests, and can be rebuilt or replaced by a separate
  team (or a separate AI agent) without touching the others.
- The **Bus** is the conference: an asynchronous, typed, durable message
  fabric. Subsystems never call each other directly; they publish what
  happened and subscribe to what they care about. The "loop with many
  feedback paths" that the AGI research says is the actual hard part
  (`docs/KnowledgeBase/AGI-04-architecture-and-subsystems.md`, "How the
  subsystems interrelate") is not a diagram here — it *is* the wiring.
- The **Ledger** is the shared memory of the journey: every event,
  decision, action, outcome, and self-observation is appended, never
  overwritten, so the system's current state — including its model of
  itself — is always reconstructible and auditable.
- **Self-awareness** is not a mood or a prompt. It is a concrete,
  measurable artifact — the Self Model — maintained by the Reflection
  subsystem from the Ledger, consulted by Planning and Curiosity, and
  rendered into every reasoning call. The system knows what it can do,
  how well, what it has changed about itself, and what it is uncertain
  about, because those facts are stored, updated, and read like any
  other data.

## 2. What we are building

The creator's stated goal, restated as engineering targets, each tied to
the knowledge base that grounds it:

| Goal (creator's words) | Engineering target | Grounding |
|---|---|---|
| Adaptive, evolving | Every subsystem hot-replaceable; behavior driven by durable state and config, not hardcoded flow; graduated trust that changes over time | harness-01 principles: externalized policy, graduated trust, composable extensibility |
| Self-improving, learns new things | A Learning subsystem that turns outcomes into competence estimates, strategies, skills, and audited self-patches; a consolidation ("sleep") pathway from episodic to semantic memory | AGI-04 §3 (memory consolidation), §6 (learning); harness-06 gaps |
| Planning, reasoning | Deliberative planning (goal → project → task DAG, Plan Mode, re-grounding, receding-horizon replanning) over reactive execution within each step; a Cognition engine with multi-provider routing, ensemble reconciliation, and a graduated context-compaction pipeline | AGI-03 §1–2, AGI-04 §4; harness-01 (compaction, Plan Mode), harness-03 |
| Discovering new areas, creative | A Curiosity subsystem with intrinsic drives (novelty, competence gaps, interests) and structured, diversified exploration that never lets the model pick its own favorite neighborhood | AGI-02 §3 (self-directed goal generation), AGI-03 §10; this session's `capability_map.py` fix |
| Personality | A Persona subsystem owning identity, continuous emotional state, voice, social cognition (a model of the user), and proactive sharing — a first-class subsystem, not a prompt prefix | AGI-03 §6, §8; `docs/SOUL.md` |
| More and more self-aware | The Self Model (in World Model) + Reflection: capability inventory, calibrated competence, known limitations, change history, open questions about itself — measured, updated, and used | AGI-03 §9, AGI-04 §7 |
| A capable, functional harness for projects and general work | An Orchestration subsystem implementing the minimal gather→act→verify loop; Planning's durable hierarchical backlog; Verification's checklist + trajectory evaluation and evaluator-optimizer iteration; multi-agent delegation with isolation | harness-01, -02, -03, -04, -05 |
| Modular, clear interfaces, async messaging, API-based, host anywhere | One package per subsystem, contracts as the only shared dependency, a Bus with pluggable backends (in-memory, SQLite, AWS SNS/SQS) and a Ledger with pluggable backends (JSONL, SQLite, DynamoDB), stdlib-only core | Creator's explicit constraints |

### 2.1 What "AGI" means for this blueprint

The knowledge base is careful that AGI has no single definition
(`AGI-01`). This blueprint adopts a **capability-and-process** stance:
Simorgh v2 is built to *have the subsystems a general intelligence
needs, wired as a feedback loop*, and to *measure its own generality
honestly* rather than to claim any level. Concretely, the system's own
Self Model tracks, per task type, its competence and calibration; the
Verification subsystem measures whether work actually achieved intent
(not merely ran); and the Reflection subsystem records what the system
cannot yet do. Progress toward generality is a queryable number in the
Ledger, not a marketing claim.

## 3. Non-goals (explicitly)

- **Not a new foundation model.** Reasoning comes from external LLM
  providers behind the Cognition subsystem, with a deterministic rule-based
  floor beneath them. Weight-level learning is out of scope; learning here
  means memory, skills, strategies, and audited code changes.
- **Not embodiment.** No sensors/actuators in v2. Perception is text,
  files, web content, tool results, and time. The Perception interface is
  designed so richer modalities can be added later without touching
  downstream subsystems.
- **Not a distributed system on day one.** Multi-process and multi-host
  are supported by the Bus/Ledger abstractions and are a *configuration*
  choice, but the reference deployment is one host, one process (or a
  few), no cloud dependency.
- **Not a rewrite of the safety posture.** The constitution
  (`docs/SOUL.md`) and its priority-ordered directives (Safety >
  Lawfulness > Loyalty > Corrigibility > Restraint > Stability > Growth >
  Transparency) are preserved verbatim as the Guardian's charter. v2 makes
  their enforcement *structural* (see §4.3) rather than loosening it.

## 4. Design principles (binding)

These are ordered roughly by how often they will decide a design
argument. Each subsystem spec must state how it honors the ones that
apply to it.

### 4.1 Minimal core loop, maximal operational harness
The agent loop is deliberately tiny (gather context → act → verify,
repeat). All real complexity — permissions, compaction, checkpoints,
delegation, persistence, observability — lives in separately-engineered,
separately-tested subsystems around it. Never make the loop clever to
avoid building a harness mechanism. (harness-01)

### 4.2 Messages, not calls
Subsystems communicate only through typed messages on the Bus, defined
once in `simorgh/contracts/`. A subsystem may import `contracts`, the Bus
and Ledger client types, and the standard library — never another
subsystem. This is enforced by an automated boundary test, not by
convention. It is what makes parallel development and independent
evolution real rather than aspirational.

### 4.3 Structural safety: the Guardian sits on the action path
Nothing executes because a model decided it should. Every action is
*proposed* on the Bus; only the Guardian subscribes to proposals; only
the Guardian can emit an approval, cryptographically bound to the exact
action; the Execution subsystem runs only approved actions and verifies
the binding. Plan Mode, pause, stop, protected files, budgets, and
deny-first policy are all enforced at this one chokepoint, independent
of any reasoning that produced the proposal. (AGI-04 §9; harness-01
"deny-first", "defense in depth")

### 4.4 Append-only durable state; derived views are recomputable
All state changes are events appended to the Ledger. A task's status, a
project's rollup, the Self Model, competence estimates, trust scores —
all are projections that can be rebuilt from the log. Nothing is
silently overwritten; the plan changing is itself an event. (harness-01
"append-only durable state"; harness-05 §7; Sim v1's own
`TaskStore`/`MemoryStore`)

### 4.5 Guaranteed floor, graceful degradation
Every capability that depends on an external provider has a
deterministic, dependency-free floor beneath it and degrades to it
honestly — never fabricating success. Budget exhaustion, provider
outage, parse failure, and reviewer silence are routine conditions with
defined behavior, not crashes. A non-answer is never graded as a
failure. (Sim v1 doctrine; harness-04)

### 4.6 Context is a scarce resource, managed progressively
Every reasoning call passes through a graduated context pipeline —
budget caps on tool results, trimming, reference substitution, read-time
collapse, and only as a last resort model summarization. Persistent
instructions (constitution, self model summary, project rules) are
configuration, never at risk of being compacted away. (harness-01
five-layer pipeline; harness-06 gap #2)

### 4.7 Plan before you act; re-ground while you act
Work that cannot be fully enumerated up front is a *project* with an
explicit planning phase producing a durable plan artifact, reviewed
before execution (by a human where stakes warrant, by an independent
pass otherwise). Long-running work periodically re-states its goal and
checks that the next step still serves it; plan changes are logged with
reasons. (harness-03; harness-06 gaps #1, #3)

### 4.8 Verify intent, not just execution; iterate with feedback
"It ran" ≠ "it's done." An independent evaluator checks against a
task-specific checklist and the trajectory, with an explicit
insufficient-evidence outcome, and feeds specific corrections back into
a bounded generate→evaluate→revise loop before anything is marked done.
(harness-02 evaluator-optimizer; harness-04; harness-06 gap #5)

### 4.9 Isolation is the default for delegation
A delegated sub-agent starts with its own context (or an explicit fork
of the parent's), has a bounded step budget and delegation depth, and
returns only a summary. Exploration noise never reaches the delegating
context. (harness-01 subagents; AGI-04 §10)

### 4.10 Reversibility-weighted oversight
Read-only and reversible actions get light oversight; oversight scales
with how hard an action is to undo. Every applied change is a
revertible commit; anything with external side effects is gated, not
"undone." (harness-01)

### 4.11 Graduated trust — tightening is automatic, loosening is human
Trust and permission posture are a spectrum tracked in the Ledger.
Failure streaks, budget pressure, and drift tighten automatically. Any
loosening of a safety gate is a human configuration change, never a
self-modification. (harness-05 §5; harness-06 "smaller notes")

### 4.12 Transparent, file-based configuration and self-knowledge
The constitution, persona, self model summary, subsystem configs, and
plans are human-readable, diffable text/JSON in the repository or the
data directory — never an opaque store. Every autonomous action is
announced and logged with its reason. (harness-01; SOUL Directive 8)

### 4.13 Diversity by construction
Where the system chooses what to work on, the *choice of area* is made
by structured sampling over real inventories (the capability map, the
competence gaps in the Self Model, tracked interests), and the model is
only asked to propose within an already-chosen area. This is what
prevents thematic collapse. (this session's live-caught repetition
problem and its fix)

### 4.14 Stdlib core, optional adapters
The core runtime (bus in-memory/SQLite, ledger JSONL/SQLite, kernel,
all cognitive subsystems) depends only on the Python standard library,
so Simorgh runs anywhere Python runs. External services (LLM providers,
AWS SNS/SQS/DynamoDB, embeddings) are optional adapters behind
contracts, discovered at runtime, and absent cleanly.

### 4.15 Everything has a test, a spec, and an owner
No subsystem is "done" without: its spec in `docs/blueprint/subsystems/`,
contract tests proving it speaks the message catalog correctly, unit
tests, at least one integration scenario, and a README pointing at all
of the above. The boundary test must pass. See `05-agent-build-instructions.md`.

## 5. What is preserved from v1, and why

Simorgh v1 (`src/`) is not a failed prototype; it is a working system
with ~20k lines, ~890 tests, a constitution, and real, live-caught
lessons recorded in `docs/EVOLUTION.md`. v2 preserves its *ideas* and
much of its *code* by porting modules into subsystems (see
`06-migration-from-v1.md`):

- The constitution and directive ordering (`docs/SOUL.md`) → Guardian charter, Persona identity.
- Event-sourced stores (`MemoryStore`, `TaskStore`, `ActivityLog`) → the Ledger and its projections.
- The audit gate's layered immune system, protected subjects, sandboxed execution, isolated full-test-suite verification, auto-commit-never-push, relaunch-with-self-check-and-rollback, hot-swap trials → Guardian, Execution, Verification, Learning.
- The Task/Research/Project harness, capability map, fuzzy dedupe → Planning, Curiosity, Orchestration.
- Persona state as continuous vectors, health monitor, emotion agent, socializing → Persona, Reflection.
- Providers, budget guards, tool protocol, marker parsing, first-line-argument and non-answer lessons → Cognition, Execution.
- The autonomous idle loop with cooldowns, daily caps, and circuit breaker → Kernel scheduler + Curiosity + Guardian trust posture.

What v2 changes is the *shape*: from one 3,300-line `main.py` wiring
everything through direct calls and daemon threads, to sixteen
subsystems wired by messages, each owning its state as Ledger streams,
each independently buildable and replaceable.

## 6. Success criteria for the blueprint itself

This document set succeeds if a competent engineer or a Claude Code
agent, given only this directory and the repository, can:

1. Explain the whole system's data flow for a chat turn, an autonomous
   task, a project, a self-patch, and a stop command from `02-system-architecture.md` alone.
2. Implement any single subsystem to its spec, in parallel with others
   implementing theirs, without coordination beyond the contracts.
3. Prove conformance with the provided contract and boundary tests.
4. Migrate v1 incrementally with the test suite green at every step.

Everything else in `docs/blueprint/` exists to make those four things
true.
