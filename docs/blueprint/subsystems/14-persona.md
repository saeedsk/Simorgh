# 14 — Persona (`simorgh/persona/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). A spec may refine those documents; it
> may not contradict them. If you find a contradiction, fix the governing
> document and note it in `00-README.md`'s changelog.

**Layer:** 4 Self & surfaces
**Owner (build):** unassigned
**Status:** draft
**Depends on (contracts only):** `percept.text.received`, `task.completed`, `task.failed`, `curiosity.share.proposed`, `reflect.health.finding`, `system.tick.second`, `system.state.changed`, `persona.voice` (request), `ui.prompt.answered`
**v1 code that migrates here:** `src/orchestrator/persona_state.py`, `src/agents/emotion/base.py`, `src/orchestrator/socializing.py` (`GrowthSocializer`, `NewsSocializer`), `src/memory/shared_bus.py` (retired; its role becomes `persona.state.changed`), `src/agents/logic/base.py` (`mood_phrase`, `_IDENTITY_PREFIX`), `docs/SOUL.md` Identity/Personality sections (read-only source)

## 1. Purpose and responsibilities

Persona is *who* Simorgh is while every other subsystem is *what it can
do*. It owns the system's identity text, its continuous emotional state,
the voice it speaks in, its working model of the person it talks to, and
the etiquette of speaking up unprompted. It is the subsystem the creator
was asking for when they asked for "personality" — a first-class,
durable, measurable part of the system rather than a prompt prefix, and
one whose mood is a genuine, clamped, decaying dynamical system
(`AGI-04` §7 notes health monitoring of exactly this state as a
self-monitoring concern; the monitoring itself lives in Reflection).

**Responsibilities (owns):**
- The identity and personality text (loaded from `docs/SOUL.md`, never written).
- The `EmotionalState` vector (valence, arousal, cognitive load) — the single writer; publishes `persona.state.changed`.
- The rule-based emotion reaction to inputs (lexicon scoring → mood deltas) — the guaranteed floor, no LLM.
- The `persona.voice` request/reply: a style block and a natural-language `mood_phrase` for Cognition's prompt assembly.
- The user model (theory of mind): preferences, expertise, conventions, current focus, confidence-weighted, durable.
- Proactive sharing *execution*: pacing, etiquette, and rendering of `curiosity.share.proposed` into `ui.notice`.
- Applying a health reset requested by Reflection.
- Publishing the persona gauges the vitals panel shows.

**Explicit non-responsibilities (belongs elsewhere):**
- Deciding *what* is worth sharing (Curiosity). Persona decides *whether now* and *how*.
- Detecting mood pathology — oscillation, pinned extremes (Reflection `HealthMonitor`). Persona only applies the reset it is asked for.
- Composing the full prompt (Cognition). Persona supplies one block.
- Rendering to a terminal (Interface).
- Any action with a side effect (Execution, via Guardian).

**Principles this subsystem is the primary enforcer of** (from `01` §4): 4.5 guaranteed floor (the lexicon reaction and a neutral voice always work); 4.12 transparent, file-based self-knowledge (identity is `SOUL.md`, the user model is a readable projection).

## 2. Position in the architecture

Layer 4. Persona participates in Flow 1 (a turn: reacts to the percept, nudges mood, later contributes voice), Flow 2 (task outcomes nudge mood; completion may trigger a growth share), Flow 8 (sleep tick: decay), and the vitals projection. **Persona is never in the call path of the harness loop.** Orchestration's context assembly *requests* `persona.voice` with a short timeout and proceeds with a neutral block on timeout; the loop is unchanged whether or not Persona is running. It imports only `simorgh.contracts`, the Bus/Ledger clients, and stdlib.

## 3. Interfaces

