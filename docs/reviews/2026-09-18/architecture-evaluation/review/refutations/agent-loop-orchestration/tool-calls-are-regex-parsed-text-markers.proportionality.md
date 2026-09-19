# refute:proportionality:Tool calls are regex-parsed text markers

*Workflow: review · Phase: Refute · Agent id: `ab1f27a63c7191722` · Tool calls: 10*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "agent-loop-orchestration". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "Tool calls are regex-parsed text markers; native function calling is never used",
    "kind": "wrong-design",
    "severity": "critical",
    "claim": "Every provider call passes tools=None and the model is asked to write 'TOOL_NAME: argument' as the first line of its reply, which a regex parser turns into at most one call per message, so the entire tool protocol (argument splitting, multi-line payloads, JSON second lines, dropped markers, invented markers, narrated calls) is reimplemented by hand and keeps breaking per tool.",
    "evidence": [
      "simorgh/cognition/service.py:358 `purpose, think_messages, tools=None,`",
      "simorgh/cognition/service.py:67-104 _tool_instruction_block: 'write its name in capitals, a colon, then your argument, as the very first line of your reply'",
      "simorgh/cognition/parser.py:345-381 _parse_markers runs the first marker; :377 `call[\"dropped_markers\"] = extra`",
      "simorgh/orchestration/scaffolds.py:~700 'One tool call per message: write a single marker line ... Anything after the first marker is ignored.'",
      "Six tool-name-keyed tables must agree for one tool to work: simorgh/contracts/toolargs.py:31,119,125,157,167,256 (MARKER_ARG_KEY, MARKER_NO_ARGS, MARKER_SPLIT_FIRST_LINE, MARKER_JSON_REST, MARKER_CODE_REST, MARKER_KEY_VALUES); simorgh/orchestration/tools.py:29 _TOOL_POLICY, :268 _MARKER_ARG_HINT; simorgh/orchestration/scaffolds.py:58 _TOOL_NOTES; simorgh/orchestration/session.py:407 _ACTION_TIMEOUTS; simorgh/cognition/parser.py:47 _CODE_BEARING_MARKERS",
      "parser.py:47-120 comments record five separate days on which a newly added tool silently lost every line after its first because it was missing from _CODE_BEARING_MARKERS",
      "session.py has 11 compiled guard regexes (grep -c re.compile = 11): _ECHO_SHAPES, _MARKER_LINE, _TV_CLAIM, _TV_ASK, _DASH_ON_TV, _COMMIT_CLAIM, _PROMISED_BEHAVIOUR, _NOTED_PRONUNCIATION, _NAMES_SIM, plus unhonoured_marker/invented_markers, each documented as a live-caught marker failure",
      "Execution already announces description/read_only/reversibility on tool.registered (execution/service.py:169-179) and holds args_schema per tool, but Orchestration cannot read it (module-boundary rule) and rebuilds it by hand",
      "grep -rn 'tools=None|tools:' simorgh/cognition/providers/*.py: every provider accepts a `tools` argument and none is ever given one"
    ],
    "why_it_matters": "This is the root cause behind most of the loop's accreted complexity: one-call-per-message (so a 4-lookup question costs 4 model round trips, each with ~6k tokens of system prompt), argument-shape bugs per tool, and the whole class of 'the model narrated a call instead of making one' fabrications. In 2026 every serious provider (Together's OpenAI-compatible API, Anthropic, Gemini, Ollama) returns structured tool_calls with schema-validated JSON arguments and supports parallel calls; the harness is fighting the model's training instead of using it.",
    "recommendation": "Make tool.registered carry Execution's args_schema and description, have Cognition pass them as native `tools` to the provider, and have the router return structured tool_calls; keep the marker parser only as a fallback for a provider that reports no tool support. Then delete MARKER_*, _MARKER_ARG_HINT, _CODE_BEARING_MARKERS and the marker-shape guards (unhonoured_marker, invented_markers, _transcript_echo). Timeouts and policy (reversibility/network) should ride on the same registration event so _ACTION_TIMEOUTS and _TOOL_POLICY become a cache of what Execution said, not a second source of truth.",
    "confidence": 0.95
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read provider call site and tools argument usage |  think_messages.append({"role": "user", "content": compacted.text}) if not think_messages: think_messages.append({"role": "user", "content": ""}) # never call c |
| 2 | Bash | Read tool instruction block and marker parser | # `web_fetch` is enough on its own. **Second live-catch, same day**: a # name alone was NOT enough for `propose_mcp_server` -- its one argument # has real inter |
| 3 | Bash | Verify tables, regex counts, provider tool support, execution registration | == parallel_read_tools == simorgh/orchestration/config.py:74: parallel_read_tools: int = 1 simorgh/orchestration/service.py:91: parallel_read_tools=self.config. |
| 4 | Bash | Check provider native tool support, schema plumbing, parallel config, and design rationale | == args_schema == simorgh/contracts/toolargs.py:109: # command, args, ...), but its one `args_schema` property is a simorgh/contracts/protocols.py:200: args_sch |
| 5 | Bash | Check primary provider, provider request bodies, table sizes, regex contexts, and design rationale | == toml 18-45 == [execution] secrets = ["vault:*", "SIM_API_TOKEN", "REOLINK_HOST", "REOLINK_USERNAME", "REOLINK_PASSWORD", "RING_TOKEN", "RING_USERNAME"] cast_ |
| 6 | Bash | Check default provider order, prior review coverage, and any recorded rationale | == provider_order default == 73: provider_order: tuple[str, ...] = ("together", "claude_code_cli", "gemini", "floor") 106: # Per-purpose provider order, tried b |
| 7 | Bash | Read cognition blueprint design intent and provider response shape | Exit code 1 **v1 code that migrates here:** `src/cognition/provider.py`, `budget.py`, `claude_code_provider.py`, `gemini_provider.py`, `tool_protocol.py` (marke |
| 8 | Bash | Check provider response shape, native tool support hooks, and step cap | == tool_calls in providers/router == == ToolCapabilities / select_provider survive? == == chat steps: how many think calls per chat turn (max steps) == 68: dele |
| 9 | Bash | Locate ProviderResponse definition | simorgh/cognition/providers/base.py:13:from simorgh.contracts.protocols import ProviderResponse simorgh/cognition/providers/base.py:42: ) -> ProviderResponse: s |
| 10 | Bash | Read ProviderResponse contract fields | class ProviderResponse: text: str provider: str input_tokens: int = 0 output_tokens: int = 0 # Prompt tokens served from the provider's cache, priced at its own |

