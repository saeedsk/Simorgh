# Simorgh Architecture

See `project_simorgh_groundwork.md` at the repo root for the original design
brief, `docs/SOUL.md` for identity/values, and `docs/EVOLUTION.md` for the
long-term roadmap and the reasoning behind each piece below. This document
tracks what's actually built.

## Core principles

1. **The Orchestrator** is the central routing/synthesis engine. It holds
   the persona's identity and delegates work to sub-agents.
2. **Sub-agent sandboxing.** Each cognitive function runs in isolation.
   Skill agents in particular execute in a separate OS process with no
   access to the orchestrator's in-memory state.
3. **Shared memory bus.** Sub-agents don't pass large context windows to
   each other; they publish/subscribe to shared state instead.
4. **Continuous state tracking.** The persona's mood and cognitive load are
   tracked as continuous vectors, not fixed discrete moods.
5. **No single point of starvation.** Cognition, memory, and stability each
   have a guaranteed-available floor (rule-based agents, local disk, an
   automatic reset) beneath any richer/networked layer built on top.

## Implemented so far

| Piece | Module | Purpose |
|---|---|---|
| Soul | `docs/SOUL.md`, `src/orchestrator/soul.py` | The constitution: identity, personality, and the 8 priority-ordered Core Directives (Safety > Lawfulness > Loyalty > Corrigibility > Restraint > Stability > Growth > Transparency) everything else is checked against. |
| State machine | `src/orchestrator/persona_state.py` | Thread-safe `PersonaState` holding continuous `valence`, `arousal`, and `cognitive_load`, clamped to valid ranges, with bounded history. |
| Shared memory bus | `src/memory/shared_bus.py` | Publish/subscribe wrapper around a `PersonaState`. Any agent can `read()` the live mood or `publish_state`/`publish_delta` to change it; subscribers are notified synchronously with `(previous, new, source)`. |
| Sub-agent interface | `src/orchestrator/router.py` | `SubAgent` ABC (`handle(request, bus) -> AgentResponse`) and `Router`, which registers agents by name and dispatches requests to one or many of them. |
| Emotion agent | `src/agents/emotion/base.py` | Lexicon-based reaction to input text; nudges mood on the bus and returns a short reaction phrase. No LLM dependency -- part of the guaranteed-available floor. |
| Logic agent | `src/agents/logic/base.py` | Rule-based response drafting that reads current mood off the bus to shape tone. No LLM dependency. |
| Sandboxing framework | `src/sandboxing/sandbox.py` | `SandboxExecutor` interface plus `SubprocessSandbox`, a process-isolated, CPU/memory/time-bounded executor for running skill code. The sandboxed process never receives the `PersonaState` or `SharedMemoryBus` objects. |
| Skills agent | `src/agents/skills/base.py` | `SkillsAgent(SubAgent)` that runs request text through a `SandboxExecutor` and reports a small cognitive-load delta back through the bus. |
| CLI loop | `src/main.py` | Reads input, dispatches to emotion then logic, synthesizes their output using live mood from the bus. |
| Persistent memory | `src/memory/long_term.py` | `MemoryStore` interface; `JSONFileMemoryStore` (durable, local disk, fsync'd) and `InMemoryStore` (non-durable) implementations. Continuity of record, not process -- see `SOUL.md`. |
| Cognition router | `src/cognition/provider.py` | `LLMProvider` interface, `CognitionRouter` with automatic failover, and `DeterministicFallbackProvider` -- a zero-dependency floor that guarantees `complete()` never raises even with every real provider unreachable. |
| Health monitor | `src/orchestrator/health.py` | `HealthMonitor` inspects `PersonaState` history for pinned extremes, sustained overload, or oscillation, and auto-resets mood to neutral on a CRITICAL finding. |
| Reflection loop | `src/orchestrator/reflection.py` | `OutcomeLog` records action outcomes to a `MemoryStore`; `ReflectionAgent.reflect()` turns a sub-agent's elevated failure/correction rate into a `Proposal` -- data, never an automatic change. |
| Audit gate | `src/orchestrator/audit.py` | `AuditGate.review()` vets a `ModificationProposal` via a static denylist plus a real sandboxed run. `soul.py`/`SOUL.md`/`audit.py` itself are always-rejected subjects. `requires_human_approval` is always `True` under current policy. |

## Data flow (current)

```
AgentRequest ──▶ Router.dispatch(name, request)
                     │
                     ▼
              SubAgent.handle(request, bus)
                     │
        (skills agent only) ─▶ SandboxExecutor.run(code)  [isolated process]
                     │
                     ▼
            bus.publish_delta(source, ...)  ─▶ PersonaState.apply_delta
                     │
                     ▼
              AgentResponse ──▶ back to caller
```

The pieces built for resilience/growth (memory, cognition router, health
monitor, reflection loop, audit gate) exist as tested, standalone modules
today; they are not yet wired into the `main.py` CLI loop or `Router` --
see `docs/EVOLUTION.md`, "Concrete Milestones," items 6+.

## Not yet implemented

- Wiring `OutcomeLog` recording into `main.py`/`Router` so the reflection
  loop has real data instead of only synthetic test data.
- A concrete skill-research agent that actually produces
  `ModificationProposal`s for `AuditGate` to review -- the gate exists but
  has no producer feeding it yet.
- A distributed `SharedMemoryBus` backend and a `Node`
  registration/heartbeat abstraction for multi-host sub-agent placement
  (deliberately not built until there's real infrastructure to target).
- A CLI/notification surface for the creator to see and act on pending
  `AuditVerdict`s.
- `src/memory/short_term.py` (context window management) is still a
  placeholder stub.
