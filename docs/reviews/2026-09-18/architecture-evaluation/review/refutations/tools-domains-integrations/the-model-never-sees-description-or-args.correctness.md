# refute:correctness:The model never sees description or args

*Workflow: review · Phase: Refute · Agent id: `af61a79401e3c3194` · Tool calls: 15*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "tools-domains-integrations". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "The model never sees description or args_schema; the real argument contract is five hand-maintained marker tables",
    "kind": "wrong-design",
    "severity": "high",
    "claim": "Tools carry a JSON schema and a description that no model-facing code reads: the model gets upper-cased names plus prose hints and answers with `NAME: one line`, and every tool's arguments are reconstructed from hand tables in two other subsystems, which is the root of the recurring 'this tool had never once worked from the model's side' bug.",
    "evidence": [
      "simorgh/cognition/service.py:67-93 `_tool_instruction_block`: `names = \", \".join(sorted(tool.upper() for tool in tools))` + `tool_hints` only; comment at :58 says descriptions 'would cross the subsystem boundary'",
      "`grep -rn \"tool_choice\\|\\\"tools\\\"\\|tools=\\|functions=\\|input_schema\" simorgh/cognition/providers/*.py` -> no output (no native function calling on any provider)",
      "`grep -rn args_schema simorgh` consumers: only simorgh/execution/service.py:452,456 `mcp_single_arg_key(tool.args_schema)` for MCP tools",
      "simorgh/contracts/toolargs.py: MARKER_ARG_KEY (~80 rows), MARKER_NO_ARGS, MARKER_SPLIT_FIRST_LINE, MARKER_JSON_REST; simorgh/orchestration/tools.py: _MARKER_ARG_HINT (~60 prose entries) and _TOOL_POLICY",
      "The tables' own comments record the failures: toolargs.py run_shell ('had never once run from the model's side; two observers found it independently'), git_discard ('had never once worked'); orchestration/tools.py browse_page and run_container ('had never once worked from the model's side'), propose_mcp_server, MCP tools ('could never actually be called from a marker reply')",
      "Measured: dash_view has 10 schema properties and ring_live 4; through the marker layer only the first line plus an optional JSON tail is expressible"
    ],
    "why_it_matters": "Adding one tool needs edits in execution (class), contracts (key table), orchestration (policy + hint) and cognition (nothing, but the hint text is prompt engineering). The code's history shows at least six tools shipped unreachable, and the CHAT profile pays prompt tokens for names whose usage the model must guess. The schemas and 170-char-average descriptions are 98 pieces of dead weight that look like a contract.",
    "recommendation": "Make args_schema the single source. (1) A pure function `marker_shape(schema)` in contracts/toolargs.py: one required string property -> its key; a schema tagged `\"x-marker\": {\"first\": \"path\", \"rest\": \"code\"|\"json\"}` -> split/json-rest; no properties -> no-args. (2) Have Execution put `description`, the schema, and the derived marker shape in tool.registered (it already sends name/reversibility/marker_arg_key), and let Orchestration build hints from `description` + property descriptions instead of `_MARKER_ARG_HINT`. (3) One boot-time test: every registered tool has a routable shape. (4) On the Claude and Together providers pass the schemas as native tools and parse tool_use blocks; keep the marker path as the Ollama floor. Steps 1-3 are a day and delete two tables; step 4 is optional but is what makes multi-argument tools (dash_view, ring_live, home_call) usable.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read the tool instruction block in cognition service |  if expected == "tool_calls": return {"kind": "markers", "markers": tuple(payload.get("tools") or ())} if expected in ("edit_blocks", "verdict"): return {"kind" |