## Structured reply

**refuted:** False

**verdict:** partly-true

**severity adjustment:** lower

**reasoning:** The core factual claim is confirmed and is materially new (none of docs/architecture-review-2026-09-18.html, docs/architecture-audit-2026.md, docs/architecture-third-opinion-2026-09-18.md mention markers or function calling). Every provider call passes tools=None (cognition/service.py:358, :419); all four providers accept a `tools` parameter and not one references it in its body; contracts/protocols.py:151 declares `ProviderResponse.tool_calls: tuple[dict, ...] = ()` and nothing populates it; docs/blueprint/subsystems/04-cognition.md:20 promises "text, structured tool calls, or floor". This is exactly the project's own "unconnected wire" shape at the provider contract, and the reader is right that it was never wired. Kind is therefore better stated as (b) right design undermined by implementation than as (a) wrong design.

However, several load-bearing sub-claims are overstated, which is why the severity and recommendation are disproportionate: (1) "At most one call per message" is only the default configuration. parser.py:378-381 parses `further_calls`, cognition/service.py:81-88 advertises parallel lookups, and session.py:1397-1415 `_parallel_offer`/`_read_batch` runs read-only calls together when `parallel_read_tools` >= 2 (orchestration/config.py:74 defaults to 1; ~/.simorgh/simorgh.toml does not set it). The "4 lookups = 4 round trips" cost is a one-line config change, not a consequence of the marker design. (2) "Six tables must agree" is stale: parser.py:127 `_CODE_BEARING_MARKERS |= {tool.upper() for tool in MARKER_SPLIT_FIRST_LINE}` closed the recurring truncation class the five dated comments describe; tools.py:252 `_MARKER_ARG_KEY = MARKER_ARG_KEY` is an alias, not a second table. (3) "Orchestration cannot read Execution's schema (module-boundary rule)" is false: execution/service.py:452-456 already sends `marker_arg_key` derived from `tool.args_schema` on tool.registered for MCP tools and orchestration/tools.py:647 consumes it; the boundary is crossed, just not with the full schema. (4) "11 guard regexes each a live-caught marker failure": only _ECHO_SHAPES (3) and _MARKER_LINE are marker-protocol guards. _TV_CLAIM, _TV_ASK, _DASH_ON_TV, _COMMIT_CLAIM, _PROMISED_BEHAVIOUR (session.py:184-262) catch the model narrating an effect without calling any tool, which native function calling does not eliminate; _NOTED_PRONUNCIATION and _NAMES_SIM are voice/wake-word. Those would survive the proposed rewrite. (5) The deletion promise is not achievable for this deployment: default provider_order is ("together", "claude_code_cli", "gemini", "floor") (cognition/config.py:73) and the second provider is `claude -p <prompt> --output-format json --disallowedTools *` (providers/claude_code.py:92), a subprocess that returns text and takes no custom tool schemas; memory records Together's day cap routinely failing over to it. So markers must stay as the live protocol for a real provider, and both parsers would coexist. _TOOL_POLICY (105 entries) and _ACTION_TIMEOUTS (46) are Guardian policy and timeouts, needed under either protocol; making them a cache of tool.registered is a sound, cheap, independent improvement.

