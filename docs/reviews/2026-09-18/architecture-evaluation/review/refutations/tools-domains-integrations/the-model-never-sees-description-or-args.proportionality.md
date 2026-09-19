# refute:proportionality:The model never sees description or args

*Workflow: review · Phase: Refute · Agent id: `adab8843469d6ac0c` · Tool calls: 21*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "tools-domains-integrations". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 2 | Bash | Check providers for native function calling | --- __init__.py __pycache__ base.py claude_code.py gemini.py ollama.py together.py |
| 3 | Bash | Find consumers of args_schema | (eval):1: no matches found: --include=*.py |
| 4 | Bash | Inventory args_schema consumers and marker tables | simorgh/contracts/toolargs.py:109: # command, args, ...), but its one `args_schema` property is a simorgh/execution/service.py:452: "marker_arg_key": mcp_single |
| 5 | Bash | Find the recorded failure comments in the tables | simorgh/contracts/toolargs.py:91: # "refused: no command given". The tool had never once run from the simorgh/contracts/toolargs.py:92: # model's side; two obse |
| 6 | Bash | Check what tool.registered carries and who reads description |  except Exception as exc: # noqa: BLE001 -- a bad server degrades, never crashes Execution's boot detail = f"mcp server {server.name!r} failed to start: {exc!r} |
| 7 | Bash | Measure schema sizes, check existing tests and provider shapes | home_call simorgh/execution/home/tools.py 5 ring_live simorgh/execution/home/ring.py no schema match dash_view simorgh/execution/media/cast.py no schema match - |
| 8 | Bash | Check multi-arg tools against the marker tables and the args_from_text router | simorgh/contracts/toolargs.py:44: "ring_live": "camera", simorgh/contracts/toolargs.py:53: "dash_view": "view", simorgh/contracts/toolargs.py:143: "home_call":  |
| 9 | Bash | Check builtin registration payload and whether any test cross-checks registry against tables | --- builtin tool.registered --- 107: produces = (topics.ACTION_RESULT, topics.ACTION_DENIED, topics.TOOL_REGISTERED, topics.PERCEPT_WEB_FETCHED, topics.SYSTEM_M |
| 10 | Bash | Cross-check registered tool classes against the marker and policy tables | Traceback (most recent call last): File "<stdin>", line 6, in <module> ImportError: cannot import name 'Tool' from 'simorgh.execution.tools' (/Users/saeed/ws/Si |
| 11 | Bash | Check whether any test cross-checks marker tables against the registry; find tool base class |  leave the machine; a tool declaring `network` would be gated as though they might.""" for marker in ("KB_SEARCH: x", "KB_ASK: x", "KB_OPEN: x", "KB_STATUS:", " |
| 12 | Bash | Read builtin registration payload and how hints reach the prompt |  system_tools = ( worktree_tools(self._worktrees, land_timeout_s=self._config.test_timeout_s + 60.0) if self._worktrees is not None else [] ) # External adapter |
| 13 | Bash | Check remaining providers for native tools and the configured primary provider | 36: self, messages: list[dict], *, tools: list[dict] \| None, max_tokens: int, timeout: float \| None = None, --- ollama --- --- which provider is primary in toml |
| 14 | Bash | Check whether the provider interface has a tools slot and whether anything fills it | simorgh/cognition/providers/base.py:41: self, messages: list[dict], *, tools: list[dict] \| None, max_tokens: int, timeout: float = 0.0, simorgh/cognition/provid |
| 15 | Bash | Instantiate builtin tools and cross-check against marker and policy tables | (eval):1: command not found: timeout |
| 16 | Bash | Check if any provider body actually forwards the tools parameter | == gemini: uses of 'tools' inside body == == together: uses of 'tools' inside body == == ollama: uses of 'tools' inside body == == claude_code: uses of 'tools'  |
| 17 | Bash | Instantiate builtin tools and cross-check against marker and policy tables | builtin tools: 98 avg desc: 173 with schema: 98 builtin tools with NO marker-table entry (args_from_text -> {}): 5 ['camera_describe', 'dash_key', 'music_now',  |
| 18 | Bash | Check whether the unroutable tools are ever offered to the model | --- are the 3 unroutable-with-required tools in any model-facing profile? --- simorgh/orchestration/profiles.py:67: "cast_devices", "cast_show", "cast_play", "c |
| 19 | Bash | Check for a registry-vs-marker-table test and churn on the two tables | --- any test iterating builtin_tools against marker tables? --- tests/simorgh/execution/test_websearch.py tests/simorgh/execution/test_console_tail.py (end) awa |
| 20 | Bash | Verify dash_key is a live unreachable tool, which profiles offer it, and the configured providers | 1:1290- remote never reaches a Cast receiver, so Sim relays keys: this tool 2:1291- publishes `ui.dash.key`, the HTTP API keeps it, the page polls it.""" 4:1293 |
| 21 | Bash | Confirm dash_key schema and profile membership, and the default provider order |  name = "dash_key" read_only = False reversibility = "reversible" ALIASES = {"enter": "ok", "select": "ok", "center": "ok", "open": "ok", "escape": "back", "esc |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line checks out, and the code around it makes the finding stronger, not weaker. (1) simorgh/cognition/service.py:67-93 builds the model-facing tool block from upper-cased names plus `payload["tool_hints"]` only; the comment at :58-60 explicitly declines to send descriptions because of the module-boundary test. (2) The provider interface HAS a native-tools slot that nothing writes: base.py:41 and all four providers declare `tools: list[dict] | None`, cognition/service.py:358 and :419 always pass `tools=None`, and `grep -n tools` inside gemini/together/ollama/claude_code bodies returns nothing beyond the signature. That is the project's own 'unconnected wire' shape applied to function calling, a detail the finding did not have. (3) `builtin_tools(Config())` instantiates 98 tools, average description 173 chars, all 98 with args_schema; the only args_schema consumer is `mcp_single_arg_key` (execution/service.py:452,456), and `tool.registered` for builtins (execution/service.py:167-172) carries description but no schema and no marker key. (4) The table count is an undercount: toolargs.py has MARKER_ARG_KEY (64), MARKER_NO_ARGS (7), MARKER_SPLIT_FIRST_LINE (23), MARKER_JSON_REST (16), MARKER_CODE_REST, MARKER_KEY_VALUES; orchestration/tools.py has _MARKER_ARG_HINT (49) and _TOOL_POLICY (105); scaffolds._TOOL_NOTES and session._ACTION_TIMEOUTS are two more per-tool tables the existing tests (test_tools_router.py:522-533) require rows in. (5) The bug is live today, not just historical: cross-checking the 98 builtins against every toolargs table leaves 5 tools with no entry (`args_from_text` returns `{}` per toolargs.py:264-300), three of which have a schema-required argument: camera_describe, dash_key, ring_setup. `dash_key` is in the CHAT profile (profiles.py:12 -> :67) and VOICE_CHAT (:198); its run() (cast.py:1306-1310) refuses on an empty key, so `DASH_KEY: left` from the model cannot ever have worked. (6) Ten single-key-routed tools have >=3 schema properties (dash_view 10, mail_search 6, kb_search 4, ring_live 4, cam_ptz 4, cast_show 4, cast_play 4, tv_app 3, tv_pair 3, cam_stream 3), so the 'first line only' loss is broader than the two examples given. (7) No test iterates builtin_tools against the marker tables (only against _TOOL_POLICY, and only per-subsystem), which is exactly the gap dash_key fell through. Scale lens: this is not over-engineering for one laptop; the cost is paid per tool added, the creator has 98 tools and keeps adding (toolargs.py 19 commits, orchestration/tools.py 60), and the drift has already shipped an unreachable tool in the default chat profile. Steps 1-3 of the recommendation delete work rather than add it. Two corrections to the recommendation: step 4 is not possible on the current Claude provider, which is a `claude -p --output-format json --disallowedTools "*"` subprocess (claude_code.py:92), not the API; it is feasible on Together (first in provider_order, cognition/config.py:73) and Gemini, both plain HTTP chat calls. And 'five tables' should read seven-plus.

### evidence

- simorgh/cognition/service.py:67-93 `_tool_instruction_block`: `names = ", ".join(sorted(tool.upper() for tool in tools))`; only `payload.get("tool_hints")` adds per-tool text; :58-60 comment: descriptions 'would cross the subsystem boundary'
- simorgh/cognition/providers/base.py:41 `complete(self, messages, *, tools: list[dict] | None, ...)`; cognition/service.py:358 and :419 pass `tools=None`; `grep -n tools` in gemini.py/together.py/ollama.py/claude_code.py bodies (excluding the signature) -> no output: the native-tools slot is declared and never written
- python: `builtin_tools(Config())` -> 98 tools, avg description 173 chars, 98 with args_schema; `grep -rn args_schema simorgh` non-definition consumers: only execution/service.py:452,456 `mcp_single_arg_key(tool.args_schema)`
- execution/service.py:167-172 builtin `tool.registered` payload = name/version/description/read_only/reversibility/schema_ref=""/provider -- no schema, no marker key
- Table sizes (python import): MARKER_ARG_KEY 64, MARKER_NO_ARGS 7, MARKER_SPLIT_FIRST_LINE 23, MARKER_JSON_REST 16, plus MARKER_CODE_REST (toolargs.py:167) and MARKER_KEY_VALUES (:256); orchestration/tools.py _MARKER_ARG_HINT 49, _TOOL_POLICY 105; scaffolds._TOOL_NOTES and session._ACTION_TIMEOUTS also per-tool (tests/simorgh/orchestration/test_tools_router.py:522-533)
- Cross-check builtin names vs all toolargs tables: 5 tools unroutable (args_from_text -> {}): camera_describe, dash_key, music_now, ring_list, ring_setup; 3 of them have schema `required`: camera_describe, dash_key, ring_setup
- simorgh/orchestration/profiles.py:67 (inside CHAT, defined :12) and :198 (VOICE_CHAT) list "dash_key"; simorgh/execution/media/cast.py:1303-1310 `args_schema = {... "required": ["key"] ...}` and run() returns `refused: no dashboard key ''` when args is {} -- live instance of the finding today
- Single-key-routed tools with >=3 schema properties: kb_search 4, tv_app 3, ring_live 4, dash_view 10, tv_pair 3, mail_search 6, cam_ptz 4, cast_show 4, cast_play 4, cam_stream 3 (toolargs.py:44 ring_live->camera, :53 dash_view->view)
- Recorded failures confirmed: toolargs.py:91-92 run_shell 'had never once run from the model's side; two observers found it independently'; :156 'had never once worked from the model's side'; orchestration/tools.py:544 'both had never once'
- tests: `grep -rln builtin_tools tests | xargs grep -l MARKER_ARG_KEY` -> only test_websearch.py (one tool) and test_console_tail.py (names only); no test iterates the registry against the marker tables; _TOOL_POLICY cross-checks exist only per subsystem (test_tools_router.py:529-544, 609-616, 681-688)
- simorgh/cognition/providers/claude_code.py:92 `argv = [binary_path, "-p", prompt, "--output-format", "json", "--disallowedTools", "*"]` -- the Claude provider is the CLI, so native tool_use (recommendation step 4) is not available there; cognition/config.py:73 provider_order = ("together", "claude_code_cli", "gemini", "floor")
- Churn: `git log --format=%h -- simorgh/contracts/toolargs.py | wc -l` -> 19; `-- simorgh/orchestration/tools.py` -> 60

**severity adjustment:** keep

**corrected claim:** Tools carry a JSON schema and a description no model-facing code reads: the model gets upper-cased names plus hand-written hints and answers `NAME: one line`, and arguments are reconstructed from seven-plus hand-maintained per-tool tables spread over contracts/toolargs.py, orchestration/tools.py, orchestration/scaffolds.py and orchestration/session.py. The provider interface already declares a native `tools` parameter that Cognition always passes as None and no provider forwards. Today `dash_key` (schema-required `key`, offered in the CHAT and VOICE_CHAT profiles) has no marker-table entry and so cannot be called from the model; ten single-key-routed tools have 3-10 schema properties the marker layer cannot express. Deriving marker shape and hints from args_schema and adding one registry-wide routability test is small and net-negative work; native tool calling is feasible on Together and Gemini but not on the Claude CLI provider as built.

