# Stage 2 -- Schemas to the model, then native tool use behind a capability flag

Status: **in progress** (2026-09-19: items 1-4 done; item 2 is the first behaviour change, measured: trial suite 6/7, no regression) · Depends on: stage 0 item 30 (the gate) · Estimated: 3 weeks · Modules touched: contracts, execution, cognition, orchestration, guardian, benchmark

## Outcome

Every provider that supports it receives the tool list as JSON schema and returns typed tool calls; a reply may carry several calls; results return as tool-result turns keyed by id; Guardian reads typed, schema-validated arguments; MCP tools with more than one property are callable. The marker protocol remains only as the fallback dialect for providers without tool support, and the regex police in `session.py` become unreachable on native paths (they stay alive on the fallback). Flipped per model only after native beats markers on BFCL and the trial suite.

## Why

Evaluation L1/C5 (no native tool calling; every adapter drops `tools=`), T2 (the model never sees description or schema; five hand-maintained marker tables), L8 (seven regex police, each a live-caught incident), T9/T10 (error kinds, decorative metadata). This is the single largest cap on reasoning quality and the largest source of accidental complexity. Unlocks: first-try argument accuracy on multi-field tools, N lookups per turn, MCP as the integration standard, a measured BFCL delta per model.

## Before you start

Run BFCL and BFCL-parallel through `simorgh/benchmark` on the live model with markers (3 repeats) and record the score: that is the number to beat. Read `cognition/parser.py`, `cognition/service.py:322-345` (`tools=None` at :358), `cognition/providers/*.py` (`complete(..., tools, ...)` accepted and dropped), `orchestration/tools.py` (`_TOOL_POLICY`, `_MARKER_ARG_KEY`, `_CODE_BEARING_MARKERS`, `to_action_payload`), `orchestration/session.py::_run` and `_propose_and_await`, `execution/service.py:167-171` (`tool.registered` ships `schema_ref=''`), `execution/mcp.py::mcp_single_arg_key`.

## Action items

Done 2026-09-19:
- Baseline (item 0): BFCL-parallel with markers, GLM-5.3-Flash via Together, 20 cases at offset 0: 17, 18 and 18 of 20 (mean 88%), 130-282 s and about $0.04 per run, no floor replies. See `docs/findings/2026-09-19-stage-0-gate.md`.
- Item 1: `tool.registered` carries `input_schema`; WorldModel keeps it with the description.
- Item 3: `cognition.api.Capabilities` on every provider.
- Item 2: one line per offered tool with its description and arguments (CHAT 323 -> 2,340 tokens, PATCH 166 -> 824); trial suite after 6/7.
- Item 4: `cognition/providers/native.py`; Together and Gemini send and parse native tool calls (fixtures, plus one live call each returning two parallel calls). Unused until item 9.

Next, in order, each behind a trial-suite before/after: items 5-6 (typed turns and N calls per turn in `session.py`, native path only), then item 9 (flip VOICE_CHAT on the provider that wins BFCL).

1. **`ToolSpec` on the wire.** *Lock `contracts`, `execution`, `worldmodel`.* (T2)
   - What: `tool.registered` carries `name, description, input_schema, reversibility, read_only, network, cost_class, source, tags`.
   - Files: `contracts/messages/tool.py` (add the optional fields), `execution/service.py::_announce_tool` (serialise `tool.args_schema`), `worldmodel/facets/registry_facets.py::ToolsFacet` (keep the schema), `execution/mcp.py` (pass MCP `inputSchema` through unflattened; keep `mcp_single_arg_key` only for the marker dialect).
   - Acceptance: `tests/simorgh/contracts/test_tool_registered_carries_schema.py`; every registered tool's `input_schema` is a valid JSON schema (`contracts/validation.py`).
