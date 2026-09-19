# read:tools-domains-integrations

*Workflow: review · Phase: Read · Agent id: `abc546b92da3c502d` · Tool calls: 64*

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
  
  
  CONCERN: the tool layer -- Execution's 98 tools across files/code/git, sandboxes, web, packages, and the six domain packages (knowledge, pim, security, home, energy, media), plus external toolsets and MCP.
  Read simorgh/execution/tools.py (registry, Tool protocol), a representative sample of tools, simorgh/execution/home/, media/, pim/, security/, energy/, knowledge/, external.py, mcp*.py, and orchestration/tools.py (router policy per tool).
  Questions: Is the Tool protocol well designed (schema, result shape, error reporting, truncation, idempotency, reversibility metadata, cost/latency metadata)? How much of the 21.6k lines is dead or speculative (tools never called in the ledger -- if ~/.simorgh/ledger has action streams or a tool-usage projection, measure which tools were ever invoked; otherwise estimate from tests and wiring)? Are integrations (Home Assistant not configured; Reolink direct; Ring; Cast; Android TV; energy) built to the right abstraction (device vs hub), and are they consistent with each other? Is there an honest 'capability floor' (stdlib-only) or has optional-dependency sprawl made behaviour unpredictable? Is 'domains' the right axis of decomposition or should tools be organised by risk class? Evaluate the tool layer.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | List execution package and line counts | __init__.py __pycache__ capabilities.py config.py container.py doctext.py domainstatus.py energy external.py geocode.py home htmltext.py knowledge listingsource |
