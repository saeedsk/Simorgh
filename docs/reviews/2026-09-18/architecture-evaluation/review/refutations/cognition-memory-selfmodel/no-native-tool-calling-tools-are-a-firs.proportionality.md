# refute:proportionality:No native tool calling: tools are a firs

*Workflow: review · Phase: Refute · Agent id: `a8eecdeab5f6ac4c1` · Tool calls: 11*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "cognition-memory-selfmodel". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Read cited cognition and together provider lines | Exit code 1 think_messages.append({"role": "user", "content": compacted.text}) if not think_messages: think_messages.append({"role": "user", "content": ""}) # n |
| 2 | Bash | Locate provider files and tools handling | simorgh/cognition/providers/together.py simorgh/cognition/providers/ollama.py ---- simorgh/cognition/providers/together.py:117: self, messages: list[dict], *, t |
| 3 | Bash | Read all cited spans plus provider tool handling |  def model(self) -> str: return self._model def available(self) -> bool: return bool(self._api_key) async def complete( self, messages: list[dict], *, tools: li |
| 4 | Bash | Check primary provider, CLI provider tool support, hint coverage, boundary test, description path | == toml providers 22:[cognition] 23- 24:[cognition.providers] 25- 26:[cognition.providers.ollama] 27-model = "qwen3:4b-instruct" 28-only_purposes = ["chat"] 29- |
| 5 | Bash | Read tool description lines, provider order, hint table, boundary rule | == session tool lines cards, invalid = discover_skills(roots) self._skill_cache = (cards, invalid) for bad in invalid: self._log_invalid_skill(bad) return list( |
| 6 | Bash | Inspect think payload, hint count, registry schema, prompt descriptions, configured model | == think payload # session was told what it *could* call and never what # finishing means -- live 2026-09-07, a run applied its # edit and stopped without commi |
| 7 | Bash | Check scaffold rendering, ToolSpec fields, tool counts, marker bug frequency, GLM support note | == scaffolds offered rendering 25:from .tools import offered_tools 45:def unavailable_note(offered: tuple[str, ...] \| list[str]) -> str: 46: """What to tell the |
| 8 | Bash | Measure tool note coverage and execution tool base class | == _TOOL_NOTES CHAT tools: 72 without note: [] == sample rendered lines stamp = when_line(now) if stamp: body = f"{stamp}\n\n{body}" if body else stamp # `offer |
| 9 | Bash | Sample tool notes and their source, check Together response parsing | notes total: 102 web_fetch: 'fetch a URL; HTML comes back as text and a PDF as its text' home_call: 'do something in the house through Home Assistant -- a light |
| 10 | ToolSearch | {"query": "select:WebFetch", "max_results": 1} |  |
| 11 | WebFetch | {"url": "https://docs.together.ai/docs/function-calling", "prompt": "Does Together's function calling / tools parameter work on the chat com | Based on the provided content, I can confirm that Together supports function calling through a `tools` parameter, and the documentation indicates this works wit |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The mechanical claims verify: Cognition passes tools=None (service.py:358, :419); Together and Ollama accept a `tools` kwarg and drop it on the floor -- neither `_complete_sync` even receives it, and the request bodies carry only model/messages/max_tokens/reasoning_effort (together.py:116-133) or model/stream/keep_alive/think/options/messages (ollama.py:125-154); `ProviderResponse` has no tool_calls field, so even a provider that returned `message.tool_calls` would have nowhere to put it. The marker protocol, native-tag unwrapping (parser.py:149-166), per-tool argument splitting (tools.py:669-690), and the three one-shot correction flags (api.py:111-121) are all as described. One call per reply outside the parallel whitelist is real (scaffolds.py:700-706 'One tool call per message ... Anything after the first marker is ignored'; `_parallel_offer` session.py:1398). The Guardian point is right: `to_action_payload` consumes a plain {tool,args} dict, so native tool_calls would flow through `action.proposed` unchanged.

Two sub-claims are wrong and they carry the headline. (1) 'the model is never told what a tool does' is false: scaffolds.py:58 `_TOOL_NOTES` holds 102 one-line descriptions and render() at :696 emits `- name: note` for every offered tool into task_rules; importing the CHAT profile shows all 72 of its tools have a note (e.g. home_call: 'do something in the house through Home Assistant -- a light, the thermostat, the TV. Reports what actually changed...'). (2) 'a few hand-written argument hints' undercounts: `_MARKER_ARG_HINT` has 45 entries. The accurate architectural finding is different and smaller: Execution already owns a `description` and an `args_schema` per tool (execution/tools.py:128, :131, :189, :224, 27 schema declarations), yet Orchestration re-describes the same tools by hand in `_TOOL_NOTES` (102), `_MARKER_ARG_HINT` (45), and four split tables (`_MARKER_SPLIT_FIRST_LINE`, `_MARKER_ARG_KEY`, `_MARKER_NO_ARGS`, `_MARKER_JSON_REST`), explicitly to avoid crossing the module boundary (cognition/service.py:57-61). That is three hand-maintained shadows of one registry -- a drift hazard (the known-list's 'CHAT binds 34 tools' is already 72 today), but it is duplication, not absence.

On the scale lens, the recommendation is oversized for its payoff. provider_order is ("together", "claude_code_cli", "gemini", "floor") (config.py:73) and the memory notes record that Together's day cap silently fails over to the Claude CLI; the CLI provider flattens messages into `-p` plus `--system-prompt` with `--disallowedTools "*"` (claude_code.py:75-93) and can never take a tools array, so the marker parser stays a live daily path, not a 'fallback'. Together's function-calling page confirms a `tools` parameter but defers model support to its catalog; whether the configured GLM-5.3-Flash supports it was not verifiable here. Adding native tools means a new ProviderResponse field, router plumbing, tool-role transcript messages in session.messages, and a second parse path kept in sync with the marker path across four providers -- for a one-laptop system whose model changes with the day's budget. The marker bugs are real and numerous (51 'marker' mentions in EVOLUTION.md, 78 in parser.py, 42 in session.py), so the pain is genuine, but the cheaper fix that addresses the actual defect (drift between hand tables and the registry) is to have Execution publish its catalog (name, description, args_schema, marker shape) on the bus at boot so Orchestration renders from one source, keeping the marker protocol the CLI provider needs anyway. Native tool calling on Together/Ollama is a reasonable later optimisation, not a high-severity design error.

**corrected claim:** Cognition never sends tool schemas to any provider (service.py:358 tools=None; together.py:116-133 and ollama.py:125-154 discard the `tools` kwarg; ProviderResponse has no tool_calls field), so tool use is a first-line text marker with one positional argument, one call per reply outside a read-only parallel set (scaffolds.py:700-706). The model IS told what each tool does -- scaffolds.py:58 `_TOOL_NOTES` (102 entries, covering all 72 CHAT tools) renders `- name: note` per offered tool, and `_MARKER_ARG_HINT` (45 entries) adds argument shapes -- but those tables, plus four marker-split tables in orchestration/tools.py, are hand-maintained shadows of the `description` and `args_schema` Execution already declares per tool (execution/tools.py:128-131 etc.), kept separate to honour the module boundary (cognition/service.py:57-61). The real defect is that duplication and its drift, not the absence of descriptions. Because the second provider in order, the Claude CLI (claude_code.py:75-93, config.py:73), can never accept a tools array and is the documented daily failover, the marker parser must remain a primary path; native OpenAI-style tools on Together/Ollama would be an addition of a second parse path, not a replacement.

### evidence

- simorgh/cognition/service.py:357-359 `response, floor = await self._router.complete(purpose, think_messages, tools=None, ...)`; also :419 for CONSOLIDATE
- simorgh/cognition/providers/together.py:116-119 `async def complete(self, messages, *, tools, max_tokens, timeout=None)` calls `self._complete_sync(messages, max_tokens, timeout)` -- `tools` never forwarded; :125-133 body = model/messages/max_tokens/reasoning_effort only
- simorgh/cognition/providers/ollama.py:125-129 same drop of `tools`; :150-154 body = model/stream/keep_alive/think/options/messages
- grep -rn 'tool_calls\|"tools"' simorgh/cognition/providers/ -> no output (no provider builds or reads a tools array)
- simorgh/cognition/service.py:57-61 comment: 'Tool names alone (no per-tool argument semantics) rather than reaching into Execution's tool registry for real descriptions -- that would cross the subsystem boundary test_module_boundaries.py enforces'; :67-93 `_tool_instruction_block`
- simorgh/orchestration/scaffolds.py:58 `_TOOL_NOTES: dict[str, str] = {`; :696 `lines = [f"- {name}: {_TOOL_NOTES[name]}" if name in _TOOL_NOTES else f"- {name}" for name in offered]`; :700-706 'One tool call per message ... Anything after the first marker is ignored.\n\nTools available to you this session:'
- python3 -c import of simorgh.orchestration.scaffolds._TOOL_NOTES and profiles.CHAT -> 'notes total: 102', 'CHAT tools: 72', 'without note: []'; sample home_call: 'do something in the house through Home Assistant -- a light, the thermostat, the TV. Reports what actually changed, which is not always what was asked'
- ast count of simorgh/orchestration/tools.py `_MARKER_ARG_HINT` (:268 and :298 update) -> 'hints: 45'; split tables at :252 `_MARKER_ARG_KEY`, :297 `_MARKER_SPLIT_FIRST_LINE`, :519 `_MARKER_NO_ARGS`, :547 `_MARKER_JSON_REST`
- simorgh/execution/tools.py:126-131 `class ReadFileTool: description = "Read a file's contents (path-safety bounded)." ... args_schema = {"type": "object", "required": ["path"], ...}`; regex count -> 27 `args_schema =` declarations
- simorgh/orchestration/tools.py:669-690 `to_action_payload` splits `args["argument"]` by tool; consumes a plain {tool,args} dict, so Guardian flow is protocol-independent
- simorgh/cognition/parser.py:149-166 `_NATIVE_TOOL_TAG` / `_unwrap_native_tool_tags` (GLM-5.3-Flash <tool_call> leak, live 2026-09-07); :168-175 count_markers 'Only the first is ever executed'
- simorgh/orchestration/api.py:111-121 `marker_corrected`, `claim_corrected`, `invented_corrected` flags
- simorgh/cognition/config.py:73 `provider_order = ("together", "claude_code_cli", "gemini", "floor")`; ~/.simorgh/simorgh.toml:26-32 Ollama qwen3:4b-instruct only_purposes=["chat"]
- simorgh/cognition/providers/claude_code.py:75-93 flattens messages to `-p prompt --system-prompt ... --disallowedTools "*"` -- cannot accept a tools array
- grep -ci marker docs/EVOLUTION.md -> 51; simorgh/cognition/parser.py -> 78; simorgh/orchestration/session.py -> 42
- WebFetch docs.together.ai/docs/function-calling: `tools` parameter exists; model support 'see the serverless and dedicated model inference catalogs' -- GLM-5.3-Flash support not confirmed

**severity adjustment:** lower

