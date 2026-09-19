# cognition -- contract

One-line status: layer 2 · 3,135 lines · 14 test files · lock: `cognition` in docs/modules/locks.toml

## Purpose

Cognition is the only path to a language model: it answers `cognition.think` (and `cognition.compact.request`) by assembling protected prompt blocks (constitution, persona voice, self summary, user profile, task rules), compacting the caller's messages to the purpose's input budget, routing the call through an ordered list of providers with per-provider rolling budgets and failover, and parsing the reply for tool markers, edit blocks and verdicts. It owns the providers (Together, Claude Code CLI, Gemini, Ollama, and the offline floor), the spend accounting per provider, and the marker parser; it does not decide what tools exist, which purpose a caller should use, or what to do with an answer. It must never answer from a provider over its budget, never truncate a protected block to fit (a `context_too_large` error instead), and never go silent on failover (`ui.notice` when the answering provider changes). The shaping decision: a purpose-keyed router with a floor that always answers, so a missing key or exhausted budget degrades to an honest template instead of an exception. Today it sends no native tool definitions to any provider (`tools=None`, `service.py:370`) and flattens the transcript into one user message (L1, L2).

## Files

| File | For |
|---|---|
| `simorgh/cognition/__init__.py` | exports `Service` |
| `simorgh/cognition/api.py` | `Purpose`, `Budget`, `BudgetStatus`, prompt/compaction/parse result types, errors |
| `simorgh/cognition/assembler.py` | `PromptAssembler`: protected blocks via `persona.voice`, `self.summary`, `world.env.query` requests |
| `simorgh/cognition/budget.py` | `RollingWindowBudget` per provider on `cognition:budget:<provider>` |
| `simorgh/cognition/compaction.py` | five-layer `Compactor`; layer-5 summaries to `cognition:summaries:<session>` |
| `simorgh/cognition/config.py` | `[cognition]` dataclasses, default providers and purpose budgets |
| `simorgh/cognition/parser.py` | `OutputParser`: tool markers, edit blocks, verdicts, non-answers |
| `simorgh/cognition/providers/__init__.py` | re-exports floor, Claude Code and Gemini providers |
| `simorgh/cognition/providers/base.py` | `FloorProvider`: offline, purpose-specific template, never raises |
| `simorgh/cognition/providers/claude_code.py` | the Claude Code CLI as a provider (subprocess) |
| `simorgh/cognition/providers/gemini.py` | Gemini via lazy `google-genai` |
| `simorgh/cognition/providers/ollama.py` | local Ollama fallback, started on demand; the only vision-capable provider |
| `simorgh/cognition/providers/together.py` | Together (OpenAI-compatible HTTP), cache-aware cost; the primary |
| `simorgh/cognition/router.py` | ordered failover within one call deadline, budgets, cooldowns, floor |
| `simorgh/cognition/service.py` | the `Service`: think/compact handlers, provider status, health |
| `simorgh/cognition/tokens.py` | `estimate_tokens` (chars / 4) |

## Consumes

`Service.consumes` (`service.py:99-102`) is authoritative.

| Topic | Schema | Where | Does |
|---|---|---|---|
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/cognition/service.py:222 | assemble, compact, route, parse; reply `cognition.think.reply` (or an error reply) |
| `cognition.compact.request` | `messages/cognition.py::CognitionCompactRequest` | simorgh/cognition/service.py:223 | compact the given messages to `target_tokens`; reply `cognition.compact.reply` |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/cognition/service.py:224 | `paused`/`stopping` makes new thinks reply `paused` |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/cognition/service.py:225 | every 30th tick, publish provider status and metrics |
| `system.started` | `messages/system.py::SystemStarted` | simorgh/cognition/service.py:231 | re-broadcast each provider's status for layers that booted later |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `cognition.think.reply` | `messages/cognition.py::CognitionThinkReply` | simorgh/cognition/service.py:397, 564 | every think: text, tool_calls, provider, cost, floor, compaction, budget; or `error{code}` (`invalid_request`, `paused`, `context_too_large`, `no_real_provider`, `budget_exceeded`) |
| `cognition.compact.reply` | `messages/cognition.py::CognitionCompactReply` | simorgh/cognition/service.py:442 | every compact request |
| `cognition.compact.pre` | `messages/cognition.py::CognitionCompactPre` | simorgh/cognition/compaction.py:359 | before a layer-5 summary |
| `cognition.compact.done` | `messages/cognition.py::CognitionCompactDone` | simorgh/cognition/compaction.py:375 | after a layer-5 summary |
| `cognition.provider.status` | `messages/cognition.py::CognitionProviderStatus` | simorgh/cognition/service.py:463, 512 | per provider at start, at `system.started`, and every `availability_poll_seconds` (30 s) |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/cognition/service.py:482 | every `availability_poll_seconds` (30 s): calls and spend per provider |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/cognition/service.py:548 | the answering provider changed (not for image calls) |
| `persona.voice` (request) | `messages/persona.py::PersonaVoice` | simorgh/cognition/assembler.py:54 | every think, `assembly_request_timeout` (2 s); omitted on timeout |
| `self.summary` (request) | `messages/self_.py::SelfSummary` | simorgh/cognition/assembler.py:58 | every think, same timeout |
| `world.env.query` (request) | `messages/world.py::WorldEnvQuery` | simorgh/cognition/assembler.py:99 | chat purpose only: the `user_profile` facet |