2. **The prompt renders name, description and argument shape.** *Lock `cognition`, `orchestration`.* `cognition/service.py::_tool_instruction_block` renders each offered tool as `NAME: <description>. Arguments: <schema summary>` from the ToolSpec instead of upper-cased names and hand hints. Measure prompt tokens before/after; keep under the CHAT budget by short-form rendering (one line per tool). Acceptance: trial suite no regression; the `_MARKER_ARG_KEY` hints are no longer needed for tools with a one-property schema.
3. **Provider capability flags.** *Lock `cognition`.* `ProviderConfig`/`Provider` gain `supports_tools`, `supports_streaming`, `supports_images`, `context_window`, `cache_prefix`; the floor and the Claude Code CLI wrapper report `supports_tools=False`. Acceptance: `tests/simorgh/cognition/test_capabilities.py`.
4. **Native dialects.** *Lock `cognition`.* Together (OpenAI-compatible `tools`/`tool_choice`, `tool_calls` in the response), a direct Anthropic Messages API adapter when `ANTHROPIC_API_KEY` is configured (`tool_use`/`tool_result` blocks; the second native-tool provider so the harness is not judged by one model), Gemini function declarations, Ollama chat tools for capable models. `ProviderResponse.tool_calls` filled natively; the marker parser runs only when `supports_tools` is false. Acceptance: one recorded-fixture test per dialect (request body shape, response parsing, malformed-JSON handling returns an error result, not a crash).
5. **Typed turns in the session.** *Lock `orchestration`, `cognition`.* (L2) `session.messages` holds assistant messages with `tool_calls` and tool-result messages keyed by `tool_call_id`; Cognition sends them as messages (the compactor's `[role] content` flattening applies only to the fallback dialect). Acceptance: a fixture test that the provider receives alternating assistant/tool messages; `test_cli_end_to_end.py` unchanged.
6. **N calls per turn; reads concurrent, writes in order.** *Lock `orchestration`.* `_run` partitions `tool_calls`: read-only via `asyncio.gather` over `_propose_and_await`, mutating sequential, stop at first error; one tool turn with N results in the original order; `action_id = tool_call.id`. `parallel_read_tools` stays as the cap. Acceptance: `tests/simorgh/orchestration/test_parallel_tool_calls.py`.
7. **Guardian reads typed args.** *Lock `guardian`.* `ProtectedRule`/`ScopeRule`/`DenylistRule` validate `proposal.args` against the tool's `input_schema` (from `tool.registered`, item 1) and read exact fields instead of `_SUBJECT_ARG_KEYS` guessing. `ToolInfo` is built from the registry, not the proposal (S6). Acceptance: existing rule tests plus one that a proposal whose args fail the schema is denied at `schema`.
8. **Error kinds.** *Lock `contracts`, `execution`, `orchestration`.* (T9) `ToolResult` gains `error_kind: refused | unconfigured | transient | failed`; the ~185 `error="refused: ..."` sites set the kind; `session.py::was_denied` and `ReadFileTool`'s sniffing read the kind. Acceptance: no machine consumer sniffs error text (a grep test).
9. **First flip: VOICE_CHAT on the model that wins.** *Lock `orchestration`, `cognition`.* `[cognition.providers.<name>] tool_dialect = "native"` per provider; flip VOICE_CHAT first, measure BFCL and the trial suite, then CHAT, PATCH, RESEARCH. Police counters (a span attr per rule trigger) establish the baseline; delete a police function on native paths only when its counter reads zero for a bless cycle.
10. **Freeze the marker dialect.** *Lock `orchestration`, `cognition`.* No new markers, no new `_CODE_BEARING_MARKERS`, no new hints; a comment at the top of `orchestration/tools.py` says so and names this stage.
11. **Findings entry** with BFCL/BFCL-parallel per model before and after, prompt tokens per turn, first-try argument accuracy on multi-field tools, MCP tools callable percentage, police triggers per 100 turns.

## Measurements after

| Number | Before | Target |
|---|---|---|
| BFCL, BFCL-parallel (live model) | recorded in item 0 | higher, 3 repeats, CI |
| MCP tools with >1 property callable | 0% | 100% |
| Police triggers per 100 turns (native paths) | baseline from spans | 0 |
| Tool calls per turn (research) | 1 | up to 4 |
| First-try argument accuracy on multi-field tools | measured in item 2 | > 95% |

## Risks and mitigations

- The cheap Together model's native tool quality is unmeasured: keep markers per provider, compare on BFCL before flipping, configure the Anthropic adapter as the second native provider.
- The prompt grows with 98 schemas: per-profile allowlists and one-line rendering; measure tokens.
- Typed turns change compaction: layer tests in `cognition/compaction.py` extended for tool messages.

## Definition of done

- [ ] Items 1-10 with tests; `--tier core` green; CONTRACT.md of cognition, orchestration, execution, guardian, contracts updated.
- [ ] At least VOICE_CHAT and CHAT on native for the live model with a recorded win.
- [ ] Findings entry.
