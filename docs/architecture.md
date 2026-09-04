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
| Logic agent | `src/agents/logic/base.py` | When given a `CognitionRouter`, calls a real LLM (persona + mood + recent `ShortTermMemory` context folded into the prompt) for the actual conversational response. Falls back to the original rule-based drafting -- unchanged, still the guaranteed floor -- whenever no `CognitionRouter` is given, a real provider raises, or only the deterministic echo answered. `main.py` wires this by default; every existing rule-based test still passes unmodified since `cognition` defaults to `None`. |
| Sandboxing framework | `src/sandboxing/sandbox.py` | `SandboxExecutor` interface plus `SubprocessSandbox`, a process-isolated, CPU/memory/time-bounded executor for running skill code. The sandboxed process never receives the `PersonaState` or `SharedMemoryBus` objects. |
| Skills agent | `src/agents/skills/base.py` | `SkillsAgent(SubAgent)` that runs request text through a `SandboxExecutor` and reports a small cognitive-load delta back through the bus. Registered by default in `build_router()`; reachable live via the CLI's `run <code>` command. |
| Persistent memory | `src/memory/long_term.py` | `MemoryStore` interface with `add`/`get`/`query`/`delete`; `JSONFileMemoryStore` (durable, local disk, fsync'd, compacts on delete) and `InMemoryStore` (non-durable) implementations. Continuity of record, not process -- see `SOUL.md`. |
| Short-term memory | `src/memory/short_term.py` | `ShortTermMemory`: a bounded, non-durable rolling window of recent turns (by count and rough char budget), rendered via `as_context()` for a future cognition prompt. Wired into `main.py`'s `history` command. |
| Cognition router | `src/cognition/provider.py` | `LLMProvider` interface, `CognitionRouter` with automatic failover, and `DeterministicFallbackProvider` -- a zero-dependency floor that guarantees `complete()` never raises even with every real provider unreachable. |
| Budget guard | `src/cognition/budget.py` | `BudgetGuard`: wraps any real `LLMProvider` with a durable (survives restarts, via `MemoryStore`), rolling-window call/spend cap. Exhaustion raises `ProviderUnavailable`, so `CognitionRouter` degrades to the free deterministic floor exactly like a provider outage. **Any real, paid provider must be wrapped in this before being registered** -- see `docs/BIOMIMICRY.md`, "Metabolic conservation under scarcity." |
| Gemini provider | `src/cognition/gemini_provider.py` | `GeminiProvider`: calls Gemini's stable `generateContent` API (not the beta Interactions API) via `google-genai`, lazily imported so it's never required unless actually used. Reads the API key only from `GEMINI_API_KEY`/`GOOGLE_API_KEY` -- never hardcoded, never logged. `main.py`'s `build_cognition_router()` wraps it in `BudgetGuard` (default: $1.00/50 calls per 24h, both overridable via env vars) before registering it; with no key set, this provider is simply absent. |
| Claude Code CLI provider | `src/cognition/claude_code_provider.py` | `ClaudeCodeProvider`: spawns `claude -p <prompt> --output-format json --disallowedTools "*" --bare` (no pip dependency -- shells out to a separately-installed `claude` binary), billed against the caller's Claude subscription rather than the API. `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`/`CLAUDE_CODE_OAUTH_TOKEN` are stripped from the subprocess environment (Claude Code's own credential precedence ranks all three above the subscription OAuth session). `--disallowedTools "*"` removes every tool from Claude's context -- used purely as a text-drafting backend, never given file/bash access, and `--dangerously-skip-permissions` is never passed. Each call also runs from a fresh empty temp dir as defense-in-depth. Wrapped in `BudgetGuard` using the CLI's own reported `total_cost_usd` (via `BudgetGuard`'s `cost_usd` metadata override) and a call-count cap (default 30/5h) -- registered ahead of Gemini in `build_cognition_router()` per the creator's preference to use the flat-rate subscription first. |
| Health monitor | `src/orchestrator/health.py` | `HealthMonitor` inspects `PersonaState` history for pinned extremes, sustained overload, or oscillation, and auto-resets mood to neutral on a CRITICAL finding. Wired live into `main.py`: a CRITICAL reset now surfaces as part of the reply itself. |
| Reflection loop | `src/orchestrator/reflection.py` | `OutcomeLog` records action outcomes to a `MemoryStore`; `ReflectionAgent.reflect()` turns a sub-agent's elevated failure/correction rate into a `Proposal` -- data, never an automatic change. Wired live into `main.py`. |
| Audit gate | `src/orchestrator/audit.py` | `AuditGate.review()` vets a `ModificationProposal` through three layers: a static denylist (innate immunity), a learned check against previously rejected proposals (adaptive immunity, via `MemoryStore`), and a real sandboxed run. `soul.py`/`SOUL.md`/`audit.py` itself are always-rejected subjects. `requires_human_approval` is `False` under current policy (creator-authorized, see `SOUL.md`) -- a passing verdict applies immediately via `apply_proposal`. |
| Apply | `src/orchestrator/apply.py` | `apply_proposal()`: the one place allowed to write a proposal's code to disk. Independently re-enforces the `src/agents/skills/`-only scope (a second boundary beyond AuditGate's own protected-subject check), refuses path traversal, and logs every write (`kind="applied_skill"`). Never runs `git commit`/`git push` -- applied changes are ordinary uncommitted working-tree changes. |
| Web fetch tool | `src/tools/web_fetch.py` | `WebFetchTool.fetch(url)`: real, reviewed outbound network access -- deliberately hand-built, not LLM-drafted (`AuditGate`'s denylist blocks `urllib.request`/`http.client`/`requests` in any drafted skill precisely so this is the only path). http/https GET only; SSRF protection (blocks private/loopback/link-local/reserved/multicast resolved addresses); bounded timeout and response size; durable, rolling-window rate limit; every attempt logged (`kind="web_fetch"`). Reachable via the CLI's `fetch <url>` command. |
| Skill research agent | `src/agents/skills/research.py` | `SkillResearchAgent.draft_skill(topic)` produces a real `ModificationProposal` via `CognitionRouter` -- honestly minimal without a real LLM provider registered, but the pipeline works end to end. |
| Live deployment | `src/orchestrator/deployment.py` | `DeploymentManager`: stage a candidate ("B") for a Router slot alongside the active version ("A"), trial both against cloned buses, `promote`/`rollback` hot-swaps the Router's live registration, `purge_retired` drops old versions once confident. Every step logged as `MemoryStore` lineage. |
| Consolidation ("sleep") | `src/orchestrator/consolidation.py` | `run_consolidation()`: one explicit maintenance pass -- runs `ReflectionAgent`, then prunes stale records per `MemoryStore` kind via `delete()`. Not a background daemon; always triggered explicitly. |
| Interests & world-awareness | `src/agents/interests.py` | `InterestTracker` persists tracked topics and decides what's overdue for follow-up; `WorldFeed`/`NullWorldFeed` is the (currently no-network) seam for a future real news/RSS integration. |
| CLI loop | `src/main.py` | Dispatches to emotion then logic and synthesizes their output using live mood; records every dispatch via `OutcomeLog`; checks `HealthMonitor` after each turn; records each turn in `ShortTermMemory`. Commands: `reflect` (outcome review), `propose <topic>`/`improve <topic>`/`pending` (draft, audit, and immediately apply a skill; `pending` shows what's been applied), `fetch <url>` (real, reviewed web access), `interest <topic>`/`interests`/`curious` (world-awareness), `sleep` (maintenance), `history` (this session's recent turns), `run <code>` (execute sandboxed Python via the skills agent), `budget` (spend status per active provider). `propose`/`fetch` narrate their steps as they run, not just the final result. A leading `/` is optional on any command. Prints which cognition provider(s) are active (Claude Code CLI, Gemini, both, or neither) at startup. |

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
          printed + dropped   apply_proposal()  [independent src/agents/skills/-only
                                 │                scope check + path-traversal guard]
                                 ▼
                    written to disk + MemoryStore(kind="applied_skill")
                                 │
                                 ▼
              ordinary uncommitted git change -- creator reviews via
              git diff/status and decides whether to commit; 'pending'
              lists what's been applied this way
```

`requires_human_approval` is `False` under current, creator-authorized
policy -- there is no separate approval step. This is unchanged from
`AuditGate`'s own checks (denylist, adaptive immunity, sandbox), and the
protected-subject list (`soul.py`/`SOUL.md`/`audit.py`) is unaffected --
see `docs/SOUL.md`, "Self-Improvement Philosophy."

## Not yet implemented

- A distributed `SharedMemoryBus` backend and a `Node`
  registration/heartbeat abstraction for multi-host sub-agent placement
  (deliberately not built until there's real infrastructure to target).
- A real `WorldFeed` implementation (RSS/API-backed) -- `curious` always
  reports no updates today, honestly, since only `NullWorldFeed` exists.
- `SkillResearchAgent` only ever asks the LLM for a short descriptive
  note about the topic, wrapped in a template -- not for actual working
  code. A real provider now produces real prose, but drafted skills still
  aren't functional beyond returning that text.
- Any command to view a previously applied proposal's full code (`pending`
  shows the file path and rationale, not the code itself) -- `git diff`/
  reading the file directly are the current way to review one.