`Service.produces` lists every row above, the three assembler requests included (fixed 2026-09-19; it used to omit `ui.notice` and the requests).

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `cognition:budget:<provider>` | simorgh/cognition/budget.py:25 (`stream_for`); one event per billed call | read back once at start by the budget itself | `cognition:budget:` 3d, but per-id handling means an active stream is never truncated (ledger/CONTRACT.md) |
| `cognition:calls` | simorgh/cognition/service.py:552; one `think.completed` per think | nothing | forever (no retention entry, no snapshot) |
| `cognition:summaries:<session_id>` | simorgh/cognition/compaction.py:343; layer-5 summaries | nothing | 30d |

## Config

`[cognition]` in simorgh.toml; dataclass in `simorgh/cognition/config.py`. Provider tables are `[cognition.providers.<name>]` (`ProviderConfig`: `max_calls`, `window_seconds`, `max_spend_usd`, `timeout_seconds`, `model`, `price_in/out/cached_in`, `backend`, `reasoning_effort`, `only_purposes`, `base_url`, `keep_alive`, `num_ctx`, `vision_model`); purposes are `[cognition.purposes.<purpose>]` (`Budget`).

| Key | Default | Read in the package |
|---|---|---|
| `provider_order` | `('together', 'claude_code_cli', 'gemini', 'floor')` | yes |
| `providers` | `field(default_factory=lambda: {'together': ProviderConfig(ma` | yes |
| `purposes` | `field(default_factory=lambda: dict(DEFAULT_PURPOSE_BUDGETS))` | partly: `max_tokens_in/out` and `max_cost_usd` are read; `max_seconds` and `require_real` are not (see Known issues) |
| `routes` | `field(default_factory=dict)` | yes |
| `tool_result_max_tokens` | `2000` | yes |
| `snip_trigger_fraction` | `0.9` | yes |
| `snip_target_fraction` | `0.85` | yes |
| `snip_keep_last_segments` | `4` | yes |
| `microcompact_trigger_fraction` | `0.95` | yes |
| `collapse_keep_full_segments` | `4` | yes |
| `collapse_trigger_fraction` | `0.45` | yes |
| `availability_poll_seconds` | `30.0` | yes: the period, in `system.tick.second` ticks (rounded, at least 1), of the `cognition.provider.status` + `system.metrics` broadcast (`Service._on_tick`). Wired 2026-09-19; it was a literal 30 |
| `assembly_request_timeout` | `2.0` | yes |
| `problems` | `()` | yes (not a key: what `from_mapping` ignored, logged at start) |

Environment: `SIMORGH_COGNITION_PROVIDER_ORDER` (the test session sets it to `floor`), `SIMORGH_LLM_DAILY_MAX_CALLS` and `SIMORGH_LLM_DAILY_BUDGET_USD` (both Together and Gemini defaults), `SIMORGH_CLAUDE_CODE_MAX_CALLS`, `TOGETHER_API_KEY` (also via `ctx.secrets`), `GEMINI_API_KEY`/`GOOGLE_API_KEY`.

## Public Python surface

