# Simorgh Architecture

See `project_simorgh_groundwork.md` at the repo root for the original design
brief, `docs/SOUL.md` for identity/values, `docs/EVOLUTION.md` for the
long-term roadmap, and `docs/BIOMIMICRY.md` for the biological grounding
behind several pieces below. This document tracks what's actually built.

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
6. **Nothing self-modifies unsupervised.** Proposals, trials, and pending
   approvals are all things this codebase produces; merging one into the
   live source is always a human action, never an automated one.

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
| Persistent memory | `src/memory/long_term.py` | `MemoryStore` interface with `add`/`get`/`query`/`delete`; `JSONFileMemoryStore` (durable, local disk, fsync'd, compacts on delete) and `InMemoryStore` (non-durable) implementations. Continuity of record, not process -- see `SOUL.md`. |
| Cognition router | `src/cognition/provider.py` | `LLMProvider` interface, `CognitionRouter` with automatic failover, and `DeterministicFallbackProvider` -- a zero-dependency floor that guarantees `complete()` never raises even with every real provider unreachable. |
| Health monitor | `src/orchestrator/health.py` | `HealthMonitor` inspects `PersonaState` history for pinned extremes, sustained overload, or oscillation, and auto-resets mood to neutral on a CRITICAL finding. |
| Reflection loop | `src/orchestrator/reflection.py` | `OutcomeLog` records action outcomes to a `MemoryStore`; `ReflectionAgent.reflect()` turns a sub-agent's elevated failure/correction rate into a `Proposal` -- data, never an automatic change. Wired live into `main.py`. |
| Audit gate | `src/orchestrator/audit.py` | `AuditGate.review()` vets a `ModificationProposal` through three layers: a static denylist (innate immunity), a learned check against previously rejected proposals (adaptive immunity, via `MemoryStore`), and a real sandboxed run. `soul.py`/`SOUL.md`/`audit.py` itself are always-rejected subjects. `requires_human_approval` is always `True` under current policy. |
| Skill research agent | `src/agents/skills/research.py` | `SkillResearchAgent.draft_skill(topic)` produces a real `ModificationProposal` via `CognitionRouter` -- honestly minimal without a real LLM provider registered, but the pipeline works end to end. |
| Live deployment | `src/orchestrator/deployment.py` | `DeploymentManager`: stage a candidate ("B") for a Router slot alongside the active version ("A"), trial both against cloned buses, `promote`/`rollback` hot-swaps the Router's live registration, `purge_retired` drops old versions once confident. Every step logged as `MemoryStore` lineage. |
| Consolidation ("sleep") | `src/orchestrator/consolidation.py` | `run_consolidation()`: one explicit maintenance pass -- runs `ReflectionAgent`, then prunes stale records per `MemoryStore` kind via `delete()`. Not a background daemon; always triggered explicitly. |
| Interests & world-awareness | `src/agents/interests.py` | `InterestTracker` persists tracked topics and decides what's overdue for follow-up; `WorldFeed`/`NullWorldFeed` is the (currently no-network) seam for a future real news/RSS integration. |
| CLI loop | `src/main.py` | Dispatches to emotion then logic and synthesizes their output using live mood; records every dispatch via `OutcomeLog`. Commands: `reflect` (outcome review), `propose <topic>`/`pending` (draft + audit a skill, list what's awaiting the creator's review), `interest <topic>`/`interests`/`curious` (world-awareness), `sleep` (maintenance). |

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
              AgentResponse ──▶ OutcomeLog.record(...) ──▶ back to caller
```

Self-modification pipeline (all reachable from the CLI today):

```
SkillResearchAgent.draft_skill(topic) ──▶ ModificationProposal
                     │
                     ▼
        AuditGate.review()  [denylist ─▶ adaptive-immunity memory ─▶ sandbox]
                     │
              approved_by_automation?
                 │              │
                no              yes
                 │               │
          printed + dropped   MemoryStore(kind="pending_approval")
                                 │
                                 ▼
                        creator reviews via 'pending' -- nothing auto-merges
```

## Not yet implemented

- A distributed `SharedMemoryBus` backend and a `Node`
  registration/heartbeat abstraction for multi-host sub-agent placement
  (deliberately not built until there's real infrastructure to target).
- A real `WorldFeed` implementation (RSS/API-backed) -- `curious` always
  reports no updates today, honestly, since only `NullWorldFeed` exists.
- A real `LLMProvider` registered ahead of the fallback in
  `CognitionRouter` -- until then, `SkillResearchAgent`'s drafts stay
  minimal by construction.
- Anything that actually merges an approved `pending_approval` proposal
  into the real source tree -- deliberately not built; per `SOUL.md`,
  that step is the creator's, by hand, not this codebase's.
- `src/memory/short_term.py` (context window management) is still a
  placeholder stub.