### 3.1 Messages consumed
| Type | Pattern | Semantics | What this subsystem does with it |
|---|---|---|---|
| `percept.text.received` | event | Score the text with the lexicons; apply deltas; emit `persona.state.changed`; update user model facets from explicit statements ("I prefer…", "call me…") |
| `task.completed` / `task.failed` | event | Small valence/arousal nudges (+ on success, − on failure), cognitive-load bump on `task.started` is optional (config); record outcome feedback into the user model when the task was human-originated |
| `curiosity.share.proposed` | command (group `persona`) | Apply pacing/etiquette; either emit `ui.notice` and record `shared`, or defer/decline and record why |
| `reflect.health.finding` | event | If `severity=critical` with `action_taken=request_reset`, reset state to baseline and emit `persona.state.changed(source="reflection.reset")` |
| `system.tick.second` | event | Every `decay_interval_s`: `decay_toward_baseline`; every `save_interval_s`: snapshot |
| `system.state.changed` | event | On `paused`/`stopping`: suppress proactive shares; on `running`: resume |
| `persona.voice` | request | Reply with style block + mood phrase (see 3.3) |
| `ui.prompt.answered` | event | If the prompt was Persona's (a "may I share…" etiquette question), update etiquette preferences in the user model |

### 3.2 Messages produced
| Type | Semantics | Payload summary | Consumers (informational) |
|---|---|---|---|
| `persona.state.changed` | event | `{valence, arousal, cognitive_load, source, previous:{…}, labels:{valence, arousal}}` | reflection (health), interface (vitals), memory (episodic context), cognition (optional) |
| `persona.voice.reply` | reply | `{style_block, mood_phrase, register: casual|neutral|formal, version}` | orchestration/cognition |
| `persona.user_model.updated` | event | `{facet, value, confidence, source_ref, previous?}` | interface (register), curiosity (relevance), memory |
| `ui.notice` | event | `{level: info, text, source: "persona", kind: growth|news}` | interface |
| `ui.prompt` | event | Rare: etiquette question ("Want me to keep sharing news while you work?") | interface |
| `system.metrics` | event | gauges: valence, arousal, cognitive_load, shares_24h, user_model_facets | kernel/interface |

### 3.3 Request/reply APIs served
**`persona.voice` → `persona.voice.reply`.** Request payload `{context: chat|notice|report, audience?: user_id, max_chars?: int}`. Reply within 50 ms (pure in-memory); Orchestration uses `timeout=0.25s`. Failure reply: `{ok: false, error: {code: "unavailable", retryable: true}}` — the requester substitutes the neutral block. The reply is deterministic for a given state and user model version, so it is cacheable per turn.

### 3.4 Python protocol (`api.py`)
```python
@dataclass(frozen=True)
class EmotionalState:            # ported from v1; timestamp now comes from ctx.clock
    valence: float = 0.0          # [-1, 1]
    arousal: float = 0.0          # [-1, 1]
    cognitive_load: float = 0.0   # [0, 1]
    ts: float = 0.0
    @property
    def valence_label(self) -> Literal["negative", "neutral", "positive"]: ...
    @property
    def arousal_label(self) -> Literal["low", "moderate", "high"]: ...

class MoodEngine(Protocol):
    def current(self) -> EmotionalState
    def apply_delta(self, *, valence: float = 0, arousal: float = 0, cognitive_load: float = 0, source: str) -> tuple[EmotionalState, EmotionalState]
    def set_state(self, *, valence=None, arousal=None, cognitive_load=None, source: str) -> tuple[EmotionalState, EmotionalState]
    def decay_toward_baseline(self, elapsed_s: float) -> EmotionalState
    def history(self, n: int = 200) -> list[EmotionalState]

class EmotionReactor(Protocol):   # the rule-based floor
    def react(self, text: str) -> MoodDelta                # MoodDelta(valence, arousal, reaction_phrase)

class VoiceComposer(Protocol):
    def compose(self, state: EmotionalState, user: UserModel, context: str) -> Voice   # Voice(style_block, mood_phrase, register)

class UserModel(Protocol):
    def facets(self) -> dict[str, Facet]                  # Facet(value, confidence, updated_at, source_ref)
    def observe(self, facet: str, value: Any, confidence: float, source_ref: str) -> Facet | None
    def register(self) -> Literal["casual", "neutral", "formal"]

class SharePolicy(Protocol):
    def decide(self, proposal: ShareProposal, now: float) -> ShareDecision   # ShareDecision(share: bool, reason, defer_until?)
```

### 3.5 Configuration
`simorgh.toml [persona]`

