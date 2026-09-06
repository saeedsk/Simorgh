# 04 — Cognition (`simorgh/cognition/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md`, `02-system-architecture.md`,
> `03-contracts-and-messaging.md`. This spec refines them; it may not
> contradict them. Contradictions found while writing are listed in §12.

**Layer:** 1 Cognitive core
**Owner (build):** unassigned
**Status:** built (compaction layers 1-2 only; ensemble/CapabilityRegistry and compaction layers 3-5 are Phase 4, per this doc's own scope notes below)
**Depends on (contracts only):** consumes `cognition.think`, `cognition.compact.request`, `system.state.changed`, `system.tick.second`; requests `persona.voice`, `self.summary`
**v1 code that migrates here:** `src/cognition/provider.py`, `budget.py`, `claude_code_provider.py`, `gemini_provider.py`, `tool_protocol.py` (marker/tool-call parsing, `preview`, `ToolCapabilities`, `select_provider`, outcome ledger); prompt blocks `_IDENTITY_PREFIX`, `_CAPABILITY_REFERENCE`, `_TONE_REMINDER`, `_FINAL_TURN_HINT`, `_CONTINUE_HINT` from `src/agents/logic/base.py`; `_PATCH_DRAFT_PROMPT`/`_PATCH_EDIT_PROMPT` shapes and SEARCH/REPLACE parsing from `src/orchestrator/self_patch.py`

## 1. Purpose and responsibilities

Cognition is the system's reasoning engine: the only place a language
model is ever called. Every other subsystem that needs judgment,
drafting, review, planning, or summarization sends a `cognition.think`
request describing *what it wants and how much it may spend*, and gets
back either text, structured tool calls, or an honest `floor: true`
reply saying no real provider answered. Cognition owns the providers,
their budgets and failover, the assembly of the prompt from
persistent/protected blocks plus caller-supplied context, the graduated
context-compaction pipeline that keeps every call inside its token
budget, and the parsing of model output into the tool-call protocol.

**Responsibilities (owns):**
- Provider adapters (`Provider` protocol): Claude Code CLI, Gemini, the deterministic floor; discovery at start; availability polling.
- Routing/failover (`CognitionRouter`), capability negotiation and per-purpose model selection (`CapabilityRegistry`, `select_provider`), ensemble reconciliation for high-stakes purposes.
- Per-provider budget accounting (rolling windows, calls and USD), `cognition.provider.status` events, honest cost reporting.
- Prompt assembly: ordered blocks with *protected* persistent blocks (constitution, persona voice, Self Model summary, task rules) that no compaction layer may drop.
- The five-layer context-compaction pipeline (`harness-01`), token accounting, thresholds, `cognition.compact.pre`/`.done` events.
- Tool-call protocol: marker parsing (`READ:`/`LIST:`/`DRAFT:`/`RUN:` …), `first_line_argument`, `extract_code`, `is_valid_python`, `preview`, SEARCH/REPLACE block parsing, non-answer detection.
- Purposes (`chat`, `draft`, `plan`, `review`, `research`, `decompose`, `reground`, `consolidate`, `ensemble`) with per-purpose budgets.

**Explicit non-responsibilities (belongs elsewhere):**
- Deciding *what* to think about, running loops, retries across attempts → Orchestration, Planning, Learning.
- Enforcing cost *limits* as policy (denying work) → Guardian reads `cognition.provider.status` and denies `action.proposed` on budget pressure; Cognition only accounts and refuses to overspend a single request's stated budget.
- Executing any tool call → Execution (via Guardian). Cognition returns `tool_calls`; it never runs them.
- Persona text, memory retrieval, Self Model content → Persona, Memory, World Model (Cognition *requests* them during assembly).

**Principles this subsystem is the primary enforcer of:** 4.5 (guaranteed floor), 4.6 (context as scarce resource, managed progressively), 4.14 (stdlib core, optional adapters).

## 2. Position in the architecture

Layer 1. Participates in every flow in `02` §5 (1, 2, 3, 4, 6, 8, 9) as
the `⇄ cognition.think` hop. Imports only `simorgh.contracts`,
`simorgh.bus.client`, `simorgh.ledger.client`, stdlib, itself. Provider
adapters that need third-party clients (`google-genai`) guard the import
and register only when importable; the Claude Code adapter shells out to
the `claude` binary and needs no library.

## 3. Interfaces

### 3.1 Messages consumed
| Type | Pattern | Semantics | What this subsystem does with it |
|---|---|---|---|
| `cognition.think` | exact | request | Assemble → compact → route → parse → reply |
| `cognition.compact.request` | exact | request | Run layers 1–5 on a caller-owned message list without a model call (used by Orchestration between steps); reply with the projected view |
| `system.state.changed` | exact | event | On `paused`/`stopping`: abandon in-flight provider calls (results discarded), reject new `think` with `error.code=paused` |
| `system.tick.second` | exact | event | Every 30 s: refresh provider availability, emit `cognition.provider.status` if changed, roll budget windows |
| `system.started` | exact | event | Emit initial `cognition.provider.status` for each provider |

### 3.2 Messages produced
| Type | Semantics | Payload summary | Consumers |
|---|---|---|---|
| `cognition.think.reply` | reply | `{ok, text, tool_calls, provider, cost_usd, tokens{prompt,completion}, floor, compaction{layers_applied, tokens_before, tokens_after}, non_answer: bool}` | requester |
| `cognition.provider.status` | event | `{provider, available, budget{window_seconds, calls, max_calls, spend_usd, max_spend_usd, exhausted}}` | guardian, interface, reflection |
| `cognition.compact.pre` | event | `{session_id, purpose, tokens, layer: 5, reason}` — the `PreCompact` hook | interface, memory (may persist a durable summary), reflection |
| `cognition.compact.done` | event | `{session_id, layers_applied, tokens_before, tokens_after, summary_ref?}` | interface, reflection |
| `cognition.compact.reply` | reply | `{messages, tokens, layers_applied}` | requester |
| `system.health` | event | degraded when no real provider available for > 5 min | kernel |

### 3.3 Request/reply APIs served
- `cognition.think` → `cognition.think.reply`. Timeout expectation: the caller sets bus timeout ≥ `budget.max_seconds` (default 180 s). Failure replies: `ok:false, error:{code: paused|budget_exceeded|invalid_request|timeout, retryable}`. A provider outage is **not** a failure reply: it is `ok:true, floor:true` (principle 4.5) unless `require_real_provider:true`, in which case `ok:false, error.code=no_real_provider, retryable:true`.
- `cognition.compact.request` → `cognition.compact.reply`. Never calls a model unless `allow_summarize:true`.

### 3.4 Python protocol (`api.py`)

```python
class Provider(Protocol):                       # declared in contracts.protocols; restated here
    name: str
    capabilities: frozenset[Capability]         # TOOL_USE, LONG_CONTEXT, STREAMING, ...
    context_window: int | None
    cost_tier: CostTier | None
    def available(self) -> bool: ...
    async def complete(self, messages: list[dict], *, tools: list[dict] | None,
                       max_tokens: int, timeout: float) -> ProviderResponse: ...

@dataclass(frozen=True)
class ProviderResponse:
    text: str; provider: str
    input_tokens: int; output_tokens: int
    cost_usd: float | None                      # provider-reported when available (Claude Code CLI total_cost_usd)
    raw: dict = field(default_factory=dict)

class Budget(Protocol):                         # per provider, rolling window; durable via ledger stream cognition:budget:<provider>
    def can_spend(self, est_cost_usd: float) -> bool
    def record(self, response: ProviderResponse) -> None
    def status(self) -> BudgetStatus

class Router:                                   # failover + selection
    def select(self, purpose: Purpose, *, require_real: bool, min_context: int | None) -> list[Provider]  # ordered candidates
    async def complete(self, purpose, messages, tools, budget) -> ProviderResponse | FloorResponse

class PromptAssembler:
    async def assemble(self, req: ThinkRequest) -> AssembledContext        # blocks with protection flags + token counts

class Compactor:                                 # the five layers
    async def compact(self, ctx: AssembledContext, *, limit_tokens: int, allow_summarize: bool) -> CompactedContext

class OutputParser:
    def parse(self, text: str, expected: OutputSpec) -> ParsedOutput      # tool_calls | final | non_answer | edit_blocks
```

`Purpose` is an `enum.StrEnum`: `chat, draft, plan, review, research, decompose, reground, consolidate, ensemble`.

### 3.5 Configuration (`simorgh.toml [cognition]`)

| Key | Type | Default | Controls |
|---|---|---|---|
| `providers.order` | list[str] | `["claude_code_cli","gemini","floor"]` | Failover priority |
| `providers.claude_code_cli.max_calls` / `.window_seconds` | int / float | 500 / 18000 | Rolling call cap (env `SIMORGH_CLAUDE_CODE_MAX_CALLS`) |
| `providers.gemini.max_calls` / `.max_spend_usd` / `.window_seconds` | int/float/float | 1500 / 2.0 / 86400 | Rolling caps (env `SIMORGH_LLM_DAILY_MAX_CALLS`, `SIMORGH_LLM_DAILY_BUDGET_USD`) |
| `providers.gemini.model` / `.price_in` / `.price_out` | str/float/float | `gemini-3.8-flash` / 0.75 / 3.75 | Model and $/1M tokens for estimates |
| `providers.claude_code_cli.timeout_seconds` | float | 180 | Subprocess timeout |
| `purposes.<p>.max_tokens_in` / `.max_tokens_out` / `.max_cost_usd` | int/int/float | chat 12k/1k/0.05; draft 40k/8k/0.5; plan 24k/2k/0.2; review 12k/1k/0.05; research 24k/2k/0.2; decompose 16k/1k/0.1; reground 8k/512/0.02; consolidate 16k/2k/0.1; ensemble 24k/2k/0.5 | Per-purpose budgets |
| `purposes.<p>.require_real` | bool | review/plan/reground: false; ensemble: true | Whether floor is acceptable |
| `compaction.thresholds` | table | L1 at 100% of `max_tokens_in` per tool result cap (`tool_result_max_tokens`=2000), L2 at 90%, L3 at 95%, L4 always, L5 at 100% | When each layer engages |
| `compaction.protected_blocks` | list[str] | `["constitution","voice","self_summary","task_rules"]` | Never compacted |
| `ensemble.min_providers` | int | 2 | Ensemble requires ≥2 real providers else degrades to single |
| `availability.poll_seconds` | float | 30 | Provider polling |

## 4. Data model and Ledger streams

| Stream | Events | Purpose |
|---|---|---|
| `cognition:budget:<provider>` | `spend.recorded {ts, calls:1, cost_usd, tokens}`; snapshot every 100 events | Durable rolling-window accounting (v1 `llm_spend` records migrate here) |
| `cognition:calls` | `think.completed {session_id, purpose, provider, tokens, cost_usd, floor, compaction, latency_ms, non_answer}` | Telemetry for Reflection calibration and Learning's provider leaderboard |
| `cognition:outcomes:<purpose>` | `outcome.recorded {provider, success}` | Port of v1 `OutcomeStore`/marker ledger; drives `best_for_task` |
| `cognition:summaries:<session_id>` | `summary.created {covers_seq_range, text_ref}` | Layer-5 summaries are durable; the collapsed view (layer 4) is *not* stored — it is a projection |

Blobs: prompts and responses above 8 KB are stored as `blobs/<sha256>`
and referenced by `*_ref`. Projections: `BudgetStatus` per provider
(rebuilt by replaying the window), provider leaderboard per purpose.
Non-ledger state: provider availability cache (30 s TTL), per-session
compaction cache keyed by `(session_id, last_seq)`.

## 5. Internal design

```
cognition/
  service.py        Service: handlers, lifecycle, availability loop
  api.py            protocols above
  config.py
  providers/
    base.py         FloorProvider (deterministic templates by purpose)
    claude_code.py  subprocess `claude -p --output-format json --disallowedTools "*"` (NEVER --bare)
    gemini.py       lazy `google.genai` import; absent if missing
  budget.py         RollingWindowBudget over ledger stream
  router.py         Router + CapabilityRegistry (best_for, best_with_context_window, best_within_cost, leaderboard, complete_ensemble)
  assembler.py      PromptAssembler: block ordering + protection + token estimate
  compaction.py     Compactor: layers 1–5
  parser.py         OutputParser: markers, edit blocks, non-answer
  tokens.py         stdlib token estimator (chars/4 with per-block calibration table; provider-reported counts override after the call)
```

**Request state machine (per `cognition.think`):**

```
RECEIVED ─validate─▶ ASSEMBLING ─(persona.voice, self.summary req/rep, 2 s timeout each; missing block = omitted, logged)─▶
COMPACTING ─layers 1..4 (5 only if still over limit and allow_summarize)─▶ ROUTING ─select candidates─▶
CALLING ─provider.complete (timeout)─┬─ok─▶ PARSING ─▶ REPLIED
                                      ├─ProviderUnavailable/timeout─▶ next candidate … ─none left─▶ FLOOR (require_real? → ERROR)
                                      └─system paused mid-call─▶ ABANDONED (result discarded, reply error.code=paused)
```

**Ensemble (`purpose=ensemble` or `ensemble:true` on any purpose):** call
every available real provider that supports the purpose's capability
concurrently (`asyncio.gather`, each within its own budget); if all texts
agree (normalized equality or, for structured outputs, identical parsed
tool calls) return that; otherwise pick the provider with the highest
leaderboard confidence for the purpose and return `agreement:false` with
all responses attached as blob refs so the caller may escalate. Falls
back to a single call when fewer than `ensemble.min_providers` are
available (v1 `complete_ensemble` semantics preserved).

**Prompt assembly order** (each block tagged `protected` or `elastic`,
with a token estimate):

1. `constitution` (protected) — the directive list from `docs/SOUL.md` §Core Directives, loaded at start, hashed; identical every call.
2. `voice` (protected) — `persona.voice.reply.style_block` + mood phrase (the v1 `_IDENTITY_PREFIX`/`_TONE_REMINDER`, now owned by Persona).
3. `self_summary` (protected) — `self.summary.reply.text` at the purpose's budget (chat 300 tokens, draft 600, plan 800).
4. `task_rules` (protected) — caller-supplied rules for this purpose (scope, format, `_CAPABILITY_REFERENCE`-style tool descriptions for the tools the caller passed).
5. `memory` (elastic) — caller-supplied retrieved items (Cognition does not call Memory itself; Orchestration does, so retrieval policy stays with the caller).
6. `conversation` (elastic) — the caller's `messages`.
7. `tool_results` (elastic, layer-1 target) — tool outputs in the conversation.
8. `final_turn_hint` (protected, only when caller sets `last_step:true`) — the v1 `_FINAL_TURN_HINT`.

**Compaction pipeline** (run before every model call; each layer emits
its effect into `compaction.layers_applied`):

| Layer | Trigger | Action | Emits |
|---|---|---|---|
| 1 Budget reduction | any tool result > `tool_result_max_tokens` | Replace body with `[tool result <name> — <n> tokens, ref: blobs/<sha>] <first 20 lines>`; exempt tools flagged `load_bearing` (e.g. test-suite output tail) | `tokens_freed` |
| 2 Snip | total > 90% of purpose `max_tokens_in` | Drop whole oldest conversation *segments* (a segment = one user/assistant/tool exchange) until under 85%, never touching the last 4 segments | `segments_removed` |
| 3 Microcompact | total > 95% | Collapse repeated identical tool results to one reference; strip whitespace runs; shorten `preview()`ed lines | `tokens_freed` |
| 4 Read-time collapse | always | Build the model-facing view from the *stored* messages without mutating them: older segments rendered as one-line headlines (`[step 3: read src/x.py — 210 lines]`), newest in full. The caller's message list is never modified; the reply reports what was shown | `collapsed_segments` |
| 5 Auto-compact | still > 100% and `allow_summarize` | Emit `cognition.compact.pre`; one model call (purpose `consolidate`, dedicated compact prompt: "preserve requests, decisions, file paths, open questions; drop chatter"); replace collapsed segments with the summary; append `summary.created` to `cognition:summaries:<session>`; emit `cognition.compact.done` | `summary_ref` |

If after layer 5 the context still exceeds the limit (a single
oversized protected block), reply `ok:false, error.code=context_too_large`
rather than silently truncating a protected block — protected means
protected (principle 4.6).

**Output parsing** (`parser.py`): the caller passes `expected`:
`{kind: final|markers|edit_blocks|verdict|json, markers?: ["READ","LIST","DRAFT","RUN"]}`.
Rules ported from v1: a marker must start the stripped text; its
argument is the first non-empty line for single-token markers
(`first_line_argument`); `DRAFT`/`RUN` keep the full payload;
`extract_code` strips fences; `is_valid_python` via `ast`; SEARCH/REPLACE
blocks via the conflict-marker regex (`<<<<<<< SEARCH … ======= … >>>>>>> REPLACE`)
with strict exact-match application performed by the caller (Learning);
a `verdict` scans every line for a standalone YES/NO and reports
`non_answer:true` when none is found — never a rejection (harness-04).

**Concurrency:** one asyncio task per request; provider calls run in
`asyncio.to_thread` (subprocess/HTTP); a semaphore per provider bounds
parallel calls (default 4); budgets are updated under an async lock.
`start()` loads config, discovers providers, replays budget streams,
subscribes; `stop()` cancels the availability loop and drains in-flight
calls with a 5 s grace; `health()` is `ok` if any real provider is
available, `degraded` if only the floor is.

## 6. Key behaviors — worked scenarios

**S1 — Chat turn with a tool call (Flow 1).** Orchestration sends
`cognition.think {purpose:"chat", messages:[…6 turns…], tools:["read_file","list_dir"], budget:{max_tokens:1000,max_cost_usd:0.05}, expected:{kind:"markers", markers:["READ","LIST"]}}`.
Cognition requests `persona.voice {context:"chat"}` (reply in 8 ms) and
`self.summary {budget_tokens:300}`; assembles 5,800 tokens (under 12 k;
layers 1–3 no-op, layer 4 collapses turns 1–2 to headlines); Router
selects `claude_code_cli` (available, 212/500 calls); provider replies
`"READ: src/orchestrator/tasks.py\nLet me check…"` in 4.1 s at
$0.012; parser yields `tool_calls:[{tool:"read_file", args:{path:"src/orchestrator/tasks.py"}}]`
(rambling after the marker discarded); reply `{ok:true, tool_calls:…,
provider:"claude_code_cli", cost_usd:0.012, floor:false, compaction:{layers_applied:[4]}}`;
`cognition:calls` and `cognition:budget:claude_code_cli` appended.

**S2 — Self-patch draft for a large file with compaction (Flow 4).**
Learning sends `purpose:"draft"`, a 32 k-token message list including
three prior `DRAFT` quick-check results (each 6 k tokens) and
`expected:{kind:"edit_blocks"}`. Layer 1 replaces each quick-check
result over 2 k tokens with a reference + 20-line preview (−15 k);
layer 2 not needed (now 17 k < 36 k); layer 4 headlines the two oldest
READ segments. Provider `gemini` (Claude Code exhausted at 500/500 →
`provider.status{exhausted:true}` was emitted an hour earlier) returns
two SEARCH/REPLACE blocks; parser validates the block shape only;
reply carries `edit_blocks:[…]`. Learning applies them strictly
(unchanged v1 `_apply_search_replace_blocks`) and proceeds to
`verify.requested`.

**S3 — Degradation: both real providers exhausted, review purpose.**
Verification sends `purpose:"review", require_real_provider:false`.
Router finds `claude_code_cli` exhausted and `gemini` at
`$2.00/$2.00`; the floor provider answers with its fixed template
`"[floor] no real reviewer available"`; reply `{ok:true, text:…,
floor:true, provider:"floor", cost_usd:0}`. Verification, by its own
contract, treats `floor:true` as `insufficient_evidence` and defers to
mechanical gates. Ten seconds later Curiosity sends `purpose:"draft",
require_real_provider:true` → `{ok:false, error:{code:"no_real_provider",
retryable:true}}`; Curiosity skips the tick. A `system.health
{status:degraded, detail:"no real provider for 5m"}` fires once.

**S4 — Pause mid-call (Flow 5).** A 40 s draft call is in flight when
`system.state.changed{paused}` arrives. The request task is cancelled;
the subprocess is terminated; the reply is `{ok:false,
error:{code:"paused", retryable:true}}`; no budget is charged unless the
provider already reported cost (Claude Code CLI reports only on
completion, so none). Orchestration checkpoints the task.

## 7. Design considerations and tradeoffs

- **Single entry point vs. direct provider access.** Every model call
  through one `think` request costs one bus hop (< 5 ms in-process) but
  gives one place for budgets, compaction, telemetry, and pause — the
  "minimal loop, maximal harness" principle (`harness-01`, "The core
  loop is deliberately small").
- **Graduated compaction vs. summarize-when-full.** Five layers are
  more code, but `harness-01` §"Context management" and `harness-05` §1
  are explicit that a single summarize step is both too eager and too
  late; layer 4's read-time projection is what keeps a later resume or
  differently-scoped summary from working on already-destroyed data.
  The stored message list is never mutated by Cognition.
- **Protected blocks fail loudly.** `harness-05` §1: persistent
  instructions are configuration, not history. Rather than compact them
  we return `context_too_large`; the caller must reduce elastic content.
- **Honest floor as a value, not an exception** (`03` §9; v1 doctrine).
  Callers cannot accidentally mistake a template for a real answer
  because `floor:true` is in the schema and `require_real_provider`
  exists for callers that must not proceed on the floor.
- **Budgets account; Guardian enforces.** Splitting accounting (here)
  from policy (Guardian) keeps the safety decision structurally outside
  the reasoning path (`AGI-04` §9) while letting Cognition refuse to
  overspend a *single* request's own stated budget (defense in depth).
- **Ensemble only where it pays.** `harness-02` parallelization/voting:
  worth it for high-stakes purposes (`ensemble`, optionally `review`),
  wasteful for chat; hence per-purpose opt-in and a `min_providers` floor.
- **Token estimation without a tokenizer dependency** (principle 4.14):
  chars/4 with a per-block calibration table updated from
  provider-reported counts after each call; error is bounded by keeping
  a 10% headroom in every threshold.
- **Alternatives rejected:** a per-subsystem model client (loses budgets
  and pause); a third-party tokenizer (dependency in the core);
  mutating history on compaction (breaks replay and `06`'s promise that
  the Ledger is the truth).

## 8. Safety, degradation, and failure modes

| Condition | Behavior |
|---|---|
| Provider down / times out | Next candidate; then floor; `provider.status` event; `health` degraded after 5 min without any real provider |
| Budget exhausted | Provider marked `exhausted` in status; skipped by Router; window rolls automatically (durable, survives restart) |
| Malformed `think` payload | Fails validation at the publisher (03 §9); if it still arrives, `ok:false, error.code=invalid_request` |
| Handler crash | Caught by the Kernel dispatcher; error reply; no budget charge |
| Restart mid-call | In-flight requests are lost; callers time out and retry (their task stream shows no `task.step` for that step); budget streams replay |
| Duplicate request (`idempotency_key`) | Reply is re-served from `cognition:calls` if the completed record exists; otherwise processed once |
| Ledger unavailable | Budget writes buffered in memory up to 100 events, then requests are refused (`error.code=ledger_unavailable`) — better to stop spending than to spend unaccounted |
| `system.pause`/`stop` | New requests refused with `paused`; in-flight abandoned; `stop` waits ≤ 5 s then cancels |
| Prompt injection in tool results | Tool results are rendered inside a fenced, labeled block (`[tool result …]`) and never in a protected block; Guardian, not Cognition, decides actions |

Guaranteed floor: the `FloorProvider` (stdlib, offline) always answers
every purpose with a fixed, clearly-labeled template.

## 9. Testing strategy

- Contract tests: `cognition.think.reply`, `provider.status`, `compact.pre/done` validate; consumed `think` with valid/invalid payloads.
- Unit: `RollingWindowBudget` (window roll, replay from ledger, cost_usd override — port v1 `test_budget.py` incl. "two providers sharing a store have independent budgets"); `Router` failover order and `require_real`; `CapabilityRegistry` (`best_with_context_window`, `cheapest_for`, leaderboard, ensemble agreement/disagreement); `ClaudeCodeProvider` argv (`test_never_passes_bare_flag`, `--disallowedTools "*"`, env stripping, `is_error` → unavailable); `GeminiProvider` absent-client path; `PromptAssembler` block order and protection; each compaction layer in isolation and the full pipeline with threshold crossings; layer 4 never mutates input; `context_too_large` on oversized protected block; `OutputParser` (`first_line_argument` rambling, `extract_code`, `is_valid_python`, SEARCH/REPLACE parse incl. missing-marker, verdict scanning with narration, `non_answer`).
- Integration: `test_flow_1_chat_turn` (with `FakeProvider`), `test_flow_5_pause_abandons_inflight_call`, `test_ensemble_disagreement_returns_all_responses`, `test_floor_reply_when_all_exhausted`.
- Property: for any message list, `compact()` output token estimate ≤ limit or error; protected blocks are byte-identical before/after.
- Mocks: `FakeProvider` (scripted responses, latency, cost), `FakeClock` for windows; never a real provider or network.

## 10. Build steps (an agent picks this up here)

Size: **L**. Parallelizable within: (providers + budget) ∥ (assembler + compaction) ∥ (parser).

1. Skeleton per `05` §4; `consumes/produces` from §3; register in kernel registry; boundary + contracts tests green. *Accept:* `--self-check` boots with cognition loaded.
2. `providers/base.py` FloorProvider + `Provider` conformance test; `tokens.py`. *Accept:* `think` with no real providers returns `floor:true`.
3. `budget.py` over `cognition:budget:*` with replay + snapshots; port `test_budget.py`. *Accept:* window math and durability tests pass.
4. `providers/claude_code.py`, `providers/gemini.py` ported with their tests (subprocess mocked). *Accept:* argv/env tests pass; absent-client path passes.
5. `router.py` + `CapabilityRegistry` ported (`complete_ensemble` included). *Accept:* failover, selection, ensemble tests pass.
6. `assembler.py` with `persona.voice`/`self.summary` requests (fakes) and protected blocks. *Accept:* order/protection tests.
7. `compaction.py` layers 1–4; then layer 5 with `compact.pre/done`. *Accept:* per-layer and pipeline tests; property test.
8. `parser.py` ported from `tool_protocol.py`/`self_patch.py` with all lessons' tests. *Accept:* rambling/non-answer/edit-block tests.
9. `service.py` wiring: `think`, `compact.request`, state/ticks, `provider.status`, `cognition:calls` telemetry. *Accept:* integration scenarios pass.
10. `src/cognition/*` adapters delegating to this package; v1 suite green. README, config table, EVOLUTION milestone.

## 11. Migration notes

- `CognitionRouter.complete(prompt)` → `Router.complete(purpose, messages, …)`; the v1 string-prompt callers are adapted by wrapping the prompt as one user message. `LLMResponse` → `ProviderResponse` + reply payload.
- `BudgetGuard` (a provider wrapper) → `RollingWindowBudget` consulted by the Router; `_recent_records` per-provider filtering lesson preserved by keying streams per provider.
- `ClaudeCodeProvider`/`GeminiProvider`: bodies unchanged; `complete` becomes async via `to_thread`.
- `tool_protocol.parse_marker/first_line_argument/extract_code/is_valid_python/preview` → `parser.py`; `safe_read_file`/`safe_list_dir`/`read_file_for_patch` → Execution (tools); `ToolCapabilities/register_capabilities/get_capabilities/select_provider` → `router.py` capability negotiation; the marker outcome ledger (`record_outcome/failure_rate/rank_by_history`) → `cognition:outcomes:*`.
- `logic/base.py` prompt constants → `assembler.py` block templates; `_IDENTITY_PREFIX`/`_TONE_REMINDER` text moves to Persona (served via `persona.voice`), `_CAPABILITY_REFERENCE` becomes the `task_rules` block generated from the caller's tool list.
- v1 `llm_spend` records → `cognition:budget:<provider>` by `migrate-v1`.
- Behavior change: none intended; new behavior is compaction layers 3–5 and `context_too_large`.

## 12. Open questions

1. **Contract gap:** `03` §4.15 lists no `cognition.compact.pre/done` or `cognition.compact.request`; this spec proposes them (needed for the `PreCompact` hook per `harness-01`). *Default:* add to contracts in Phase 0 review.
2. **Contract gap:** `cognition.think` payload lacks `expected`, `session_id`, `allow_summarize`, `last_step`; reply lacks `compaction`, `non_answer`, `edit_blocks`, `agreement`. *Default:* add as optional fields (non-breaking per `03` §8).
3. Should Cognition call Memory itself for retrieval? *Default:* no — the caller retrieves (keeps retrieval policy with the loop owner, per `02` Flow 1).
4. Token estimator calibration source. *Default:* provider-reported counts update a per-block-type ratio table in `cognition:calls`; start at chars/4.
5. Whether `review` should be ensemble by default once two real providers are common. *Default:* off; Reflection's calibration data decides later (config change, not code).
6. **Two assemblers fetch the same blocks (post-cutover review, 2026-09-06 — `07-post-cutover-review.md` §3.2). Decision: Cognition's `PromptAssembler` is the sole owner of `self.summary` and `persona.voice`.** Today `orchestration/context.py::Assembler` also fetches both and puts them in `messages`; `PromptAssembler` then flattens that whole list into the elastic "conversation" block *and* re-fetches its own protected copies — the text reaches the provider twice per turn, at double the bus round-trips and roughly double the tokens, feeding the `context_too_large` pressure the live trial hit. Orchestration contributes only memory retrieval, `session.messages`, and `user_text` (remove `context.py` lines 28–34). Matches §5 and "Cognition owns the pipeline" literally.
7. **Layer 5 needs an input cap (same review, §3.4d).** `_layer5_auto_compact` joins `older_elastic` into `body` and sends it to `_summarize_for_compaction` unbounded; `Budget.max_tokens_in` is never enforced as input truncation anywhere downstream. One oversized retrieved memory item can make the summarization call itself too large, or leave it unable to shrink enough — the "residual, rarer" `context_too_large` that survived the `allow_summarize` fix. *Default:* truncate/chunk `body` to a documented maximum before the model call (a second layer-1/3-style pass on `older_elastic` when `body` alone exceeds the `consolidate` budget).