| 2 | Bash | Read the top of the tool registry module | """Builtin tools (08-execution.md section 5.2), ported from v1. Each implements `contracts.protocols.Tool`. Scoped this build to the tools that don't depend on  |
| 3 | Bash | Read Tool protocol, ToolResult, ToolContext definitions | 2:section 6). Structural (`typing.Protocol`), so a backend or a test fake 11:from typing import Any, Awaitable, Callable, Mapping, Protocol, runtime_checkable 2 |
| 4 | Bash | List top-level definitions in tools.py | 109:def tool_root(config: Config, ctx: ToolContext \| None, path: str = "") -> Path: 126:class ReadFileTool: 169:def _split_line_range(raw: str) -> tuple[str, tu |
| 5 | Bash | Read builtin_tools registry function | def builtin_tools(config: Config, *, secrets=None) -> list: """`secrets` is the subsystem's scoped secret store. Only the account-backed tools use it, and they  |
| 6 | Bash | Read execution Config head and constructors | """Execution configuration (08-execution.md section 3.5) -- a working subset: the knobs the tools built this phase actually read. Shell, relaunch, hot_swap, and |
| 7 | Bash | Enumerate all registered builtin tools with metadata | count: 98 reversibility: Counter({'reversible': 51, 'read_only': 37, 'irreversible': 10}) read_only: Counter({False: 58, True: 40}) container run_container ro=F |
| 8 | Bash | List domain package files and sizes | simorgh/execution/energy: __init__.py __pycache__ api.py meters.py tools.py simorgh/execution/home: __init__.py __pycache__ cameras.py registry.py ring.py tools |
| 9 | Bash | Find dispatch, timeout, truncation and token checks in execution service | 139: secret = ctx.secrets.get("__hmac__") 141: raise RuntimeError("execution: no guardian_hmac secret in Context -- refusing to start") 201: # `wait_for` in `_o |
| 10 | Bash | Read the action dispatch path of execution service |  resolved: dict = {} for key, value in args.items(): # `blob:<sha256>` is the Ledger's ref shape (02 section 4.2). # Matched here by shape rather than by import |
| 11 | Bash | Read timeout_for and _store_rows in execution service | 84:def timeout_for(tool, constraints: dict, default_s: float) -> float: 85- """How long one call to `tool` may take: a constraint on the approval 86- wins, then |
| 12 | Bash | Read orchestration tools router policy (part 1) |  723 simorgh/orchestration/tools.py """ToolCallRouter (16 section 5): a `cognition.think` tool_call becomes an `action.proposed` payload. Guardian is the sole a |
| 13 | Bash | Read external toolsets adapter | """Open-source toolset adapters -- the creator, 2026-09-07: "sim should be able to seamlessly integrate and use tools from ... Pydantic AI Toolsets, Composio, L |
| 14 | Bash | Read MCP client adapter | """MCP (Model Context Protocol) client -- a human-configured, static list of external tool servers Execution can dispatch to, alongside its own builtin tools (0 |
| 15 | Bash | List data dir, ledger streams and masked config | total 3808 drwxr-xr-x@ 26 saeed staff 832 Sep 18 15:04 . drwxr-x---+ 100 saeed staff 3200 Sep 18 18:39 .. drwxr-xr-x@ 2 saeed staff 64 Sep 9 21:27 benchmark drw |
| 16 | Bash | Locate HA client and consumers of tool metadata | === HA client === (eval):1: no matches found: --include=*.py === reversibility consumers outside execution === (eval):1: no matches found: --include=*.py === re |
| 17 | Bash | Count test files referencing each tool name | tools with zero test files quoting the name: 0 [] ---bottom 30--- 1 cancel_task 1 find_package 1 memory_forget 1 overheard_note 1 remember_place 1 self_map 1 vo |
| 18 | Bash | Read orchestration tools router policy (part 2) |  "cam_watch": ("reversible", True), "ring_setup": ("reversible", True), "ring_list": ("read_only", True), "ring_snapshot": ("reversible", True), "ring_events":  |
| 19 | Bash | Read orchestration tools router policy (part 3) |  "an [account:folder:uid] reference exactly as MAIL_SEARCH printed it, to read that one " "message's body." ), "remind": ( "first line: when -- \"20m\", \"tomor |
| 20 | Bash | Inspect ledger layout and find action streams | action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl action%3A00085e844cff.jsonl action%3A0009062c07cc.jsonl action%3A000947307a9 |
| 21 | Bash | Locate HA client and reversibility consumers | === HA client === simorgh/contracts/home/policy.py simorgh/contracts/home/client.py simorgh/contracts/home/fakes.py === reversibility consumers outside executio |
| 22 | Bash | Diff tool-declared reversibility against orchestration policy table | registered tools missing from _TOOL_POLICY: [] policy entries with no registered tool: ['worktree_open', 'worktree_land', 'worktree_close', 'draft_candidate', ' |
| 23 | Bash | Read home tools head | """`home_find`, `home_state`, `home_describe`, `home_call`, `home_undo`. `home_call` is the one that matters, and its shape is set by two rules from the design: |
| 24 | Bash | Check side_effects usage and profile tool bindings | simorgh/execution/service.py:849: side_effects=list(result.side_effects), simorgh/execution/remote.py:218: side_effects=(f"run_remote:{_head(command)}",), simor |
| 25 | Bash | Inspect the shape of an action stream | == action%3A00058d0478bb.jsonl {"causation_id":null,"idempotency_key":null,"payload":{"proposal":{"action_id":"00058d0478bb","args":{"action":"offer","camera":" |
| 26 | Bash | Check whether cognition uses native function calling | simorgh/cognition/parser.py:148:_NATIVE_TOOL_TAG = re.compile(r"</?(?:tool_call\|tool_calls\|function_call\|arg_key\|arg_value\|parameter)>") === instruction block = |
| 27 | Bash | Read HA client and home policy | """A Home Assistant REST client, in the standard library. HA's REST API is a JSON API with a bearer token: `GET /api/states`, `POST /api/services/<domain>/<serv |
| 28 | Bash | Read Reolink cameras and Ring heads | """The cameras: a Reolink NVR and every camera on it, through `reolink_aio` (open source, what Home Assistant uses; optional, refused by name when absent). The  |
| 29 | Bash | Read Cast, Android TV and media tools heads | """Sim on the TV: Chromecast through `pychromecast` (open source, an optional dependency, refused by name when absent). cast_devices the Cast devices on this ne |
| 30 | Bash | Read capability probes and domain status | """Which of Sim's capabilities actually work right now. Half of the toolset added on 2026-09-09 stands on something outside this repository: Node and a bundled  |
| 31 | Bash | Find how Guardian consumes reversibility | simorgh/guardian/config.py:103: irreversible_requires_human: bool = True simorgh/guardian/config.py:104: reversible_auto_in_guarded: bool = True simorgh/guardia |
| 32 | Bash | List PIM connectors, energy sources and test coverage per domain | __init__.py __pycache__ caldav.py fakes.py imap.py === energy api === """Meters, tariffs and what they add up to.""" from __future__ import annotations from dat |
| 33 | Bash | Read shared marker argument tables | """How one line of text becomes a tool call's arguments. The model writes `KB_SEARCH: flood cover` and means `{"query": "flood cover"}`. A person types `tool kb |
| 34 | Bash | Count tool invocations per tool across all ledger action streams | action streams read: 26737 distinct tools ever proposed: 68 decisions: Counter({'approved': 26703, 'denied': 34}) proposed_by (top): [('interface:dash', 23560), |
| 35 | Bash | Find schema consumers, idempotency handling and the token verifier | === args_schema consumers === simorgh/contracts/protocols.py:200: args_schema: dict simorgh/contracts/toolargs.py:109: # command, args, ...), but its one `args_ |
| 36 | Bash | Read how the tool instruction block is built for the model | # `web_fetch` is enough on its own. **Second live-catch, same day**: a # name alone was NOT enough for `propose_mcp_server` -- its one argument # has real inter |
| 37 | Bash | Check result truncation, cross-domain imports and optional dependency sprawl | simorgh/orchestration/tools.py:276: "simorgh/foo.py:120-260. A result is cut at ~8000 chars, so read a " simorgh/orchestration/session.py:1591: # 8000 character |
| 38 | Bash | Check interface's direct action proposals and who publishes action.proposed |  async def _on_denied(message) -> None: if not done.done() and message.payload.get("action_id") == action_id: done.set_result(("denied", message.payload)) # Sub |
| 39 | Bash | Read the OverheardTool natural-language request parser | class OverheardTool: """Asking what the room said when it was not talking to Sim. This is the half that was missing. `voice/overheard.py` recorded every line an |
| 40 | Bash | Read security selfcheck, knowledge embedding and vision heads | """What Sim can find out about its own exposure, using nothing but this machine. Guardian audits the code Sim writes. Nothing audited what Sim *is*. Every check |
| 41 | Bash | See how connectors and probes are wired in the service | 55:from .capabilities import CAPABILITIES_STREAM, PROBES, connector_probe, degraded_detail, run_probes 58:def _probe_tools(name: str) -> tuple[str, ...]: 111: c |
| 42 | Bash | Read the direct tool.run calls in the execution service |  # -- skill acquisition as procedural memory (roadmap 4.7) -------------------- async def _autostart_ring_watch(self, *, delay_s: float = 20.0) -> bool: """Run  |
| 43 | Bash | Read ring_live tool and its dashboard callers | 691:class RingLiveTool(_RingTool): 692- """Ring live view for the dashboard. Ring's live video is WebRTC: the 693- browser on the TV negotiates a peer connectio |
| 44 | Bash | List never-proposed tools and calls versus lines per tool module | registered tools never proposed: 33 ['cam_ptz', 'cam_setup', 'camera_describe', 'console_tail', 'dash_key', 'energy_report', 'energy_status', 'energy_tariff', ' |
| 45 | Bash | Check whether Guardian trusts the proposer's reversibility label |  source="guardian", )) return # Claimed before the first await, so two deliveries racing each # other cannot both get through. Bounded, oldest first: an # unbou |
| 46 | Bash | Check how run_shell is enabled and count idempotency and blob entries | 18:from .shell import DEFAULT_SHELL_REFUSALS 110: # `run_shell` (execution/shell.py) is not bounded by this and 111: # cannot be: a shell writes wherever the us |
| 47 | Bash | Check relative workspace paths and ffmpeg process lifecycle in cameras | simorgh/execution/home/cameras.py:49:HLS_DIR = Path("workspace/cameras/hls") simorgh/execution/home/cameras.py:50:SNAPSHOT_DIR = Path("workspace/cameras") simor |
| 48 | Bash | Read execution README deferred list and PIM heads | isn't installed, a bad import path, or a constructor error skips that one tool with an `external_tool_load_failed` warning -- never a boot failure. `pip install |
| 49 | Bash | Read dash_view tool and how TV state is persisted | 949:class DashViewTool(_CastTool): 950- """Steer the glass dashboard on the TV. A Cast receiver never sees the 951- TV remote's keys, so the dashboard is turned |
| 50 | Bash | Check whether Guardian recomputes home policy and what label cam_siren carried | === guardian home policy === === cam_siren proposals from interface === cam_siren interface:71b8cc9e-4ff2-4a88-9876-f072e1bcc4c4 reversibility= reversible args= |
| 51 | Bash | Break down ring_live actions by kind and day, and idem entries by stream type | ring_live streams: 22849 bytes: 18579811 by action: Counter({'offer': 9318, 'close': 8301, 'keepalive': 5230}) by day: [('2026-09-12', 16), ('2026-09-13', 324), |
| 52 | Bash | Check vision's direct calls, description consumers and the tool.registered payload | === vision direct tool calls === 235: result = await tool.run({"camera": camera}, ctx=ctx) 466: tool = self._registry.get(tool_name) 475: result = await tool.ru |
| 53 | Bash | Check arg validation, the read-only sandbox exemption and BudgetRule | === arg validation in service === 171: "schema_ref": "", "provider": getattr(tool, "provider", "builtin")}, 451: "schema_ref": "", "provider": "mcp", 452: "mark |
| 54 | Bash | Survey timeouts, probe table and the refused string convention | === timeout_s declared on tools === simorgh/execution/media/cast.py:641: IDLE_POLL_S = 10.0 simorgh/execution/media/cast.py:643: WATCH_MAX_S = 4 * 3600.0 === ru |
| 55 | Bash | Total lines for never-used and rarely-used modules, and read restart handling | === LOC pim connectors, contracts/home === 1599 total 907 total === total execution LOC === 21590 total === zero-call modules total === 5523 total === <=6-call  |
| 56 | Bash | Trace dash to ring_live path and inventory third-party imports and binaries | === dash -> ring_live path === simorgh/interface/live_status.py:106: ("act", "ring_live"): "Opening a Ring live view", simorgh/interface/httpapi.py:476: async d |
| 57 | Bash | Confirm no native tool calling, Guardian subscriptions, per-tool timeouts and sim.sh cwd | === native tool params in providers === (none above = no native function calling) === guardian consumes === 97: consumes = ( 98- topics.ACTION_PROPOSED, 99- top |
| 58 | Bash | Read the cast watch loop and how watch tools background themselves |  generation = self._bump() try: await asyncio.to_thread(backend.play, device, self._media_url(path.name), content_type="video/mp4", title=title) except Exceptio |
| 59 | Bash | Check whether long-running tools are bounded below the 60s service timeout | === kb_sources scan bounds === 36:from .sources import scan_all, scan_source 84: "run KB_SOURCES: scan") 294: "or scan them now. Adding a source does not read a |
| 60 | Bash | List tools the dashboard page can trigger and which domains have connector probes | === page-triggered tools over HTTP === 3 cam_stream 1 cast_play 1 ring_live 3:389- # Guardian sees, the result read back (interface/dispatch.py). 6:392- from .d |
| 61 | Bash | Check scan bounds, per-tool timeout declarations, network scope use and non-action streams | === scan bounds in sources.py === 79:def walk_source(spec: SourceSpec, *, max_file_bytes: int = 100 * 1024 * 1024, 80: max_files: int = 100_000): 93: if seen >= |
| 62 | Bash | Confirm network scope is unused by Guardian and inspect timeout declarations | === network anywhere in guardian === simorgh/guardian/config.py:49: r"\bsocket\.\b": "opens raw network sockets (Directive 1, Directive 5)", simorgh/guardian/co |
| 63 | Bash | Confirm install_package runs in a thread under the 60s service bound |  return None def _install(self, manager: str, spec: str): command = ( [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", spec] if manager = |
| 64 | Bash | Check whether install runs in a thread | 201: hits, oversize = await asyncio.to_thread(self._lookup_detail, name, manager) 299: refusal = await asyncio.to_thread(self._vet, name, manager) 304: complete |

## Structured reply

**concern:** The tool layer: Execution's 98 registered tools (files/code/git, sandboxes, web, packages), the six domain packages (knowledge, pim, security, home, energy, media) plus cameras/Ring/Cast/Android TV, external toolsets (external.py), MCP (mcp.py), and the router policy in orchestration/tools.py.

**summary of what is actually there:** Every tool is a plain class satisfying the structural `Tool` protocol in simorgh/contracts/protocols.py:195-201 (name, description, read_only, reversibility in {read_only,reversible,irreversible}, args_schema, `async run(args, ctx) -> ToolResult`), and `ToolResult` (protocols.py:185-192) is ok/output/output_ref/error/side_effects/metadata with no error kind, cost, or idempotency field. `builtin_tools()` in simorgh/execution/tools.py:3059-3117 assembles 98 instances (measured by import): 26 in tools.py itself, 13 Cast/TV tools in media/cast.py, 11 Reolink tools in home/cameras.py, 8 Ring tools in home/ring.py, and 3-5 each for the HA-backed home/media/energy packages and for knowledge, pim, security. Dispatch is in simorgh/execution/service.py:751-860: on `action.approved` it re-fetches the args from the action's own ledger stream, re-verifies the HMAC token (execution/verifier.py), runs the tool under a 4-slot semaphore and `asyncio.wait_for(timeout_for(...))` (60s for 97 of 98 tools, service.py:84-99), blobs output over 4 KB, caps the preview at 64 KB, writes `metadata["rows"]` to results/<action_id>.json, and publishes action.result. The model never sees `description` or `args_schema`: cognition/service.py:67-93 shows the model only upper-cased tool NAMES plus hand-written hints, and it calls tools by writing `NAME: one line`; the argument contract is five hand-maintained tables (MARKER_ARG_KEY/NO_ARGS/SPLIT_FIRST_LINE/JSON_REST in contracts/toolargs.py, _MARKER_ARG_HINT and _TOOL_POLICY in orchestration/tools.py) that remap the one string onto each tool's real keys; no provider uses native function calling (grep of cognition/providers for tool_choice/"tools"/input_schema is empty). Reversibility is declared three times: on the tool class, in orchestration's `_TOOL_POLICY` (identical today, measured), and hard-coded as "reversible" by the interface for anything a person or the dashboard proposes (interface/dispatch.py:1336); Guardian builds its `ToolInfo` from the proposal's label alone (guardian/service.py:504,522-526) and does not subscribe to tool.registered (guardian/service.py:97-100) or import contracts/home/policy.py. Home Assistant (contracts/home/client.py, stdlib urllib) is the hub abstraction for lights/media/energy, but it is not configured on this machine (~/.simorgh/simorgh.toml lists no HOME_ASSISTANT_* secret) and the ledger shows 6 calls through it in nine days; cameras (reolink_aio + ffmpeg HLS), Ring (ring_doorbell), Cast (pychromecast), Android TV (androidtvremote2) and Music (osascript) are device-direct SDK wrappers and carry ~23,800 of the 26,737 recorded actions. External toolsets (external.py: LangChain/pydantic_ai/Composio/callable adapters behind one `input` string, default reversibility irreversible) and MCP (mcp.py: hand-rolled stdio JSON-RPC, `McpToolProxy`) are built and tested but nothing is configured in simorgh.toml and neither has a single ledger call. Execution also calls `tool.run()` directly, outside Guardian, for ring_watch/cam_watch/cast_show at boot and tv_charts on dashboard state (service.py:484,517,543,561), and vision.py does the same for snapshots and camera_describe on every camera event (vision.py:235,475,515). Optional dependencies are reached lazily (13 third-party libraries and 9 binaries found by grep) and refused by name; boot probes (execution/capabilities.py:154-158) cover node/puppeteer/bandit/homeharvest/docker plus one connector per domain (domainstatus.py), but none of the five device SDKs or ffmpeg.

### strengths

- End-to-end approval verification at the executor, not only the approver: execution/verifier.py:36-57 recomputes args_sha256 from the ledger's own `received` event of the action stream and re-checks the HMAC, so a forged action.approved on the bus cannot run a tool (service.py:751-770).
- One protocol for everything: MCP tools (mcp.py McpToolProxy), LangChain/pydantic_ai/Composio callables (external.py ExternalTool) and Sim-written skills are all wrapped as ordinary `Tool`s and go through the same action.proposed path; the frameworks' own agent runners are deliberately not used (external.py module docstring), which keeps the Guardian invariant intact for third-party code.
- Fail-safe defaults for the unknown: `_TOOL_POLICY.get(tool, ("irreversible", False))` in orchestration/tools.py, `ExternalToolSpec.reversibility = "irreversible"` (external.py:63-84, with the live-caught os.remove incident recorded), and MCP tools are irreversible unless a human names them in `read_only_tools` (mcp.py:218-221).
- Per-call risk for the house is a pure function in contracts (contracts/home/policy.py classify_call: lock.unlock, alarm disarm, garage, climate outside 10-32C, anything while armed -> human) - the right shape for a tool whose danger depends on its arguments, and orchestration/tools.py:701-708 applies it to home_call.
- Honest 'not configured' vs 'configured but broken' reporting: every domain gets a Connector probe (domainstatus.py:49-215) and every HA tool refuses with the exact secret names to set (home/tools.py:75-83); knowledge's kb_status says when search was lexical-only (knowledge/embed.py docstring).
- Read-only by construction where it matters: the IMAP connector has no write path at all (pim/connectors/imap.py docstring 'Nothing here writes'), so mail cannot be sent or deleted whatever a policy says.
- Data tools hand data back, not summaries: `_store_rows` (service.py:939-967) writes `metadata["rows"]` to results/<action_id>.json under a readable-but-not-writable root and names the file in the output; `read_file path:START-END` (tools.py:169-185) makes files larger than the 8 KB model window reachable.
- Blocking work is moved off the event loop in the places that were bitten (ReadFileTool tools.py:133-152 after the zip-bomb freeze; install/scan via asyncio.to_thread), and every subprocess passes stdin=DEVNULL for a documented reason (tools.py module docstring).

### findings

##### 1. Guardian enforces the reversibility label the proposer chose, and the interface labels everything 'reversible'

- **kind:** right-design-undermined
- **severity:** high
- **claim:** The tool layer's only safety export, the per-tool reversibility class, never reaches Guardian: Guardian builds ToolInfo from the proposal's own `reversibility` field, does not subscribe to tool.registered, and does not call contracts/home/policy.py, while interface/dispatch.py stamps every human- or dashboard-proposed call as 'reversible'.
- **evidence:**
  - simorgh/guardian/service.py:522-526: `tool=ToolInfo(name=proposal.tool, read_only=proposal.reversibility == "read_only", reversibility=proposal.reversibility)` - the declared class on the Tool object is never consulted
  - simorgh/guardian/service.py:97-100: consumes = (ACTION_PROPOSED, GUARDIAN_REVIEW, SYSTEM_STATE_CHANGED, ...) - no TOOL_REGISTERED; `grep -rn "classify_call\|contracts.home" simorgh/guardian/*.py` -> no output
  - simorgh/interface/dispatch.py:1336: `"reversibility": "reversible"` with the comment 'Guardian recomputes the real class itself and never trusts a proposer's label' - which is not what guardian/service.py does
  - simorgh/orchestration/tools.py (home_call comment): 'Guardian recomputes the same answer from the same pure function rather than trusting this' - also untrue
  - Ledger, 5 action streams: `cam_siren interface:71b8cc9e-... reversibility= reversible args= {'camera': 'Pool', 'seconds': 1}` etc., while simorgh/execution/home/cameras.py declares cam_siren `reversibility = "irreversible"` (measured: 10 tools declare irreversible)
  - simorgh/interface/httpapi.py:389-402: the dashboard's `_run_for_page` goes through the same `_run_tool` and therefore the same hard-coded label
- **why it matters:** The three-tier taxonomy is maintained in three places across 98 tools, yet the component that acts on it sees a value the least trusted party supplies. A `tool home_call lock.unlock` typed at the CLI, or any tool the dashboard is later wired to, arrives as 'reversible' and is auto-allowed in guarded posture; the `human` class for locks and alarms in contracts/home/policy.py holds only when Orchestration is the proposer. Two docstrings assert the opposite of the code, so the next person will trust the label too.
- **recommendation:** Have Execution hand Guardian the declared table once (Guardian subscribes to tool.registered, or Kernel passes the registry's {name: reversibility} at boot) and compute `effective = strongest(declared[tool], proposal.reversibility, classify_call(...) for home_call)` in guardian/service.py before building ToolInfo. Then delete the label from interface/dispatch.py and make `_TOOL_POLICY`'s reversibility column a test that asserts equality with the declared value rather than a second source. Half a day; one new test that proposes cam_siren from 'interface:x' with 'reversible' and expects the irreversible path.
- **confidence:** 0.95

##### 2. The model never sees description or args_schema; the real argument contract is five hand-maintained marker tables

- **kind:** wrong-design
- **severity:** high
- **claim:** Tools carry a JSON schema and a description that no model-facing code reads: the model gets upper-cased names plus prose hints and answers with `NAME: one line`, and every tool's arguments are reconstructed from hand tables in two other subsystems, which is the root of the recurring 'this tool had never once worked from the model's side' bug.
- **evidence:**
  - simorgh/cognition/service.py:67-93 `_tool_instruction_block`: `names = ", ".join(sorted(tool.upper() for tool in tools))` + `tool_hints` only; comment at :58 says descriptions 'would cross the subsystem boundary'
  - `grep -rn "tool_choice\|\"tools\"\|tools=\|functions=\|input_schema" simorgh/cognition/providers/*.py` -> no output (no native function calling on any provider)
  - `grep -rn args_schema simorgh` consumers: only simorgh/execution/service.py:452,456 `mcp_single_arg_key(tool.args_schema)` for MCP tools
  - simorgh/contracts/toolargs.py: MARKER_ARG_KEY (~80 rows), MARKER_NO_ARGS, MARKER_SPLIT_FIRST_LINE, MARKER_JSON_REST; simorgh/orchestration/tools.py: _MARKER_ARG_HINT (~60 prose entries) and _TOOL_POLICY
  - The tables' own comments record the failures: toolargs.py run_shell ('had never once run from the model's side; two observers found it independently'), git_discard ('had never once worked'); orchestration/tools.py browse_page and run_container ('had never once worked from the model's side'), propose_mcp_server, MCP tools ('could never actually be called from a marker reply')
  - Measured: dash_view has 10 schema properties and ring_live 4; through the marker layer only the first line plus an optional JSON tail is expressible
- **why it matters:** Adding one tool needs edits in execution (class), contracts (key table), orchestration (policy + hint) and cognition (nothing, but the hint text is prompt engineering). The code's history shows at least six tools shipped unreachable, and the CHAT profile pays prompt tokens for names whose usage the model must guess. The schemas and 170-char-average descriptions are 98 pieces of dead weight that look like a contract.
- **recommendation:** Make args_schema the single source. (1) A pure function `marker_shape(schema)` in contracts/toolargs.py: one required string property -> its key; a schema tagged `"x-marker": {"first": "path", "rest": "code"|"json"}` -> split/json-rest; no properties -> no-args. (2) Have Execution put `description`, the schema, and the derived marker shape in tool.registered (it already sends name/reversibility/marker_arg_key), and let Orchestration build hints from `description` + property descriptions instead of `_MARKER_ARG_HINT`. (3) One boot-time test: every registered tool has a routable shape. (4) On the Claude and Together providers pass the schemas as native tools and parse tool_use blocks; keep the marker path as the Ollama floor. Steps 1-3 are a day and delete two tables; step 4 is optional but is what makes multi-argument tools (dash_view, ring_live, home_call) usable.
- **confidence:** 0.9

##### 3. Execution and the camera watcher run tools directly, outside Guardian and the action ledger

- **kind:** right-design-undermined
- **severity:** high
- **claim:** Seven call sites invoke `tool.run()` with synthetic action ids and no proposal, approval, token or `action:*` stream, so casting to the TV at boot, starting ffmpeg transcodes, polling Ring's cloud, taking snapshots and calling a vision model on every motion event are effects Guardian never sees and the ledger never records as actions.
- **evidence:**
  - simorgh/execution/service.py:484 `result = await tool.run({"on": True}, ctx=ctx)` (ring_watch, action_id="ring-watch-boot"); :517 (cam_watch, "cam-watch-boot"); :543 (cast_show, "tv-show-boot"); :561 (tv_charts, f"charts-{message.id}" on ui.dash.state)
  - simorgh/execution/vision.py:235, :475, :515 `await tool.run(...)` for cam_snapshot/ring_snapshot/camera_describe on world.camera.event
  - Ledger measured over 26,737 action streams: camera_describe proposed 0 times, cam_watch 1, ring_watch 5, cast_show 114 - yet the watch and describe paths run on every boot and event (vision.py module docstring: 'Sim takes a couple of stills ... asks a model that can actually see them')
  - Design statement being undermined: simorgh/execution/home/cameras.py docstring 'Every call is a tool call, so Guardian sees it -- the siren above all'; mcp.py docstring 'Guardian sees every call'
- **why it matters:** The two invariants the whole architecture is sold on - one approver, one append-only record of effects - are false for the subsystem that carries 99% of real use (cameras/TV). A vision call per motion event is a paid-model spend with no BudgetRule and no action stream; a boot-time cast to the family TV is exactly the kind of unattended effect the posture/ModeRule exist for. Anyone auditing the ledger will conclude the cameras were barely used.
- **recommendation:** Add one helper in execution/service.py, `_propose_internal(tool, args, rationale)`, that publishes action.proposed with proposed_by="execution:boot"/"execution:vision" and awaits the result (interface/dispatch.py `_run_tool` already implements this pattern; reuse it via a contracts helper). Route the seven sites through it. If a synchronous boot path cannot wait on Guardian, at least append a `started` event with the tool name to `execution:inflight` so the record is complete. Two hours.
- **confidence:** 0.9

##### 4. WebRTC signalling is modelled as agent actions: ring_live is 85% of everything Guardian has ever decided

- **kind:** wrong-design
- **severity:** high
- **claim:** Each dashboard offer/keepalive/close for a Ring live view is a full action (bus -> Guardian -> HMAC -> Execution -> verify -> three ledger events -> inflight -> tool.invoked), producing 22,849 action streams in five days, all approved, and the interface already has to special-case the tool to hide it from the activity feed.
- **evidence:**
  - Ledger measured: 22,849 of 26,737 action streams are ring_live (offer 9,318 / close 8,301 / keepalive 5,230), 18,579,811 bytes; by day: 2026-09-14 = 12,896, 09-16 = 5,052, 09-15 = 4,301; decisions for ring_live: approved 22,846, denied 3
  - simorgh/interface/httpapi.py:476-487: `POST /api/dash/ring/live` -> `_run_for_page("ring_live", args, 30.0)` with rate=(120, 60.0); :815 `_ACTIVITY_SILENT_TOOLS = frozenset({"ring_live"})`
  - simorgh/execution/home/ring.py:691-734 RingLiveTool: 'Sim carries only the signalling ... Each step is a tool call, so Guardian sees who is opening a live view'
  - simorgh/execution/security/selfcheck.py docstring rates 'A ledger of hundreds of thousands of files' as a medium finding on this project's own history; ~/.simorgh/ledger/streams holds 118,215 files today
- **why it matters:** Approval is meaningful once per session, not per keepalive; at packet granularity Guardian is a 100%-yes rubber stamp that costs a ledger file, an HMAC, and a bus round-trip each time. It is the single largest writer to the ledger and the reason cam_stream (721 calls) is the second. On one laptop this is the difference between a ledger you can back up and one you cannot.
- **recommendation:** One approved action (`ring_live open <camera>`) returns a session grant with a TTL; the page then posts offer/keepalive/close to an httpapi route that talks to the Ring client directly under that grant (the Ring client object is already reachable from the tool's `_cloud()`); `close` or TTL expiry ends it and appends one `ended` event. Same shape for cam_stream. Half a day, and it deletes 85% of future action streams.
- **confidence:** 0.9

##### 5. The reversibility taxonomy has had no runtime effect: 0 escalations in 26,737 decisions

- **kind:** right-design-undermined
- **severity:** medium
- **claim:** Across every recorded action the decision kinds are approved 26,703 and denied 34 with no escalation, so the three-tier label the tool layer maintains in three places has changed nothing for nine days; its one consumer (ReversibilityRule) is switched off by the deployment's auto-approve default and `[execution] shell = True` is the code default.
- **evidence:**
  - Ledger measured: `decisions: Counter({'approved': 26703, 'denied': 34})`; irreversible tools approved: run_shell 561, run_script 45, install_package 17, sim_command 11, cam_siren 5
  - simorgh/guardian/rules.py:720-739 ReversibilityRule: escalates only when `ctx.config.irreversible_requires_human`; simorgh/guardian/config.py:157 flips it from SIMORGH_GUARDIAN_AUTO_APPROVE
  - simorgh/execution/config.py:193 `shell: bool = True` ('the creator: give sim file system write access and shell access'); run_shell is the most-used effecting tool (570 calls) and is declared irreversible
  - contracts/home/policy.py docstring: 'sim.sh auto-approves irreversible actions by default. For the house that default is wrong, and `human` here is meant to survive it' - but home_call has been proposed once, and Guardian never applies the policy (see finding 1)
- **why it matters:** This is the creator's chosen posture, so the gate itself is not the bug; the waste is that the label is treated as the tool layer's main safety contract while its only effect is nil. Meanwhile the things the label could drive for free - recording a `before` state so reversible tools are actually undoable, verification rigor (verification/rigor.py already reads it), a spoken confirmation for `human`-class house calls even under auto-approve - are not wired to it.
- **recommendation:** Keep auto-approve, but give the label consumers that run in that posture: (a) ReversibilityRule escalates `human`-class house calls and `notify` regardless of the boolean (a tiny always-human set, already sketched in guardian config's `always_human`); (b) for reversible tools, Execution captures `before` in metadata automatically (home_undo already expects it) so undo is uniform; (c) drop the pretence elsewhere: if `shell = True` is the default, say so in the tool's description hint. One afternoon.
- **confidence:** 0.85

##### 6. 26% of the tool layer (5,523 lines) has never been called; three of six domains have zero use and cannot work today

- **kind:** over-engineering
- **severity:** medium
- **claim:** 33 of the 98 registered tools have never been proposed in the ledger; knowledge (1,995 LOC), security (1,085), energy (686), real-estate listings (535), notify (394), external toolsets (279), MCP (232), remote (225) and geocode (92) total 5,523 of 21,590 lines with zero calls, and a further 3,899 lines (pim, HA home/media, container) carry 14 calls between them - while every one of these tools is still offered to the model and costs a policy row, a marker row and a hint.
- **evidence:**
  - Measured from ~/.simorgh/ledger (26,737 action streams, 2026-09-09..09-17): registered tools never proposed = 33: cam_ptz, cam_setup, camera_describe, console_tail, dash_key, energy_report, energy_status, energy_tariff, geocode, home_state, home_undo, kb_ask, kb_open, kb_search, kb_sources, kb_status, mail_read, media_control, media_play, memory_forget, notify, overheard, overheard_note, propose_mcp_server, remember_place, ring_light, ring_siren, search_listings, sec_accept, sec_findings, sec_posture, sec_self, sec_show
  - Calls vs lines per module (measured): knowledge/tools.py 0/520 (package 1,995), security/tools.py 0/410 (package 1,085), energy/tools.py 0/341 (package 686), realestate.py 0/318 + listingsources.py 217, notify.py 0/394, geocode.py 0/92, home/tools.py 5/409, pim/tools.py 6/386 (+907 connectors), media/tools.py 1/288, container.py 2/222; `wc -l` of the zero-call set = 5,523; of the <=6-call set = 3,899; `find simorgh/execution -name '*.py' | xargs wc -l` = 21,590
  - ~/.simorgh/simorgh.toml (masked): `[execution] secrets = ["vault:*", "SIM_API_TOKEN", "REOLINK_*", "RING_*"]`, no HOME_ASSISTANT_URL/TOKEN, no `[[execution.external_tools]]`, no `mcp_servers` - so home_*, media_*, energy_* refuse with 'Home Assistant is not configured' (home/tools.py:75-83) and external/MCP register nothing
  - simorgh/orchestration/profiles.py:19-69 CHAT still lists kb_*, cal_*, mail_*, sec_*, home_*, energy_*, media_* for every chat turn; tests/simorgh/execution/energy = 326 lines
- **why it matters:** For a one-laptop, one-family system this is a large speculative surface: it is prompt tokens on every chat turn, three tables to keep in sync, probes to run, and a place for the 'unconnected wire' bug to live unnoticed because nothing exercises it. The work itself is not wrong - HA and a document index are plausible next steps - but registering it unconditionally makes the offered tool list lie about what can happen today.
- **recommendation:** Do not delete; gate registration on configuration. In builtin_tools(), register a domain's tools only when its Connector probe says 'configured' (domainstatus.py already computes this), otherwise register a single `<domain>_setup` tool whose output is the exact config to add. That shrinks the CHAT list from ~70 names to the ~30 that can run, and lets the policy/marker tables be asserted against the live registry. If external.py/mcp.py stay unused for another month, move them to a `contrib/` package outside the boundary test rather than carrying them in execution/.
- **confidence:** 0.85

##### 7. One 60-second service timeout for 97 of 98 tools, while the cancelled work keeps running in a thread

- **kind:** bug
- **severity:** medium
- **claim:** `timeout_for` falls back to `default_timeout_s = 60` for every tool except run_tests, so install_package (own subprocess budget 300s) and kb_sources scan (up to 100,000 files) are reported as 'timeout' at 60s while their `asyncio.to_thread` work continues invisibly, inviting a retry that runs a second pip install or a second sqlite writer.
- **evidence:**
  - simorgh/execution/service.py:84-99 `timeout_for`: constraints.timeout_s ('Nothing in Guardian or Orchestration sets `constraints.timeout_s` (checked 2026-09-10)'), then `getattr(tool, "timeout_s", None)`, else default; `grep -rn "self.timeout_s\|\.timeout_s = " simorgh/execution` -> none; the only declaration is the RunTestsTool property at tools.py:1229-1240, whose docstring records this exact bug fixed for itself only
  - simorgh/execution/config.py:54 `default_timeout_s: float = 60.0` vs :296 `package_install_timeout_s: float = 300.0`
  - simorgh/execution/packages.py:304 `completed = await asyncio.to_thread(self._install, manager, spec)`; :358-368 `_install` runs pip/npm with timeout=300
  - simorgh/execution/knowledge/tools.py:411 `report = await asyncio.to_thread(_work)` where `_work` calls scan_source with `max_files: int = 100_000` (knowledge/sources.py:79-80) and no time bound
  - service.py:801-806: on `asyncio.TimeoutError` the service publishes error="timeout" and returns; a thread started by to_thread cannot be cancelled and no event records that it is still running
- **why it matters:** A tool that says 'timeout' while still installing a package is the 'succeeds while saying nothing true' failure the project's own honesty rules name, and the model's natural next move (retry) doubles the effect. The protocol has no place to declare cost, so every new slow tool repeats this until someone adds a property by hand.
- **recommendation:** Make `timeout_s` part of the Tool protocol (contracts/protocols.py) with a class default per family (reads 15s, network 30s, subprocess/scan 330s), set it in the six slow tools (install_package, kb_sources, run_container, sec_self, cam_recordings, ring_setup), and on cancellation of a to_thread-backed tool publish error="timeout; still running in the background" plus a `finished` inflight event when the thread ends. Two hours; add a test that a tool with timeout_s=0.1 wrapping a 1s thread reports the background note.
- **confidence:** 0.75

##### 8. Device integrations are five parallel SDK wrappers sharing state through workspace/ files and a private HA base class

- **kind:** wrong-design
- **severity:** medium
- **claim:** The hub abstraction (Home Assistant) exists for the parts of the house that are not used, while the parts that carry the load (Reolink, Ring, Cast, Android TV, Music) are device-direct with no shared base: each has its own `available()`, secrets lookup, name resolution, watch-task lifecycle and workspace/ cache, cameras.py resolves Ring names by reading Ring's JSON from a CWD-relative path, and media/energy reuse HA's private `_HomeTool`.
- **evidence:**
  - Measured calls: ring.py 22,879, cameras.py 790, cast.py 294, musicapp.py 14 vs HA-backed home/tools.py 5, media/tools.py 1, energy/tools.py 0
  - simorgh/execution/home/cameras.py:66-78: `_RING_LIST = Path("workspace/cameras/ring/cameras.json")` and `_RING_LIST.read_text(...)` at :74 with no `root /` prefix, whereas every other path in the file is joined (`root / SNAPSHOT_DIR` :454, `root / HLS_DIR` :581) and ring.py writes `root / RING_DIR` (:402); it works only because sim.sh:13 does `cd "$REPO_ROOT"`
  - simorgh/execution/media/tools.py:23-24 `from ..home.registry import Ambiguous, NotFound` / `from ..home.tools import _HomeTool`; simorgh/execution/energy/tools.py:26 same private import
  - Separate `available()` and secrets keys per device: cameras.py:56-61 (reolink_aio, REOLINK_*), ring.py:47,60 (ring_doorbell, RING_*), cast.py:40-45 (pychromecast), androidtv.py (androidtvremote2, ~/.simorgh/tv/), musicapp.py (osascript); separate watch loops cameras.py:820, ring.py:777
  - simorgh/execution/home/tools.py:79-81 tells the model 'Sim does not talk to devices directly; it talks to Home Assistant' - the opposite of what 99% of recorded calls do
- **why it matters:** The stated abstraction and the practised one disagree, so every new device (the next camera brand, a thermostat) will be a sixth copy of the same 800-line shape, and cross-device features (the dashboard's camera grid mixing Reolink and Ring) are already coupling modules through files instead of an interface. The CWD-relative read is a small latent bug of the same origin.
- **recommendation:** Accept device-direct as the architecture for this house and name it: an `execution/devices/` base with `Backend.available()`, secrets binding, a shared `Device` registry (name -> backend, channel) that cameras/Ring/Cast all register into, and one watch-task holder. Move `_HomeTool` to a public `HomeBackedTool` and keep HA as one backend among the others. Fix cameras.py:74 to `tool_root(...) / _RING_LIST`. The registry alone removes the JSON-file coupling; a day's refactor with the existing fake-backed tests.
- **confidence:** 0.8

##### 9. Tool errors are a string convention with no kind, so callers cannot tell 'unconfigured' from 'transient' from 'refused'

- **kind:** wrong-design
- **severity:** low
- **claim:** ToolResult has ok/error only; 186 sites construct `error="refused: ..."` and ReadFileTool decides `ok` by sniffing `content.startswith("[refused:")`, so the session, the retry logic and the model all classify failures by reading prose.
- **evidence:**
  - simorgh/contracts/protocols.py:185-192 ToolResult fields: ok, output, output_ref, error, side_effects, metadata - no kind
  - `grep -rn 'error=f"refused\|error="refused' simorgh/execution | wc -l` -> 186; simorgh/execution/tools.py:163 `ok = not content.startswith("[refused:")`
  - simorgh/execution/home/tools.py:75-83 'refused: Home Assistant is not configured' and cameras.py:56-58 'needs reolink-aio' are the same `ok=False` as a network failure
- **why it matters:** A model that sees 'refused: not configured' three times in a turn has no structured signal to stop; the session cannot auto-retry a transient without also retrying a policy refusal; the ledger cannot be queried for 'how often does tool X fail for lack of setup'.
- **recommendation:** Add `kind: str = ""` to ToolResult with five values (refused, unconfigured, bad_args, transient, failed) and a helper `refused(msg)`/`unconfigured(msg)` in contracts; migrate call sites opportunistically (the `refused:` prefix can be derived from kind during the transition). Then orchestration/session.py drops a tool from the offered list for the rest of the turn after `unconfigured`, and retries once on `transient`.
- **confidence:** 0.8

##### 10. Decorative metadata: read_only contradicts reversibility on the sandboxes, and the policy table's network flag is never read

- **kind:** bug
- **severity:** low
- **claim:** run_python_sandboxed, run_js_sandboxed and run_tests declare `read_only=True` with `reversibility="reversible"`, which Guardian's ModeRule had to patch around with a code-argument scan, and the `(reversibility, network)` tuple's second element becomes `scope.network` that no Guardian rule consults.
- **evidence:**
  - Measured by import: `read_only flag vs reversibility label inconsistent: [('run_python_sandboxed', True, 'reversible'), ('run_js_sandboxed', True, 'reversible'), ('run_tests', True, 'reversible')]`
  - simorgh/guardian/rules.py:286-300: '`run_python_sandboxed` is declared `read_only=True` and runs an arbitrary subprocess with no chroot; an observer proved this exact early return made today's code-payload scan a COMPLETE no-op' -> special-cased via `_CODE_ARG_KEYS`
  - simorgh/orchestration/tools.py:715 `"scope": {"paths": paths, "network": network, ...}`; `grep -n network simorgh/guardian/rules.py` -> no output (guardian/config.py mentions network only in denylist regexes)
- **why it matters:** Two booleans that disagree invite exactly the rule-by-rule patching already visible in rules.py; a flag that is computed, transported and stored on every action but never read is the 'unconnected wire' in miniature.
- **recommendation:** Delete `read_only` from the protocol and derive it (`reversibility == "read_only"`), which also removes the sandbox contradiction; either make ScopeRule deny `scope.network` in `locked` posture or drop the column from `_TOOL_POLICY`. Thirty minutes plus the boundary test.
- **confidence:** 0.9

##### 11. Boot probes cover the libraries that are not used and skip the device SDKs and ffmpeg that carry 99% of calls

- **kind:** missing
- **severity:** low
- **claim:** The capability floor is honest at boot (stdlib-only import, lazy find_spec guards), but proactive probing covers node/puppeteer/bandit/homeharvest/docker plus HA-style domain connectors, while reolink_aio, ring_doorbell, pychromecast, androidtvremote2, ffmpeg and osascript - the dependencies behind ~23,800 recorded calls - are only discovered by a refusal at call time.
- **evidence:**
  - simorgh/execution/capabilities.py:154-158 PROBES = node, puppeteer, bandit, homeharvest, docker; simorgh/execution/domainstatus.py:211-215 connectors = knowledge, home, energy, media, security (pim per account)
  - Lazy third-party imports found by grep in simorgh/execution: androidtvremote2 apprise docx fitz homeharvest openpyxl pdfminer pychromecast pypdf pytesseract ring_doorbell sentence_transformers zeroconf; binaries via shutil.which: docker(3) npm(2) node(2) git(2) tesseract rg osascript lsof ffmpeg
  - simorgh/execution/home/cameras.py:56-61 and ring.py:60 `available()` are called per tool run, not registered as probes; requirements.txt lists none of the device libraries
- **why it matters:** The 'refused by name' floor is a good pattern, but the status screen and the prompt's capability note (capabilities.py docstring: 'written into the prompt, so the model does not spend three of its steps discovering') only know about the rarely-used half. After a Python upgrade breaks reolink_aio, the first symptom is a refusal in the middle of a spoken request.
- **recommendation:** Add one `Probe` per device backend using the existing `available()` functions (five lines each) and one for ffmpeg, all cost='free'; list the device libraries in requirements.txt under an `[house]` comment block so a fresh install of this particular house is reproducible.
- **confidence:** 0.7


### measurements

- Registered tools by import of builtin_tools(Config()): count 98; reversibility Counter({'reversible': 51, 'read_only': 37, 'irreversible': 10}); read_only Counter({False: 58, True: 40})
- Tool-declared reversibility vs orchestration _TOOL_POLICY: mismatches [] ; policy entries with no registered tool: ['worktree_open', 'worktree_land', 'worktree_close', 'draft_candidate', 'run_remote', 'mcp_ddg_search_ddg_search', 'mcp_ddg_search_ddg_get_answer']
- read_only flag vs reversibility label inconsistent: [('run_python_sandboxed', True, 'reversible'), ('run_js_sandboxed', True, 'reversible'), ('run_tests', True, 'reversible')]
- ~/.simorgh/ledger/streams: 118,215 files; action streams read: 26,737; distinct tools ever proposed: 68 (65 registered + 3 worktree_*); decisions: Counter({'approved': 26703, 'denied': 34}); proposed_by top: interface:dash 23,560, orchestration 2,979, verification 18
- ring_live streams: 22,849, bytes 18,579,811; by action Counter({'offer': 9318, 'close': 8301, 'keepalive': 5230}); by day 09-12:16, 09-13:324, 09-14:12,896, 09-15:4,301, 09-16:5,052, 09-17:260
- Most-used tools: ring_live 22,849; cam_stream 721; run_shell 570; read_file 473; search_code 431; web_fetch 291; web_search 207; run_tests 129; cast_show 114; replace_in_file 96 | HA-backed: home_describe 2, home_find 2, home_call 1, media_now 1, home_state 0, home_undo 0, media_control 0, media_play 0, energy_* 0 | kb_* 0, sec_* 0, notify 0, search_listings 0, geocode 0, propose_mcp_server 0
- Registered tools never proposed: 33 (list in finding 6)
- Lines: `find simorgh/execution -name '*.py' | xargs wc -l` = 21,590; zero-call modules (realestate, listingsources, geocode, notify, knowledge/*, security/*, energy/*, external, mcp, remote) = 5,523; <=6-call modules (pim/* incl. connectors, home/tools, home/registry, media/tools, container, contracts/home/*) = 3,899
- Calls vs LOC per module: ring.py 22,879/862; cameras.py 790/886; tools.py 1,757/3,117; shell.py 570/281; cast.py 294/1,339; websearch.py 207/377; script.py 56/143; render.py 31/503; packages.py 19/394; musicapp.py 14/289; pim/tools.py 6/386; home/tools.py 5/409; container.py 2/222; media/tools.py 1/288; vision.py 0/561; energy/tools.py 0/341; security/tools.py 0/410; knowledge/tools.py 0/520; notify.py 0/394; realestate.py 0/318; geocode.py 0/92
- Tests: no registered tool name is absent from tests (0 with zero test files); bottom of the distribution: cancel_task, find_package, memory_forget, overheard_note, remember_place, self_map, voice_setting each quoted in 1 test file; top: read_file 43, apply_source_patch 34, git_commit 26; tests/simorgh/execution/{home,media,pim,security,energy,knowledge} = 1359/1170/828/601/326/870 lines
- ToolResult constructions in simorgh/execution: 534; with side_effects: 24; `error="refused: ..."` sites: 186
- args_schema consumers outside tool definitions: simorgh/execution/service.py:452,456 (mcp_single_arg_key) only; description consumers model-side: none (cognition/service.py:67-93 sends names + hints)
- grep simorgh/cognition/providers for tool_choice|"tools"|tools=|functions=|input_schema: no output
- grep simorgh/guardian for classify_call|contracts.home: no output; grep simorgh/guardian/rules.py for network: no output; guardian consumes = ACTION_PROPOSED, GUARDIAN_REVIEW, SYSTEM_STATE_CHANGED (no TOOL_REGISTERED)
- Config: default_timeout_s 60.0; sandbox_timeout_s 10.0; web_fetch_timeout_s 10.0; package_install_timeout_s 300.0; home_timeout_s 10.0; shell = True; only RunTestsTool declares timeout_s (tools.py:1229-1240)
- ~/.simorgh/simorgh.toml [execution]: secrets = [vault:*, SIM_API_TOKEN, REOLINK_HOST/USERNAME/PASSWORD, RING_TOKEN/USERNAME], cast_device = "Family Room TV"; no HOME_ASSISTANT_*, no external_tools, no mcp_servers
- Third-party imports reached lazily in simorgh/execution: androidtvremote2 apprise docx fitz homeharvest openpyxl pdfminer.high_level pychromecast pypdf pytesseract ring_doorbell sentence_transformers zeroconf (13); binaries via shutil.which: docker 3, npm 2, node 2, git 2, tesseract 1, rg 1, osascript 1, lsof 1, ffmpeg 1; boot PROBES: node, puppeteer, bandit, homeharvest, docker + domain connectors knowledge/home/energy/media/security
- Ledger sizes: streams 696M, blobs 325M (256 files), idem 355M (90,755 entries: trace 88,356, task 2,393); execution:tools.jsonl = 20,110 registration lines