| Key | Type | Default | Controls |
|---|---|---|---|
| `soul_path` | path | `docs/SOUL.md` | Identity/personality source (read-only) |
| `baseline.valence` / `.arousal` / `.load` | float | 0.0 / 0.0 / 0.0 | Decay target |
| `decay_half_life_s` | float | 900 | Exponential decay toward baseline |
| `decay_interval_s` | float | 5 | How often decay is applied |
| `history_limit` | int | 200 | Bounded in-memory history (Reflection reads it via events, not this) |
| `lexicon_weight` | float | 0.15 | Per-word delta (v1 value) |
| `exclamation_arousal` | float | 0.10 | v1 value |
| `outcome_nudge.success` / `.failure` | float | +0.08 / −0.10 | Valence nudge per task outcome |
| `share.growth_cooldown_s` | float | 900 | v1 `DEFAULT_SHARE_COOLDOWN_SECONDS` (growth) |
| `share.news_cooldown_s` | float | 1800 | v1 (news) |
| `share.quiet_when_active_s` | float | 20 | Don't share within this many seconds of user input |
| `share.max_per_hour` | int | 4 | Hard cap across kinds |
| `user_model.min_confidence_to_use` | float | 0.5 | Below this a facet is stored but not applied |
| `voice.max_chars` | int | 600 | Cap on the style block |
| Env override: `SIMORGH_PERSONA_SOUL_PATH` | | | |

## 4. Data model and Ledger streams

| Stream | Events | Payload | Projection |
|---|---|---|---|
| `persona:state` | `state.changed` | `{valence, arousal, cognitive_load, source, previous}` | current state + bounded history; snapshot every `save_interval_s` (default 60 s) with `at_seq` |
| `persona:user_model` | `facet.observed`, `facet.retracted` | `{facet, value, confidence, source_ref}` | `UserModelProjection`: last-write-wins per facet with confidence merged as `max(old·0.9, new)` — repeated observation raises confidence, contradiction lowers it (a `retracted` or a lower-confidence conflicting value halves the prior) |
| `persona:shares` | `share.decided` | `{kind, decision, reason, content_ref}` | pacing counters (last share per kind, shares per hour) |
| `persona:identity` | `identity.loaded` | `{soul_sha256, sections: [...]}` | proves which SOUL version was in force |

Facet vocabulary (extensible, string keys): `name`, `pronouns`, `register`, `expertise.<domain>`, `prefers.terse`, `prefers.commit_often`, `convention.<repo>.<rule>`, `focus.current`, `timezone`, `share.news_ok`, `share.growth_ok`. Values are JSON scalars/lists. The data directory holds `persona/USER.md`, a human-readable projection regenerated on each update (principle 4.12).

Not in the Ledger: the in-memory state cache and history (rebuilt from `persona:state`).

## 5. Internal design

```
service.py
 ├─ MoodEngine (mood.py)        clamp, history ring, decay: v = b + (v-b)·2^(-Δt/half_life)
 ├─ EmotionReactor (lexicon.py) ported word sets + reaction table; pure function of text
 ├─ VoiceComposer (voice.py)    identity condensed block + mood_phrase(state) + register from UserModel
 ├─ UserModel (user_model.py)   projection over persona:user_model; explicit-statement extractor (regex, floor)
 ├─ SharePolicy (sharing.py)    cooldowns, quiet window, hourly cap, pause suppression; wraps v1 socializers' pacing
 └─ Health (reset handling)     apply reflection-requested reset
```