| 2 | Bash | Search providers for native function calling | __init__.py __pycache__ base.py claude_code.py gemini.py ollama.py together.py simorgh/cognition/api.py:140: kind: str # tool_calls \| final \| non_answer \| edit_ |
| 3 | Bash | Find all consumers of args_schema | (eval):1: no matches found: --include=*.py --- (eval):1: no matches found: --include=*.py 0 |
| 4 | Bash | Find args_schema consumers and provider tools handling | simorgh/contracts/toolargs.py:109: # command, args, ...), but its one `args_schema` property is a simorgh/execution/vision.py:198: args_schema = {"type": "objec |
| 5 | Bash | Inspect marker tables in contracts/toolargs.py | 31:MARKER_ARG_KEY: dict[str, str] = { 91: # "refused: no command given". The tool had never once run from the 119:MARKER_NO_ARGS: frozenset[str] = frozenset({ 1 |
| 6 | Bash | Inspect hint and policy tables in orchestration/tools.py | 29:_TOOL_POLICY: dict[str, tuple[str, bool]] = { 268:_MARKER_ARG_HINT: dict[str, str] = { 298:_MARKER_ARG_HINT.update({ 346: # into `_TOOL_POLICY` by mistake in |
| 7 | Bash | Check what tool.registered carries and who reads description | simorgh/execution/service.py:12:module in a sandbox-backed SkillTool, register it, emit tool.registered"), simorgh/execution/service.py:107: produces = (topics. |
| 8 | Bash | Check what each provider does with the tools parameter | === together 117: self, messages: list[dict], *, tools: list[dict] \| None, max_tokens: int, timeout: float \| None = None, === claude_code 76: self, messages: li |
| 9 | Bash | Check tool.registered payload and description consumers |  # the same name is never shadowed by an optional package's. external = load_external_tools(self._config.external_tools, logger=ctx.logger) for tool in builtin_ |
| 10 | Bash | Read the marker table comments and args_from_text |  "run_script": "code", "run_python_sandboxed": "code", "run_js_sandboxed": "code", "run_tests": "target", # Absent until 2026-09-08, so every `RUN_SHELL:` marke |
| 11 | Bash | Measure dash_view/ring_live schema properties and description sizes | run_shell 1 ['command'] === descriptions count/avg 38 177 |
| 12 | Bash | Read the name: description lines builder in session.py and its callers |  from simorgh.contracts.skills import discover_skills roots = [(Path(root).expanduser().name or "skills", Path(root).expanduser()) for root in self._skills_root |
| 13 | Bash | Locate dash_view, ring_live, home_call schemas and count their properties | simorgh/execution/home/tools.py:194: name = "home_call" simorgh/execution/home/ring.py:698: name = "ring_live" simorgh/execution/media/cast.py:956: name = "dash |
| 14 | Bash | Check orchestration's handling of tool.registered and whether prior reviews already cover this | 1:16:from .tools import forget_registered, note_registered, register_tool_policy 2:104: self._tool_sub = await ctx.bus.subscribe(topics.TOOL_REGISTERED, self._o |
| 15 | Bash | Check what orchestration keeps from tool.registered and whether prior reviews cover the marker layer |  async def _on_tool_registered(self, message) -> None: p = message.payload note_registered(p.get("name", "")) register_tool_policy( p.get("name", ""), reversibi |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every load-bearing part of the claim checks out against the code today. (1) No model-facing code reads args_schema or description: cognition/service.py:358 calls `self._router.complete(purpose, think_messages, tools=None, ...)` unconditionally, and all four providers (together.py:117, claude_code.py:76, ollama.py:126, gemini.py:36) mention `tools` only in their `complete()` signature and never use it; grep for tool_choice/input_schema/functions= in providers returns nothing. (2) The prompt the model gets is `_tool_instruction_block` (cognition/service.py:67-93): upper-cased names + "NAME: argument" convention + hand-written `tool_hints`; the comment at :56-59 explicitly says real descriptions were not used because it "would cross the subsystem boundary". (3) args_schema is read only at execution/service.py:452,456 (`mcp_single_arg_key(tool.args_schema)`, MCP only); toolargs.py:109 is a comment. (4) The marker tables exist and carry the cited failure comments: toolargs.py:88-100 (run_shell "had never once run from the model's side; two observers found it independently", git_discard "had never once worked"), :153-156 (JSON_REST "live-caught twice ... never once worked"), orchestration/tools.py:537-548 (browse_page, run_container "had never once worked from the model's side"). (5) Measured schema widths match exactly: dash_view 10 properties (execution/media/cast.py:956), ring_live 4 (home/ring.py:698), home_call 4; run_shell 1. (6) Not in the known-findings list: grep for "marker" in docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html and the third-opinion doc returns nothing. Two factual tweaks: the finding undercounts the tables (toolargs.py has six -- MARKER_ARG_KEY 64 rows, MARKER_NO_ARGS 7, MARKER_SPLIT_FIRST_LINE 23, MARKER_JSON_REST 16, plus MARKER_CODE_REST at :167 and MARKER_KEY_VALUES at :256 -- and orchestration/tools.py adds _MARKER_ARG_HINT 49 and _TOOL_POLICY 105), and its row estimates (~80, ~60) are a bit high (64, 49). One materially new point that makes the recommendation cheaper than stated: Execution ALREADY publishes `description` on tool.registered (execution/service.py:169 and :449), and Orchestration's `_on_tool_registered` (orchestration/service.py:224-231) discards it, keeping only name/reversibility/provider/marker_arg_key -- a textbook instance of the project's "unconnected wire" bug shape, sitting on the tool contract itself. Classification as wrong-design is right: the schema/description fields are a contract nobody honours, and the marker tables reconstruct what the schema already states.

### evidence

- simorgh/cognition/service.py:358 `response, floor = await self._router.complete(purpose, think_messages, tools=None, ...)` -- tools never passed to any provider
- simorgh/cognition/providers/{together.py:117,claude_code.py:76,ollama.py:126,gemini.py:36}: `tools: list[dict] | None` appears only in the signature; `grep -n tools` on each file returns that single line
- simorgh/cognition/service.py:56-59 comment: tool names only 'rather than reaching into Execution's tool registry for real descriptions -- that would cross the subsystem boundary'; :67-93 `_tool_instruction_block` builds `names = ', '.join(sorted(tool.upper() ...))` + `tool_hints`
- `grep -rn args_schema simorgh | grep -v 'args_schema=\|args_schema:'` -> only execution/service.py:452,456 (`mcp_single_arg_key(tool.args_schema)`) and a comment at contracts/toolargs.py:109; 110 total occurrences, the rest are definitions
- python -c import: MARKER_ARG_KEY 64 rows, MARKER_NO_ARGS 7, MARKER_SPLIT_FIRST_LINE 23, MARKER_JSON_REST 16 (contracts/toolargs.py:31,119,125,157); also MARKER_CODE_REST :167 and MARKER_KEY_VALUES :256; orchestration/tools.py _MARKER_ARG_HINT 49 entries (:268), _TOOL_POLICY 105 (:29)
- contracts/toolargs.py:88-100 comments: run_shell 'had never once run from the model's side; two observers found it independently'; git_discard 'had never once worked from the model's side'; :153-156 MARKER_JSON_REST 'Live-caught twice ... the tool had never once worked from the model's side'
- orchestration/tools.py:537-548: browse_page and run_container 'both had never once worked from the model's side'
- Schema widths by import: dash_view 10 properties (execution/media/cast.py:956), ring_live 4 (execution/home/ring.py:698), home_call 4 (execution/home/tools.py:194), run_shell 1
- NEW: execution/service.py:169 and :449 already put `"description": tool.description` on the tool.registered payload; orchestration/service.py:224-231 `_on_tool_registered` reads only name/reversibility/provider/marker_arg_key and drops description
- orchestration/session.py:1355 `_catalog` renders `- name: description` lines, but for SKILLS (contracts/skills.py catalog_text), not tools
- `grep -ic marker` over docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html, docs/architecture-third-opinion-2026-09-18.md -> no matches; not in the known-findings list
- 38 tool classes in execution/tools.py alone carry a description, average 177 chars

**severity adjustment:** keep

**corrected claim:** Tools carry a JSON args_schema and a description that no model-facing code reads: cognition passes tools=None to the router, all four providers ignore the `tools` parameter, and the model sees only upper-cased names plus hand-written hints and answers `NAME: one line`. Arguments are then reconstructed from eight hand-maintained tables (six in contracts/toolargs.py: MARKER_ARG_KEY 64, MARKER_SPLIT_FIRST_LINE 23, MARKER_JSON_REST 16, MARKER_NO_ARGS 7, MARKER_CODE_REST, MARKER_KEY_VALUES; two in orchestration/tools.py: _MARKER_ARG_HINT 49, _TOOL_POLICY 105), whose own comments record at least six tools that shipped unreachable from the model's side. Execution already publishes `description` on tool.registered, but Orchestration discards it -- so the first half of the fix is wiring an existing field, not adding one.

