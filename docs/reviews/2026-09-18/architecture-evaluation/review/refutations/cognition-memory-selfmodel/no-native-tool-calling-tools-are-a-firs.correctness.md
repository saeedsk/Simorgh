# refute:correctness:No native tool calling: tools are a firs

*Workflow: review · Phase: Refute · Agent id: `a3306e9ef1e154e6a` · Tool calls: 9*

## Task given to the agent

```text
You are reviewing the ARCHITECTURE of Simorgh, a self-improving personal AI agent written in Python (stdlib-first) at /Users/saeed/ws/Simorgh. The creator built it from scratch: ~87k lines in simorgh/, 18 subsystems (one package each) composed by a Kernel, talking only via typed messages on an async Bus, all state in an append-only Ledger of events, a Guardian that is the sole approver of every effect (HMAC token re-verified by Execution), worktree-isolated self-patching, a bootloader (simloader.py) that gates the checkout with the unit suite and rolls back. It chats (CLI/TUI/HTTP/Telegram/WhatsApp), talks (voice pipeline), controls the house (Home Assistant, Reolink cameras, Ring, Cast/Android TV), and runs benchmarks (GAIA/BFCL/SWE-bench).
  
  The creator asked: "review its architecture, evaluate it, tell me where I went wrong and how to improve it."
  
  Ground rules for you:
  - Read the CODE, not the docs, to establish what is true today. docs/EVOLUTION.md (5,254 lines) is a HISTORY; a bug it describes has very likely been fixed since. Do not report a historical finding as current state.
  - Previous reviews already exist and you must NOT simply repeat them. Already known (do not re-report unless you have something materially new to add): cameras use local ffmpeg/HLS instead of Home Assistant; self_patch.draft tool is named in learning/pipeline.py but not registered; Self Model capabilities["tools"] is never populated; no in-prompt sliding dialogue buffer for chat turns (orchestration/context.py); Ledger default backend is JSONL and ~1.4 GB; CHAT profile binds 34 tools; STT latency degrades under self-inflicted load; "unconnected wire" (designed slot, one side implemented, nobody writes it) is the project's dominant bug shape; test coverage thin in persona/learning/worldmodel; sim.sh auto-approve flips one boolean. Read docs/architecture-review-2026-09-18.html and docs/architecture-audit-2026.md quickly if you want the full list.
  - Useful orientation docs (read briefly, then go to code): docs/module-map.md, docs/architecture.md, docs/blueprint/02-system-architecture.md, docs/blueprint/03-contracts-and-messaging.md.
  - Every finding MUST cite file:line evidence you actually read, and where feasible a command whose output you quote. If a claim depends on runtime behaviour, try to establish it by a cheap command (python -c import + inspect, grep, wc, reading ~/.simorgh/simorgh.toml, listing ~/.simorgh/ledger). Do NOT boot the full system, do NOT run the full test suite, do NOT run anything that calls a paid model, do NOT modify any file in the repo.
  - Think like a senior systems architect. Distinguish (a) a design decision that is wrong or over-built for this system's real scale (one laptop, one family), (b) a design that is right but the implementation undermines it, (c) a genuine bug. Say which.
  - Your final text is data for an orchestrator, not a message to a human. Return only the structured output.
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "cognition-memory-selfmodel". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "No native tool calling: tools are a first-line text marker with one positional argument, and the model is never told what a tool does",
    "kind": "wrong-design",
    "severity": "high",
    "claim": "Cognition always passes `tools=None`, the Together/Ollama providers never send a `tools` array, and the model is told only tool NAMES plus a few hand-written argument hints -- so it invents argument shapes, emits its own native `<tool_call>` syntax that has to be unwrapped, and can make at most one call per reply outside a whitelisted parallel set.",
    "evidence": [
      "simorgh/cognition/service.py:357-358 `response, floor = await self._router.complete(purpose, think_messages, tools=None, ...)`; providers/together.py:120-131 builds `body` with only model/messages/max_tokens/reasoning_effort (no `tools`)",
      "simorgh/cognition/service.py:67-93 `_tool_instruction_block`: 'Tools available this turn: NAMES ... write its name in capitals, a colon, then your argument, as the very first line' -- names only; per-tool `tool_hints` are 'a short, hand-maintained, per-tool addendum' (lines 63-66)",
      "simorgh/cognition/parser.py:151-166 `_unwrap_native_tool_tags`: 'GLM-5.3-Flash replied ... <tool_call>SEARCH_CODE: word_count</arg_value>' -- the model uses the tool syntax it was trained on and the parser has to strip it",
      "simorgh/orchestration/tools.py:669-690 `to_action_payload` splits the single `argument` by first line / fenced code / JSON rest per tool; simorgh/orchestration/api.py:111-121 -- `marker_corrected`, `claim_corrected`, `invented_corrected` flags exist to send malformed markers back once each"
    ],
    "why_it_matters": "A large share of the harness's live-caught bugs (markers mid-sentence, invented tools, wrong JSON shape for propose_mcp_server, fenced code in sandbox args) are symptoms of re-implementing function calling in prose for a model that already speaks the OpenAI tools schema. The Guardian invariant does not depend on the marker protocol -- every call still flows through `action.proposed` -- so the safety argument for keeping it does not hold.",
    "recommendation": "Pass the Execution registry's JSON schemas as `tools` on the OpenAI-compatible endpoints (Together and Ollama both accept them) and read `message.tool_calls` back into the same `tool_calls` reply field; keep the marker parser only as the fallback for the CLI provider, which cannot take tools. Do it for the CHAT profile first (34 tools, the primary UX).",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read cited cognition and provider lines | Exit code 1 think_messages.append({"role": "user", "content": compacted.text}) if not think_messages: think_messages.append({"role": "user", "content": ""}) # n |
| 2 | Bash | Locate provider modules and tools usage | (eval):1: no matches found: --include=*.py --- simorgh/cognition/router.py:288: provider.complete(messages, tools=tools, max_tokens=max_tokens, timeout=share, * |
| 3 | Bash | Read cited cognition, parser, tools, api lines | simorgh/cognition/providers/__init__.py simorgh/cognition/providers/gemini.py simorgh/cognition/providers/together.py simorgh/cognition/providers/ollama.py simo |
| 4 | Bash | Check providers' tools handling, hint counts, and known findings docs | ---TOGETHER 117: self, messages: list[dict], *, tools: list[dict] \| None, max_tokens: int, timeout: float \| None = None, 125: body = { 133: body["max_tokens"] = |
| 5 | Bash | Verify provider bodies, tool descriptions elsewhere, registry, and prior reviews | ---TOGETHER-BODY self, messages: list[dict], *, tools: list[dict] \| None, max_tokens: int, timeout: float \| None = None, ) -> ProviderResponse: return await asy |
| 6 | Bash | Read how tool descriptions reach the prompt and tool spec shape | ---SESSION-1340 from simorgh.contracts.skills import discover_skills roots = [(Path(root).expanduser().name or "skills", Path(root).expanduser()) for root in se |
| 7 | Bash | Check whether tool descriptions reach the model anywhere | ---TOOLBASE ---DESC-ATTR 26 ---WHO-READS-DESC ---PROMPT-TOOLS simorgh/cognition/service.py:75: "Tools available this turn: " + names + ". To use one, write its  |
| 8 | Bash | Read scaffold tool block and its callers | ---SCAFFOLD # was finally shown a whole file, its very next reply was "I have # the full file in hand, but the change itself was never # specified" -- it had re |
| 9 | Bash | Count per-tool notes vs. CHAT profile and check schema use | TOOL_NOTES count: 102 CHAT tools: 72 offered (chat+skills): 72 chat tools without a note: 0 [] chat tools without an arg hint: 36 ---NOTES-SAMPLE 58:_TOOL_NOTES |

## Structured reply

**refuted:** False

**verdict:** partly-true

**corrected claim:** Cognition always passes `tools=None` (cognition/service.py:358, :419) and every provider's `complete()` accepts a `tools` parameter and then silently drops it: together.py:117-135 and ollama.py:126-155 build request bodies with no `tools` array, gemini.py:36-39 flattens messages to a prompt, so no native function calling is ever used and the model must speak a first-line `NAME: argument` marker protocol whose native-syntax leakage the parser has to unwrap (parser.py:150-166). Calls are one per reply except a read-only batch (session.py:1397-1410, scaffolds.py:702). BUT the model is NOT told only names: scaffolds.py:697-706 injects a hand-maintained one-line description (`_TOOL_NOTES`, 102 entries, covering all 72 CHAT-profile tools) plus 49 per-tool argument-format hints (orchestration/tools.py `_MARKER_ARG_HINT`), and the Execution tools each carry a `description` and JSON `args_schema` (execution/tools.py:131, 402, 943, 1676, 1722...) that are published on the bus (execution/service.py:169,179) yet never reach the prompt or the provider -- the marker layer duplicates them by hand. Also the CHAT profile now binds 72 tools, not 34.

**reasoning:** The central design claim survives: `tools=None` is hard-coded on both `_router.complete` call sites, and every provider signature takes `tools: list[dict] | None` and then ignores it (`_complete_sync` in together.py and ollama.py are called without it and neither body includes a `tools` key; grep for `"tools"`/`tool_calls` in both provider files returns nothing). The parser's `_unwrap_native_tool_tags`, the per-session `marker_corrected/claim_corrected/invented_corrected` flags, and the one-marker-per-reply rule with a read-only parallel whitelist are all present in the code today. None of the three prior review documents mention "marker", "native tool", or "function calling", so this is not already known. However, the finding overstates the prompt-side gap: it says the model is told "only tool NAMES plus a few hand-written argument hints" and "never told what a tool does". In fact `scaffolds.render` (called from session.py:1243 as `task_rules` on every chat step) emits `- name: note` lines from `_TOOL_NOTES` for every offered tool -- an import shows 102 notes, 0 of the 72 CHAT tools lack one -- and `_MARKER_ARG_HINT` has 49 entries, not a few. The accurate architectural criticism is narrower but still real: Execution already owns per-tool `description` + JSON `args_schema` and publishes them on the bus, yet the prompt layer maintains a parallel hand-written copy and the providers throw away the `tools` argument they accept -- a textbook instance of the project's own "unconnected wire" shape, and the reason argument-shape bugs (propose_mcp_server JSON, fenced code, mid-sentence markers) are handled by prose corrections and parser heuristics instead of schema-validated native tool calls. The known-findings list's "CHAT profile binds 34 tools" is stale; profiles.CHAT.tools has 72 entries today. Severity is kept: the recommendation (send the registry's schemas as native `tools` on Together/Ollama, keep markers as the CLI-provider fallback) is well-founded and materially improves the primary UX, but the reviewer's evidence must be corrected so the creator is not told descriptions are absent when they are merely duplicated by hand.

### evidence

- simorgh/cognition/service.py:357-359 `response, floor = await self._router.complete(purpose, think_messages, tools=None, ...)`; :419 same for CONSOLIDATE. `grep -n 'tools=' simorgh/cognition/service.py` -> only lines 358 and 419, both `tools=None`.
- simorgh/cognition/providers/together.py:117-119 `async def complete(self, messages, *, tools, max_tokens, timeout=None)` -> `return await asyncio.to_thread(self._complete_sync, messages, max_tokens, timeout)` (tools dropped); :125-135 body = {model, messages, [max_tokens], [reasoning_effort]} -- no `tools`. `grep -n 'tool_calls\|"tools"' together.py ollama.py` -> no output.
- simorgh/cognition/providers/ollama.py:126-129 same pattern, `_complete_sync(messages, max_tokens, timeout, images)`; :150-154 body = {model, stream, keep_alive, think, options, messages} -- no `tools`.
- simorgh/cognition/providers/gemini.py:36-39 flattens all messages into one prompt string; tools ignored.
- simorgh/cognition/parser.py:150-166 `_NATIVE_TOOL_TAG` regex and `_unwrap_native_tool_tags` with the GLM-5.3-Flash `<tool_call>` live-catch docstring -- present today.
- simorgh/orchestration/api.py:111-121 `marker_corrected`, `claim_corrected`, `invented_corrected` flags on Session -- present today.
- simorgh/orchestration/scaffolds.py:697-706: `lines = [f"- {name}: {_TOOL_NOTES[name]}" ...]`; `"One tool call per message: write a single marker line ... Anything after the first marker is ignored.\n\nTools available to you this session:\n" + "\n".join(lines)` -- descriptions ARE sent. Called from session.py:1243 (`"task_rules": scaffolds.render(...)`).
- python3 -c import check: `TOOL_NOTES count: 102`, `CHAT tools: 72`, `chat tools without a note: 0 []`, `chat tools without an arg hint: 36`; `hints: 49` entries in orchestration/tools.py `_MARKER_ARG_HINT`.
- simorgh/execution/tools.py: 26 `description = ` attrs and per-tool `args_schema` JSON (lines 131, 192, 234, 402, 587, 943, 1028, 1093, 1224, 1676, 1722, 1921, 1965, 2014); execution/service.py:169,179,449,657 publish `tool.description` on the bus; `grep -rn '\.description' simorgh/orchestration simorgh/cognition` -> nothing consumes it for the prompt.
- simorgh/orchestration/session.py:1397-1402 `_parallel_offer` whitelists only `is_read_only` tools; :1404-1410 `_read_batch` runs the first call plus following read-only calls only -- confirms one call per reply outside the read-only set.
- `grep -n -i 'marker\|native tool\|function calling\|tool_calls' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md` -> no output; not previously reported.

**severity adjustment:** keep