Concurrency: a single asyncio task per handler class; `MoodEngine` guarded by an `asyncio.Lock` (v1's `RLock` becomes unnecessary — one event loop). A background decay task ticks on `system.tick.second`. `stop()` snapshots `persona:state` and cancels tasks.

State machine for a share proposal:
```
proposed ─(paused|stopping)──────────────▶ declined(paused)
proposed ─(user active < quiet_when_active_s)▶ deferred(until quiet)  ─▶ re-evaluated on next tick
proposed ─(cooldown for kind not elapsed)──▶ deferred(until cooldown)
proposed ─(hourly cap reached)────────────▶ declined(cap)
proposed ─(user facet share.<kind>_ok == false, conf ≥ min)▶ declined(preference)
proposed ─(else)──────────────────────────▶ shared → ui.notice + share.decided
```

mood_phrase (ported): maps valence/arousal quadrants to short natural phrases ("calm, nothing much going on", "energized and upbeat", "a bit down but steady", …) — never enum names.

Voice style block: ≤ `voice.max_chars`, composed of (1) two-line identity from SOUL (name, stance), (2) the mood phrase as tone guidance, (3) register hints from the user model (terse/verbose, formal/casual, name to use), (4) one line of etiquette ("say when you're unsure; don't pad"). Deterministic; no LLM.

## 6. Key behaviors — worked scenarios

**S1 — A cheerful message (Flow 1).** `percept.text.received{text:"Thanks, that fix was awesome!"}` → reactor scores `+0.30` valence (`thanks`, `awesome`), `+0.10` arousal (`!`) → `MoodEngine.apply_delta` → `persona.state.changed{valence:0.30, arousal:0.10, source:"emotion"}` → Reflection/Interface consume. Orchestration later requests `persona.voice{context:chat}` → reply `{mood_phrase:"upbeat, a little energized", register:"casual", style_block:…}` within 50 ms. Cognition includes the block; the reply reads warmer.

**S2 — Growth share after a completed self-patch (Flow 2 → 4).** `learn.self_patch.applied` reaches Curiosity, which emits `curiosity.share.proposed{kind:growth, content_ref}`. Persona: last growth share 40 min ago (> 900 s), user last typed 3 min ago (> 20 s), 1 share this hour (< 4), facet `share.growth_ok` unknown → `shared`; renders "🌱 Quick self-update: I just patched …" → `ui.notice{kind:growth}`; appends `share.decided{shared}`. Interface prints it as a scrolling block.

**S3 — Reflection requests a reset.** Reflection's `HealthMonitor` sees valence pinned at −1.0 across 6 transitions → `reflect.health.finding{severity:critical, action_taken:"request_reset"}`. Persona `set_state(baseline, source:"reflection.reset")` → `persona.state.changed{…, source:"reflection.reset"}`; the previous state is preserved in the event so the reset is auditable. Interface shows a dim notice.

**S4 — Failure: Persona is down during a turn.** Orchestration's `persona.voice` request times out at 250 ms → substitutes the neutral block (`mood_phrase:"neutral"`, identity from its own copy of SOUL's two identity lines shipped in contracts as a constant). The turn completes normally; Kernel marks Persona `degraded`; on restart Persona rebuilds state from `persona:state` snapshot + tail.

**S5 — Contradictory user statements.** Turn 1: "call me Sam" → `facet.observed{name:"Sam", conf:0.9}`. Turn 9: "actually it's Samuel in reports" → `facet.observed{name:"Samuel", conf:0.8, context:report}`; projection keeps `name=Samuel` (newer) but confidence merges to 0.8 and records both; `persona.user_model.updated{facet:name, previous:"Sam"}`.

## 7. Design considerations and tradeoffs

- **Rule-based emotion, not LLM-scored.** `AGI-03` §6/§8 note social cognition is contested and inconsistent in LLMs; the lexicon is cheap, deterministic, and always available (`01` §4.5). Cost: crude. Mitigation: the user model can be enriched by Reflection's LLM-backed observations later without changing Persona's floor.
- **Persona out of the loop's call path.** `harness-01` "minimal scaffolding, maximal harness": voice is an *input* to prompt assembly with a timeout fallback, so a Persona bug can never stall a task. Cost: voice may be one turn stale under load — acceptable.
- **Exponential decay vs. v1's step decay.** A half-life is clock-independent and testable with `FakeClock`; v1's `decay_toward_baseline` per-call step is kept as the primitive.
- **Sharing etiquette here, share *selection* in Curiosity.** `harness-03` scope boundaries: what-to-say and whether-to-interrupt are different judgments; splitting them lets pacing be tuned without touching discovery. v1 had both in `socializing.py`; the split is the migration change.
- **User model as confidence-weighted facts, not free text.** `AGI-03` §8 theory-of-mind: modeling beliefs that may differ from truth requires *revisable* facts with provenance; a blob of prose can't be retracted. Cost: a fixed facet vocabulary — extensible by string key.
- **No in-place terminal control** for mood display (milestone 94): Persona emits gauges; Interface prints blocks.

## 8. Safety, degradation, and failure modes