At this scale (one developer adding tools by hand), each new tool already costs a Tool class with args_schema plus one or two dict entries; native calling would replace the dict entries with the schema the class already has, a real simplification but not a "critical" one. The proportionate version: implement native tool_calls on the Together (OpenAI-compatible /chat/completions, together.py:138) and Ollama (/api/chat, ollama.py:155) providers, carry args_schema+description on tool.registered, keep markers for the CLI provider, and flip parallel_read_tools now.

### evidence

- simorgh/cognition/service.py:358 `purpose, think_messages, tools=None,` and :419 same for CONSOLIDATE
- grep -n tools simorgh/cognition/providers/{together,gemini,ollama,claude_code}.py -> only the `complete(... tools: list[dict] | None ...)` signature line in each; no body use
- simorgh/contracts/protocols.py:151 `tool_calls: tuple[dict, ...] = ()` on ProviderResponse; grep tool_calls simorgh/cognition/providers/ simorgh/cognition/router.py -> no matches
- docs/blueprint/subsystems/04-cognition.md:20 'gets back either text, structured tool calls, or an honest floor: true reply'
- simorgh/cognition/config.py:73 `provider_order = ("together", "claude_code_cli", "gemini", "floor")`; providers/claude_code.py:92 `argv = [binary_path, "-p", prompt, "--output-format", "json", "--disallowedTools", "*"]`
- simorgh/cognition/parser.py:378-381 `further = further_calls(text, markers) if extra > 0 else ()` ... `tool_calls=(call, *further)`
- simorgh/orchestration/session.py:1397-1415 _parallel_offer / _read_batch; orchestration/config.py:74 `parallel_read_tools: int = 1`; ~/.simorgh/simorgh.toml sets no [orchestration] key
- simorgh/cognition/service.py:81-88 parallel lookup instruction emitted when max_parallel_tools > 1
- simorgh/cognition/parser.py:127 `_CODE_BEARING_MARKERS |= {tool.upper() for tool in MARKER_SPLIT_FIRST_LINE}`
- simorgh/orchestration/tools.py:252 `_MARKER_ARG_KEY = MARKER_ARG_KEY` (alias)
- simorgh/execution/service.py:452-456 tool.registered payload includes `"marker_arg_key": mcp_single_arg_key(tool.args_schema)`; orchestration/tools.py:647 `_MARKER_ARG_KEY[name] = marker_arg_key`
- python -c table sizes: MARKER_ARG_KEY 64, MARKER_NO_ARGS 7, MARKER_SPLIT_FIRST_LINE 23, MARKER_JSON_REST 16, MARKER_CODE_REST 3, MARKER_KEY_VALUES 4, _TOOL_POLICY 105, _MARKER_ARG_HINT 49, _TOOL_NOTES 102, _ACTION_TIMEOUTS 46, _CODE_BEARING_MARKERS 32
- grep -c re.compile simorgh/orchestration/session.py -> 11; session.py:160-176 _ECHO_SHAPES(3)+_MARKER_LINE are the only marker-protocol guards; :184-262 _TV_CLAIM/_TV_ASK/_DASH_ON_TV/_COMMIT_CLAIM/_PROMISED_BEHAVIOUR guard narrated effects; :338 _NOTED_PRONUNCIATION and :553 _NAMES_SIM are voice
- simorgh/orchestration/scaffolds.py:704-705 'One tool call per message ... Anything after the first marker is ignored.'
- grep -i 'marker|function.calling|native tool|tool_calls' over docs/architecture-review-2026-09-18.html, docs/architecture-audit-2026.md, docs/architecture-third-opinion-2026-09-18.md -> no matches (not already known)

**corrected claim:** Native function calling is designed into the contracts (ProviderResponse.tool_calls, a `tools` parameter on every provider, the cognition blueprint) but implemented by no provider; every call passes tools=None and the model is steered to a text marker protocol maintained by hand across several tool-name-keyed tables. This is a genuine unconnected wire and a real maintenance tax, but it is not the root cause of most loop complexity: parallel read calls already exist behind `parallel_read_tools` (default 1), the recurring multi-line truncation class was closed by parser.py:127, tool.registered already carries a schema-derived arg key across the boundary, and most session guard regexes catch narrated effects that native calling would not prevent. Because the second provider in the default order is the Claude CLI subprocess (text only, no custom tool schemas), the marker path must remain; the proportionate fix is native tool_calls on Together and Ollama plus args_schema/description/reversibility on tool.registered, with markers kept as the CLI fallback, and parallel_read_tools raised now. Severity: high at most, not critical.

