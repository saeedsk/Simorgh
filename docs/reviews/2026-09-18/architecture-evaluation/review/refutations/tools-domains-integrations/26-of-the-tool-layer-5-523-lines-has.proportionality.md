# refute:proportionality:26% of the tool layer (5,523 lines) has

*Workflow: review · Phase: Refute · Agent id: `a06f724a9a9369f94` · Tool calls: 12*

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
    "title": "26% of the tool layer (5,523 lines) has never been called; three of six domains have zero use and cannot work today",
    "kind": "over-engineering",
    "severity": "medium",
    "claim": "33 of the 98 registered tools have never been proposed in the ledger; knowledge (1,995 LOC), security (1,085), energy (686), real-estate listings (535), notify (394), external toolsets (279), MCP (232), remote (225) and geocode (92) total 5,523 of 21,590 lines with zero calls, and a further 3,899 lines (pim, HA home/media, container) carry 14 calls between them - while every one of these tools is still offered to the model and costs a policy row, a marker row and a hint.",
    "evidence": [
      "Measured from ~/.simorgh/ledger (26,737 action streams, 2026-09-09..09-17): registered tools never proposed = 33: cam_ptz, cam_setup, camera_describe, console_tail, dash_key, energy_report, energy_status, energy_tariff, geocode, home_state, home_undo, kb_ask, kb_open, kb_search, kb_sources, kb_status, mail_read, media_control, media_play, memory_forget, notify, overheard, overheard_note, propose_mcp_server, remember_place, ring_light, ring_siren, search_listings, sec_accept, sec_findings, sec_posture, sec_self, sec_show",
      "Calls vs lines per module (measured): knowledge/tools.py 0/520 (package 1,995), security/tools.py 0/410 (package 1,085), energy/tools.py 0/341 (package 686), realestate.py 0/318 + listingsources.py 217, notify.py 0/394, geocode.py 0/92, home/tools.py 5/409, pim/tools.py 6/386 (+907 connectors), media/tools.py 1/288, container.py 2/222; `wc -l` of the zero-call set = 5,523; of the <=6-call set = 3,899; `find simorgh/execution -name '*.py' | xargs wc -l` = 21,590",
      "~/.simorgh/simorgh.toml (masked): `[execution] secrets = [\"vault:*\", \"SIM_API_TOKEN\", \"REOLINK_*\", \"RING_*\"]`, no HOME_ASSISTANT_URL/TOKEN, no `[[execution.external_tools]]`, no `mcp_servers` - so home_*, media_*, energy_* refuse with 'Home Assistant is not configured' (home/tools.py:75-83) and external/MCP register nothing",
      "simorgh/orchestration/profiles.py:19-69 CHAT still lists kb_*, cal_*, mail_*, sec_*, home_*, energy_*, media_* for every chat turn; tests/simorgh/execution/energy = 326 lines"
    ],
    "why_it_matters": "For a one-laptop, one-family system this is a large speculative surface: it is prompt tokens on every chat turn, three tables to keep in sync, probes to run, and a place for the 'unconnected wire' bug to live unnoticed because nothing exercises it. The work itself is not wrong - HA and a document index are plausible next steps - but registering it unconditionally makes the offered tool list lie about what can happen today.",
    "recommendation": "Do not delete; gate registration on configuration. In builtin_tools(), register a domain's tools only when its Connector probe says 'configured' (domainstatus.py already computes this), otherwise register a single `<domain>_setup` tool whose output is the exact config to add. That shrinks the CHAT list from ~70 names to the ~30 that can run, and lets the policy/marker tables be asserted against the live registry. If external.py/mcp.py stay unused for another month, move them to a `contrib/` package outside the boundary test rather than carrying them in execution/.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count lines in execution modules named by the finding |  21590 total 27 simorgh/execution/knowledge/__init__.py 158 simorgh/execution/knowledge/api.py 204 simorgh/execution/knowledge/chunk.py 173 simorgh/execution/kn |
