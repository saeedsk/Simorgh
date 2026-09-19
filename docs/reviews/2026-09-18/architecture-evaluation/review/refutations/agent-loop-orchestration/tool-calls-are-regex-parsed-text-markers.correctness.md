# refute:correctness:Tool calls are regex-parsed text markers

*Workflow: review · Phase: Refute · Agent id: `a7469a6624d4d0946` · Tool calls: 6*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "agent-loop-orchestration". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Find every tools= argument in cognition service and providers | 358: purpose, think_messages, tools=None, 419: Purpose.CONSOLIDATE, [{"role": "user", "content": text}], tools=None, --- |
| 2 | Bash | Look at provider tools handling and the cited service.py call | __init__.py __pycache__ base.py claude_code.py gemini.py ollama.py together.py simorgh/cognition/providers/base.py:41: self, messages: list[dict], *, tools: lis |
| 3 | Bash | Check whether providers actually forward tools, and read instruction block and parser code-bearing markers | == together tools body == simorgh/cognition/providers/claude_code.py:76: self, messages: list[dict], *, tools: list[dict] \| None, max_tokens: int, timeout: floa |
| 4 | Bash | Read the marker parser and check whether any provider body uses the tools argument | == parser 125-140 == # Every entry above is left as written: each one carries the story of # the day it was missing, and this line is what stops the next story. |
| 5 | Bash | Verify parallel-tools feature, guard regexes, six tables, and whether prior reviews already cover marker protocol | == parallel in session/config == simorgh/orchestration/config.py:74: parallel_read_tools: int = 1 simorgh/orchestration/session.py:610: delegate_max_steps: int  |
| 6 | Bash | Check prior reviews for overlap, guard names, args_schema, and parallel-read default | == html marker mentions == == audit md marker/tool protocol == == _ECHO_SHAPES / unhonoured / invented == 161:_ECHO_SHAPES = ( 170: for pattern, why in _ECHO_SH |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** The core claim holds against the code today. Both router.complete calls in cognition/service.py pass tools=None (lines 358 and 419). Every provider's complete() signature accepts `tools: list[dict] | None` (together.py:117, ollama.py:126, gemini.py:36, claude_code.py:76) but no provider body ever uses it: together._complete_sync builds the request body with only model/messages/max_tokens/reasoning_effort and the `tools` parameter is not even forwarded to it; ollama/gemini/claude_code contain no other reference to `tools`. A grep for tool_calls|tool_use|function_call over simorgh/ finds nothing. The tool protocol is the text-marker instruction in _tool_instruction_block (service.py:67-104) parsed by _parse_markers (parser.py:345-381) with the hand-maintained _CODE_BEARING_MARKERS set (parser.py:47-127) whose comments record the repeated silent-truncation defect exactly as claimed. The six name-keyed tables exist at the cited lines (toolargs.py:31,119,125,157,167,256; tools.py:29,268; scaffolds.py:58; session.py:407; parser.py:47). session.py has 11 re.compile and the unhonoured_marker/invented_markers guards (session.py:213,361,1078,1109). Execution tools carry per-class args_schema (execution/container.py:90, geocode.py:35, mcp.py:220, etc.) but tool.registered publishes only description/read_only/reversibility with schema_ref "" (execution/service.py:167-172), so Orchestration cannot receive the schema. Neither docs/architecture-audit-2026.md nor docs/architecture-review-2026-09-18.html mentions markers, regex parsing or function calling, so this is not in the known-findings list. One nuance the claim overstates: "at most one call per message" is the default but not the ceiling. _parse_markers also parses further_calls, and Session._read_batch/_parallel_offer (session.py:1397-1417) run several read-only calls per step when [orchestration] parallel_read_tools >= 2; that setting defaults to 1 (config.py:74) and ~/.simorgh/simorgh.toml does not set it, so in the live configuration it is one call per message, and scaffolds.py:704 still tells the model so. The "~6k tokens of system prompt" figure was not verified. This is genuinely a design decision (provider-agnostic text markers, stdlib-first) whose cost the parser's own comment history documents; severity stays critical because it is the documented root of a recurring per-tool defect class, not a one-off bug.

### evidence

- simorgh/cognition/service.py:358 `purpose, think_messages, tools=None,` and :419 `Purpose.CONSOLIDATE, [...], tools=None,` -- grep -n 'tools=' service.py returns only these two lines
- simorgh/cognition/providers/together.py:117-120 complete() accepts `tools` then calls `self._complete_sync(messages, max_tokens, timeout)` without it; :124-134 request body has only model/messages/max_tokens/reasoning_effort
- grep -n tools ollama.py/gemini.py/claude_code.py: the only hit in each is the complete() signature line (ollama.py:126, gemini.py:36, claude_code.py:76); no body use
- grep -rn 'tool_calls|tool_use|function_call' simorgh/ (non-test): no matches
- simorgh/cognition/service.py:67-104 _tool_instruction_block: 'write its name in capitals, a colon, then your argument, as the very first line of your reply'
- simorgh/cognition/parser.py:345-381 _parse_markers; :127 `_CODE_BEARING_MARKERS |= {tool.upper() for tool in MARKER_SPLIT_FIRST_LINE}`; :47-126 comments record GIT_COMMIT (2026-09-07), PROPOSE_MCP_SERVER, RUN_SHELL, RUN_CONTAINER et al. (2026-09-09), nine domain markers (2026-09-10) each silently truncated for missing from this set
- simorgh/contracts/toolargs.py:31 MARKER_ARG_KEY, :119 MARKER_NO_ARGS, :125 MARKER_SPLIT_FIRST_LINE, :157 MARKER_JSON_REST, :167 MARKER_CODE_REST, :256 MARKER_KEY_VALUES; simorgh/orchestration/tools.py:29 _TOOL_POLICY, :268 _MARKER_ARG_HINT; scaffolds.py:58 _TOOL_NOTES; session.py:407 _ACTION_TIMEOUTS
- grep -c re.compile simorgh/orchestration/session.py = 11; _ECHO_SHAPES :161, _MARKER_LINE :176, _TV_CLAIM :184, _TV_ASK :193, _DASH_ON_TV :236, _COMMIT_CLAIM :242, _PROMISED_BEHAVIOUR :257, _NOTED_PRONUNCIATION :338, _NAMES_SIM :553; invented_markers :213, unhonoured_marker :361, used at :1078 and :1109
- simorgh/execution/service.py:167-172 tool.registered payload = name/version/description/read_only/reversibility/schema_ref ''/provider -- no args_schema; args_schema defined per tool in execution/container.py:90, external.py:122, geocode.py:35, mcp.py:220, notify.py:327, packages.py:185,253, realestate.py:171
- simorgh/orchestration/scaffolds.py:704-705 'One tool call per message: write a single marker line ... Anything after the first marker is ignored.'
- Nuance: simorgh/orchestration/config.py:74 `parallel_read_tools: int = 1` ('1 is off'); session.py:1397-1417 _parallel_offer/_read_batch batch read-only calls only when >= 2; grep parallel ~/.simorgh/simorgh.toml: no match, so live default is one call per message
- grep -i 'marker|function calling|native tool|regex' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md: no matches -- not previously reported

**severity adjustment:** keep

**corrected claim:** Every provider call passes tools=None and every provider silently ignores the `tools` parameter it accepts; the model is asked to write 'TOOL_NAME: argument' as the first line of its reply and a hand-written marker parser turns that into tool calls. By default (parallel_read_tools=1, unset in simorgh.toml) only the first call runs per message; a read-only batching path exists (session.py:1397-1417) but is off. The argument protocol is spread across six name-keyed tables and a hand-maintained _CODE_BEARING_MARKERS set whose comment history records five separate days a new tool silently lost its payload, while Execution already holds a JSON args_schema per tool that tool.registered does not carry.