- `simorgh.cognition.Service` (`service.py:96`): `name="cognition"`, `Service(*, config=None, providers=None)`; `providers=[...]` is the test seam that replaces every real provider. Health: `degraded` once only the floor has answered for more than 300 s, counted from the first floor reply.
- Other packages talk to Cognition only over the bus (`cognition.think`, `cognition.compact.request`). Wire types live in `contracts/messages/cognition.py`; `Provider` and `ProviderResponse` in `contracts/protocols.py`.
- Nothing outside the package imports `cognition.api`, `router`, `budget` or the providers (boundary rule); `contracts/tidy.py` is tested in the contracts tier (`tests/simorgh/contracts/test_tidy.py`, moved there 2026-09-19).
- Module-level mutable state: `config.DEFAULT_PURPOSE_BUDGETS` (a dict of frozen `Budget`s; `Config` copies it, so mutation affects only later configs) and `parser._CODE_BEARING_MARKERS` (a set). No singletons hold runtime state.

## Invariants

- Every `cognition.think` gets exactly one `cognition.think.reply`, success or `error{code, detail, retryable}`.
- While the system is `paused` or `stopping`, a think gets `error.code = "paused"` and no provider is called.
- Protected blocks are never compacted; if they alone exceed the input budget, or compaction leaves the context over budget, the reply is `context_too_large` and no provider is called.
- The input ceiling comes from the purpose (`max_tokens_in`), not from the caller's `max_tokens`, unless the caller sets `max_tokens_in`.
- A provider whose rolling window is exhausted (calls or spend) is skipped; one provider's spend never counts against another's cap.
- Candidates are tried in route order (a per-purpose route, or `routes.strong` for `tier: "strong"`) then `provider_order`, all within one call deadline; the floor answers last unless `require_real_provider`, which yields `no_real_provider`.
- A provider with `only_purposes` is never dialled for another purpose; a call with images goes only to a provider that can see.
- Every billed call, including a failed-but-billable one, is recorded on `cognition:budget:<provider>`; the window is read from the ledger once and then kept in memory.
- A change of answering provider between text calls publishes one `ui.notice`.
- A verdict reply with no standalone YES/NO is `non_answer=True`, never a rejection.
- No test may reach a real provider: the session sets `SIMORGH_COGNITION_PROVIDER_ORDER=floor` and providers take injectable transports.
- The context requests made while assembling a prompt (`persona.voice`, `self.summary`, `world.env.query`) carry the think request's `trace_id` (stage 1 item 2).

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract cognition`.

- `tests/simorgh/cognition/test_service.py` -- the Service over a real bus and ledger: think and compact replies, error codes, paused, provider status, notices.
- `tests/simorgh/cognition/test_router.py` -- ordered failover, budgets, cooldowns, one deadline per call, floor and `require_real_provider`.
- `tests/simorgh/cognition/test_routes.py` -- per-purpose routes and the strong tier.
- `tests/simorgh/cognition/test_budget.py` -- rolling-window accounting replayed from the ledger; per-provider isolation.
- `tests/simorgh/cognition/test_budget_reads_its_stream_once.py` -- the budget stream is read once, then kept in memory (C13).
- `tests/simorgh/cognition/test_parser.py` -- markers, code-bearing markers, edit blocks, verdicts, non-answers.
- `tests/simorgh/cognition/test_compaction.py` -- each compaction layer and the pipeline; summaries and their events.
- `tests/simorgh/cognition/test_assembler.py` -- protected block order and graceful omission when persona or self model do not answer.

## Known issues (2026-09-18 evaluation)

- L1 (critical): tool calls are regex-parsed text markers; every provider gets `tools=None` (`service.py:370`). Open; stage 2.
- L2 (critical): the whole transcript is flattened into one user message by the compactor (`compaction.py`) and sent after two system messages (`service.py:341-352`). Open; stage 2 item 5.
- C5 (high): the model sees tool names and hand hints, never a description or schema (`service.py:67-93`). Open; stage 2 item 2.
- C3 (high): the Claude Code CLI failover has no price and no spend cap, so it is invisible to the budget model (`config.py`). Open.
- C11 (low): the floor is an in-band success special-cased outside cognition; the purpose table's `require_real` is dead (the service reads it only from the payload, `service.py:294`). Open.
- C12 (low): the no-real-provider health timer was reset on every floor reply. Fixed 2026-09-18, commit `aa05475`.
- C13 (low): the rolling budget replayed its whole stream on every candidate check. Fixed 2026-09-18, commit `aa05475` (read once, then in memory); the retention half (`cognition:budget:` 3d) was added the same day but does not truncate an active stream.
- L11 (low): orchestration never sends `session_id`, so a layer-5 summary would go to `cognition:summaries:unspecified`. Open (orchestration side).
- V6 (low): every think makes a 2 s-timeout bus round trip to Persona (and to the World Model for self summary and chat profile) in `assembler.py`. Open; stage 4 item 4 replaces them with injected readers.
- B2 (medium): Cognition's `Message.new` sites mint fresh trace ids. Open; stage 1 item 2.

Found while writing this contract (not in the catalogue): `_on_think` builds its `Budget` (`service.py:288-295`) without the purpose's `max_seconds`, so `[cognition.purposes.chat] max_seconds = 90` never applies and every think runs against the 180 s dataclass default (`api.py:96`), although `voice/config.py:213` is tuned to the 90 s value. `cognition:calls` is appended on every think, read by nothing, and never compacted.

## Planned changes (roadmap)

- Stage 1 items 2 and 5: thinks keep the caller's `trace_id`; Cognition shrinks its timeout to the envelope's `deadline`.
- Stage 2 items 2-5, 9, 10: prompt renders each tool's description and argument shape from the ToolSpec; provider capability flags (`supports_tools`, `supports_streaming`, `supports_images`, `context_window`, `cache_prefix`); native tool dialects (Together, Anthropic, Gemini, Ollama) filling `ProviderResponse.tool_calls`, markers only as fallback; typed turns sent as messages (fixes L2); `tool_dialect = "native"` flipped per provider; the marker dialect frozen.
- Stage 3 items 1 and 7: `Provider.stream()` with deltas, `complete()` derived from it; a cheap-tier bridge line before slow turns.
- Stage 4 items 4 and 5: the ContextBuilder in orchestration replaces `assembler.py` (deleted); compaction by token pressure with re-fetchable tool-result stubs.
- Stage 9 item 2: `providers/`, `router.py`, `budget.py`, `tokens.py` move to `simorgh/llm/`.

## Working on this module

Lock it first (`python tools/modlock.py claim cognition --by <you> --task "..."`), commit the lock, edit only `simorgh/cognition/`, `tests/simorgh/cognition/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py cognition` before committing; commit subject `cognition: <what changed>`.

- Telemetry (stage 1 item 4, 2026-09-19): each provider call is a span `cognition.provider_call` (attrs `purpose`, `provider`, `tokens_in`, `tokens_out`), parented to the `cognition.think` message.

- Deadline (stage 1 item 5, 2026-09-19): a think's time cap is shrunk to the request's `deadline` less 0.5 s, but never below the Router's one-candidate minimum (5 s), which would turn a short wait into a floor reply without dialling anyone.

- Capabilities (stage 2 item 3, 2026-09-19): `api.Capabilities(supports_tools, supports_streaming, supports_images, context_window, cache_prefix)` declared as `capabilities` on each provider class and read with `api.capabilities_of(provider)` (undeclared = none; Ollama's `supports_images` property wins). They describe the provider's API, not the adapter: nothing reads them yet; stage 2 item 9's `tool_dialect = "native"` requires `supports_tools`. Floor and the Claude Code CLI wrapper: no tools.

- Native dialects (stage 2 item 4, 2026-09-19): `providers/native.py` maps Sim's tool specs (`{name, description, input_schema}`) to OpenAI `tools` (Together) and Gemini `function_declarations` (SDK automatic calling disabled, so every call still goes through Guardian), and their tool calls back to `ProviderResponse.tool_calls` as `{id, tool, args}` (a call whose arguments are not a JSON object carries `error` instead). Names are encoded for the wire (`skill:greet` -> `skill__greet`) and decoded on the way back. `openai_messages` passes typed tool turns (assistant `tool_calls`, `tool` messages by `tool_call_id`). A reply of tool calls only is not a truncation. Nothing passes `tools` yet: the Service still sends `tools=None` until item 9's `tool_dialect` switch. Verified live 2026-09-19: both APIs returned two parallel calls with Sim's names and arguments.