| 2 | Bash | Read HA refusal path, CHAT profile, masked config keys, ledger layout |  return HomeAssistantClient( url=url, token=token, timeout_s=float(getattr(self._config, "home_timeout_s", 10.0)), dry_run=bool(getattr(self._config, "home_dry_ |
| 3 | Bash | Check HA config sources, domainstatus helper, CHAT tool count |  "switch": ("switch.turn_on", "switch.turn_off"), "fan": ("fan.turn_on", "fan.turn_off"), "media_player": ("media_player.turn_on", "media_player.turn_off"), "co |
| 4 | Bash | Inspect secrets keys, domainstatus usage, builtin_tools registration | Exit code 1 ----SECRETS_KEYS SIM_API_TOKEN REOLINK_HOST REOLINK_USERNAME REOLINK_PASSWORD RING_TOKEN RING_USERNAME ----DOMAINSTATUS_USE (eval):1: no matches fou |
| 5 | Bash | Read builtin_tools body and enumerate registered tool names | def builtin_tools(config: Config, *, secrets=None) -> list: """`secrets` is the subsystem's scoped secret store. Only the account-backed tools use it, and they  |
| 6 | Bash | Inspect ledger stream layout and an action stream sample | action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl action%3A00085e844cff.jsonl action%3A0009062c07cc.jsonl 118215 1 voice%3Atur |
| 7 | Bash | Count tool proposals per registered tool across ledger action streams | 26737 {"causation_id":null,"idempotency_key":null,"payload":{"proposal":{"action_id":"00058d0478bb","args":{"action":"offer","camera":"Garden","sdp":"blob:731ac |
| 8 | Bash | Recount proposals per tool with correct payload path, and find where tool names are listed outside their package | Exit code 1 received 26737 dates 2026-09-09 2026-09-17 never proposed 33 ['cam_ptz', 'cam_setup', 'camera_describe', 'console_tail', 'dash_key', 'energy_report' |
| 9 | Bash | Locate tool name tables, external/MCP wiring, security and knowledge config needs, prompt hint rendering | ----WHERE_NAMES_LIVE simorgh/interface/dispatch.py:1223:_NO_ARG_TOOLS = frozenset({"kb_status", "sec_self", "sec_posture", "energy_status", simorgh/interface/li |
| 10 | Bash | Confirm security tool config needs, table shapes, existing registry tests, prompt rendering of tools | ----SEC_INIT class _SecurityTool: def __init__(self, config, *, store=None, secrets=None, env=None, clock=time.time, lsof_runner=None) -> None: self._config = c |
| 11 | Bash | Check offered-tool computation, prompt cost of CHAT tool list, existing registry consistency tests | ----OFFERED 758: # decides); once anything has registered, an Execution that 1221: # `offered_tools(())` means "every registered tool" (skills arrive 1223: offe |
| 12 | Bash | Read profile-filter semantics test, registry test, offered_tools, connector consumers, and measure prompt cost | ----ROUTER_TEST class TestOfferedToolsFollowRealRegistrations(unittest.TestCase): """`offered_tools` filters a profile by what Execution announced -- never by t |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The measurements replicate exactly (5,523/21,590 lines; 33 of 98 tools never proposed in 26,737 action streams over 2026-09-09..09-17; home 5, pim 6, container 2; no HA/external/MCP config; CHAT = 72 names; unconfigured tools cost ~1.2k tokens of hints per chat turn). But the framing and recommendation fail on the code: (1) security is counted among the 'cannot work today' domains, yet sec_self is entirely local and needs no config -- only knowledge and energy are blocked; (2) the recommendation to gate registration on config would NOT shrink the CHAT list, because offered_tools (orchestration/tools.py:607-627) deliberately never subtracts unregistered names from a profile -- a 2026-09-08 decision reversed after intersection stripped every builtin -- so the change would leave 72 names and turn a specific 'Home Assistant is not configured, set X and Y' refusal into 'I have no such tool', the failure already logged at profiles.py:39-41; (3) the proposed <domain>_setup tool already exists in substance as the refusal text (home/tools.py:79-86) and as a documented deliberate choice (execution/tools.py:3080-3084); (4) the table-vs-registry assertion it asks for already exists (test_tools_router.py:697-716); (5) remote.py is already config-gated and external/mcp are wired in service.py:161,193 -- they are empty because config is empty, not speculative surface, so the contrib/ move is disproportionate for 511 lines; (6) the 9-day window is dominated by dashboard and benchmark traffic (ring_live 22,849; run_shell 570) with tiny family chat volume, so 'never called' carries little inferential weight for conversational domains. At one-laptop scale the real, verifiable cost is ~1.2k prompt tokens per turn and one row in each of ~7 parallel name tables (not three) per tool; the latter duplication is the genuine architectural smell and is not what the recommendation targets.

### evidence

- find simorgh/execution -name '*.py' | xargs wc -l -> 21590 total; wc -l of the nine named modules -> 5523 total (exact match)
- Ledger replication (payload.proposal.tool over type=='received' in ~/.simorgh/ledger/streams/action*): received 26737, dates 2026-09-09..2026-09-17, never proposed = 33, identical list; home 5 {home_find 2, home_describe 2, home_call 1}, pim 6, run_container 2, media_now 1 (music_* 14 more)
- Top proposals: ring_live 22849, cam_stream 721, run_shell 570, read_file 473, search_code 431 -- window is dashboard and task traffic, not family chat
- ~/.simorgh/simorgh.toml [execution] secrets = [vault:*, SIM_API_TOKEN, REOLINK_HOST/USERNAME/PASSWORD, RING_TOKEN/USERNAME]; ~/.simorgh/secrets.toml keys: SIM_API_TOKEN REOLINK_HOST REOLINK_USERNAME REOLINK_PASSWORD RING_TOKEN RING_USERNAME -- no home_assistant entry; env has 0 HOME_ASSISTANT vars
- simorgh/execution/home/tools.py:56-58 _lookup('HOME_ASSISTANT_URL','vault:home_assistant:url'); :79-86 _unconfigured returns 'refused: Home Assistant is not configured. Set ' + missing() -- this IS the setup guidance the recommendation asks for
- simorgh/execution/security/tools.py:121-127 sec_self description: 'Entirely local -- no network'; _SecurityTool.__init__ :53-75 needs only config.repo_root and a sqlite findings path -- security CAN work today
- simorgh/execution/tools.py:3080-3084 comment: knowledge 'Registered whether or not a source is configured: an unconfigured knowledge base answers with what to add, which beats the tool not existing' -- deliberate design decision
- simorgh/execution/tools.py:3126-3127 RunRemoteTool registered only if config.remote -- remote.py is already config-gated; service.py:161 load_external_tools(self._config.external_tools), :193 for server in self._config.mcp_servers -- external/MCP are wired, empty because config is empty
- simorgh/orchestration/tools.py:607-627 offered_tools: 'A profile names the tools that session should have; registration adds skills to it, and must never subtract' -- gating registration would not shrink CHAT
- tests/simorgh/orchestration/test_tools_router.py:240-250 test_a_registration_never_takes_a_tool_away_from_a_profile (observer, 2026-09-08)
- simorgh/orchestration/profiles.py:39-41: sim_command 'in no profile at all, so every "run restart" got "I have no such tool" (live 2026-09-15)' -- the failure mode registration-gating would reintroduce
- tests/simorgh/orchestration/test_tools_router.py:697-716 test_every_registered_tool_has_a_policy_row_and_a_note iterates builtin_tools(Config()) against _TOOL_POLICY and scaffolds._TOOL_NOTES -- the registry assertion already exists
- python -c: len(CHAT.tools) = 72; hint+note chars for all 72 = 14779 (~3.7k tokens); for the 19 unconfigured = 4683 (~1.2k tokens); scaffolds.render(CHAT) = 12923 chars
- Tool-name tables outside the tool's package (grep energy_status/kb_search/sec_posture): orchestration/tools.py:98-137 _TOOL_POLICY and :395-489 _MARKER_ARG_HINT, scaffolds.py:89-121 _TOOL_NOTES, session.py:431-451 timeouts, contracts/toolargs.py:66,120, interface/live_status.py:64-125, interface/dispatch.py:1223 _NO_ARG_TOOLS -- about seven tables, not three

**severity adjustment:** lower

**corrected claim:** 33 of the 98 registered tools were never proposed in the 9-day ledger window (2026-09-09..09-17), a window dominated by dashboard and benchmark traffic rather than family chat. Knowledge (no document source) and the Home Assistant-backed home/energy/media tools (no HA URL/token in simorgh.toml, secrets.toml or env) cannot run today and refuse with a message naming the exact config to add; security tools are local and can run but have never been called; external/MCP/remote are wired and config-gated, empty only because config is empty. The unconfigured tools cost roughly 1.2k prompt tokens of hints per chat turn and one row in each of about seven parallel name tables (policy, marker hint, note, timeout, toolargs, live_status, dispatch). Gating registration on configuration would not shrink the CHAT list, because offered_tools deliberately never subtracts unregistered names from a profile (reversed 2026-09-08 after it stripped every builtin), and would replace an informative refusal with 'I have no such tool'. The registry-vs-tables assertion already exists in test_tools_router.py. The actionable cost is the seven-table duplication per tool, not unconditional registration.

