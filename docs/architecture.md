# Simorgh Architecture

See `project_simorgh_groundwork.md` at the repo root for the original design
brief and directory layout. This document tracks what's actually built.

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

## Implemented so far

| Piece | Module | Purpose |
|---|---|---|
| State machine | `src/orchestrator/persona_state.py` | Thread-safe `PersonaState` holding continuous `valence`, `arousal`, and `cognitive_load`, clamped to valid ranges, with bounded history. |
| Shared memory bus | `src/memory/shared_bus.py` | Publish/subscribe wrapper around a `PersonaState`. Any agent can `read()` the live mood or `publish_state`/`publish_delta` to change it; subscribers are notified synchronously with `(previous, new, source)`. |
| Sub-agent interface | `src/orchestrator/router.py` | `SubAgent` ABC (`handle(request, bus) -> AgentResponse`) and `Router`, which registers agents by name and dispatches requests to one or many of them. |
| Sandboxing framework | `src/sandboxing/sandbox.py` | `SandboxExecutor` interface plus `SubprocessSandbox`, a process-isolated, CPU/memory/time-bounded executor for running skill code. The sandboxed process never receives the `PersonaState` or `SharedMemoryBus` objects. |
| Skills agent | `src/agents/skills/base.py` | `SkillsAgent(SubAgent)` that runs request text through a `SandboxExecutor` and reports a small cognitive-load delta back through the bus. |

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

## Not yet implemented

- `emotion` and `logic` sub-agents (only the `SubAgent` interface and the
  `skills` agent exist so far).
- `src/memory/short_term.py` (context window management) and
  `src/memory/long_term.py` (vector DB-backed permanent memory) are
  placeholder stubs.
- `src/main.py` CLI loop tying orchestrator, agents, and bus together.