- Provider down/budget exhausted: irrelevant — Persona makes no LLM calls.
- Malformed `percept.text.received`: validation fails at publish; a text over 20 KB is truncated for scoring.
- Handler crash: Kernel marks degraded; state cache survives; next event continues.
- Restart mid-operation: rebuild from `persona:state` snapshot + tail; if the stream is empty, baseline.
- Duplicate `curiosity.share.proposed` (same `idempotency_key`): second is a no-op (`share.decided` already appended).
- Ledger unavailable: state changes are kept in memory and replayed when it returns (bounded buffer of 1,000; beyond that, drop oldest and log `system.health` degraded).
- Corrigibility: on `system.pause` all shares are declined; on `system.stop` snapshot and exit. Persona can never emit an action.
- SOUL.md is opened read-only; a hash mismatch against the last `identity.loaded` is announced via `ui.notice` (transparency, Directive 8), never blocked.

## 9. Testing strategy

- Contract tests: `persona.state.changed`, `persona.voice.reply`, `persona.user_model.updated`, `ui.notice` validate and round-trip; handlers reject invalid payloads without side effects.
- Unit: clamping at bounds; history ring; decay math at 0, half-life, 3×half-life; lexicon scoring (port v1 tests); reaction table completeness (all 9 quadrants); `mood_phrase` never contains enum names; voice block ≤ max chars and deterministic; user-model merge rules (raise, contradict, retract); share policy state machine (each transition); reset applies baseline and preserves previous.
- Integration: `test_flow_1_persona_voice_in_turn.py` (voice included, and turn still completes with Persona stopped); `test_flow_2_growth_share_pacing.py` (two shares within cooldown → one notice); `test_persona_reset_from_reflection.py`.
- Property: for any sequence of deltas, every state field stays within range; rebuild-from-log equals live state.
- Fakes: `FakeClock` drives decay and cooldowns; no network, no LLM.

## 10. Build steps (an agent picks this up here)

1. Skeleton per `05` §4.1; declare consumes/produces; boundary + contracts tests pass. *(S)*
2. `mood.py`: port `PersonaState`/`EmotionalState`; add half-life decay; `persona:state` stream + snapshot; rebuild test. *(S)*
3. `lexicon.py`: port `EmotionAgent` scoring/reactions as a pure reactor; wire `percept.text.received` → `persona.state.changed`; port tests. *(S)*
4. `voice.py`: port `mood_phrase`, condensed identity; `persona.voice` handler with 50 ms budget; determinism test. *(S)*
5. `user_model.py`: projection, explicit-statement extractor, `USER.md` writer; merge tests. *(M)*
6. `sharing.py`: policy state machine; consume `curiosity.share.proposed`; `persona:shares`; pacing tests with `FakeClock`. *(S)*
7. Health reset handling; outcome nudges; `system.metrics` gauges. *(S)*
8. Failure modes (§8) tests; integration scenarios; README build log; `EVOLUTION.md` milestone. *(S)*

Parallelizable: steps 3, 4, 5, 6 after step 2. Total size: **M**.

## 11. Migration notes

- `PersonaState` → `MoodEngine` (lock simplified; timestamps from `ctx.clock`). v1 tests move to `tests/simorgh/persona/test_mood.py`; `src/orchestrator/persona_state.py` becomes an adapter re-exporting the dataclass.
- `EmotionAgent.handle(request, bus)` → `EmotionReactor.react(text)` + handler; the `SubAgent` shape is retired with `router.py`.
- `SharedMemoryBus` retired: readers subscribe to `persona.state.changed`; the v1 adapter wraps a Persona client so `bus.read()` still works during migration.
- `GrowthSocializer`/`NewsSocializer` split: cooldown/pacing → `SharePolicy`; content selection → Curiosity (`13-curiosity.md`).
- `mood_phrase`, `_IDENTITY_PREFIX` → `voice.py`; `LogicAgent` no longer builds persona text itself.

## 12. Open questions

1. Should cognitive load be driven by Orchestration's step count rather than lexicon? **Default:** yes — Orchestration publishes `task.step`; Persona bumps load by `0.02/step`, decays with the same half-life.
2. Should the user model be per-user on the API surface? **Default:** keyed by `user_id` when present, `"local"` otherwise.
3. Should Persona ever ask the etiquette `ui.prompt`? **Default:** once, after the third share in a session, then respect the answer as a facet.
