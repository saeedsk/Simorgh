# refute:correctness:WebRTC signalling is modelled as agent a

*Workflow: review · Phase: Refute · Agent id: `a25f2145139497e6b` · Tool calls: 10*

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
    "title": "WebRTC signalling is modelled as agent actions: ring_live is 85% of everything Guardian has ever decided",
    "kind": "wrong-design",
    "severity": "high",
    "claim": "Each dashboard offer/keepalive/close for a Ring live view is a full action (bus -> Guardian -> HMAC -> Execution -> verify -> three ledger events -> inflight -> tool.invoked), producing 22,849 action streams in five days, all approved, and the interface already has to special-case the tool to hide it from the activity feed.",
    "evidence": [
      "Ledger measured: 22,849 of 26,737 action streams are ring_live (offer 9,318 / close 8,301 / keepalive 5,230), 18,579,811 bytes; by day: 2026-09-14 = 12,896, 09-16 = 5,052, 09-15 = 4,301; decisions for ring_live: approved 22,846, denied 3",
      "simorgh/interface/httpapi.py:476-487: `POST /api/dash/ring/live` -> `_run_for_page(\"ring_live\", args, 30.0)` with rate=(120, 60.0); :815 `_ACTIVITY_SILENT_TOOLS = frozenset({\"ring_live\"})`",
      "simorgh/execution/home/ring.py:691-734 RingLiveTool: 'Sim carries only the signalling ... Each step is a tool call, so Guardian sees who is opening a live view'",
      "simorgh/execution/security/selfcheck.py docstring rates 'A ledger of hundreds of thousands of files' as a medium finding on this project's own history; ~/.simorgh/ledger/streams holds 118,215 files today"
    ],
    "why_it_matters": "Approval is meaningful once per session, not per keepalive; at packet granularity Guardian is a 100%-yes rubber stamp that costs a ledger file, an HMAC, and a bus round-trip each time. It is the single largest writer to the ledger and the reason cam_stream (721 calls) is the second. On one laptop this is the difference between a ledger you can back up and one you cannot.",
    "recommendation": "One approved action (`ring_live open <camera>`) returns a session grant with a TTL; the page then posts offer/keepalive/close to an httpapi route that talks to the Ring client directly under that grant (the Ring client object is already reachable from the tool's `_cloud()`); `close` or TTL expiry ends it and appends one `ended` event. Same shape for cam_stream. Half a day, and it deletes 85% of future action streams.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read cited httpapi lines for ring_live route |  self.register_route("POST", "/api/dash/cameras/main", _cameras_main, max_body=1024, rate=(30, 60.0)) self.register_route("POST", "/api/dash/youtube", _youtube_ |
| 2 | Bash | Read RingLiveTool and _run_for_page, selfcheck docstring |  if problem: return ToolResult(ok=False, error=problem) if not cam.has_siren: return ToolResult(ok=False, error=f"refused: {cam.name} has no siren") await cloud |
| 3 | Bash | Read _run_for_page and survey ledger stream directory |  self.register_route("POST", "/api/dash/key", _dash_key_post, max_body=512, rate=(300, 60.0)) self.register_route("POST", "/api/dash/state", _dash_state_post, m |
| 4 | Bash | Count ring_live action streams, bytes, days, decisions in ledger | prefixes: [('trace', 88356), ('action', 26737), ('task', 2431), ('verify', 350), ('reflect', 310), ('memory', 5), ('cognition', 5), ('curiosity', 5), ('persona' |
| 5 | Bash | Day split and Guardian verdicts for ring_live; locate _run_tool | by day: [] verdicts: Counter() decided payload sample: None ---- 11:the model's own Guardian-gated tools already cover 34:from simorgh.bus.client import BusClie |
| 6 | Bash | Dump one ring_live action stream and read _run_tool | {"causation_id": null, "idempotency_key": null, "payload": {"proposal": {"action_id": "00058d0478bb", "args": {"action": "offer", "camera": "Garden", "sdp": "bl |
| 7 | Bash | Compute ring_live day split and verdicts; grep Execution path, dashboard JS, grant mechanisms | ring_live streams: 0 by day: [] verdicts: Counter() ---- execution hmac/inflight/invoked 62:INFLIGHT_STREAM = "execution:inflight" 139: secret = ctx.secrets.get |
| 8 | Bash | Fix ring_live day/verdict count; read Execution HMAC, inflight, invoked; dashboard cadence | ring_live streams: 22849 by day: [('2026-09-12', 16), ('2026-09-13', 324), ('2026-09-14', 12896), ('2026-09-15', 4301), ('2026-09-16', 5052), ('2026-09-17', 260 |
| 9 | Bash | Check prior reviews for ring_live, proposer of ring_live streams, verifier use, rotation step | ---- prior reviews mention ring_live? docs/architecture-review-2026-09-18.html:0 docs/architecture-audit-2026.md:0 docs/architecture-third-opinion-2026-09-18.md |
| 10 | Bash | Compare ledger bytes by stream prefix | [('trace', 144289993), ('metrics', 119099341), ('curiosity', 45075623), ('action', 22069453), ('execution', 18449741)] 325M /Users/saeed/.simorgh/ledger/blobs 6 |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every factual element of the claim reproduces against the code and the live ledger. (1) The route: simorgh/interface/httpapi.py:476-487 registers POST /api/dash/ring/live with rate=(120, 60.0) and calls _run_for_page("ring_live", args, 30.0); _run_for_page (httpapi.py:387-419) delegates to interface/dispatch.py:_run_tool (dispatch.py:1298-1365), which publishes ACTION_PROPOSED on the bus and waits for ACTION_RESULT/ACTION_DENIED, i.e. the full Guardian path. (2) Execution re-verifies the HMAC token per action (execution/service.py:143 builds ApprovalVerifier, :756 self._verifier.verify(approved, args, now=now)), appends inflight started/finished to a shared execution:inflight stream (:791, :937), and publishes TOOL_INVOKED (:857). (3) The tool's own docstring states the design intent verbatim (execution/home/ring.py:691-696: "Each step is a tool call, so Guardian sees who is opening a live view of the house"), and the dashboard JS fires an offer per rotated tile (dash.html:427, window slides every LIVE_STEP_S, default 6s, min 0.5s per :195/:383), a keepalive every 20s (:432), and a close on rotation (:437, :449). (4) Ledger measurement I ran myself: 26,737 action streams, of which 22,849 are ring_live (85.5%), split offer 9,318 / close 8,301 / keepalive 5,230; 18,579,811 bytes; every stream is 3 events (received/decided/verified); by day 09-12=16, 09-13=324, 09-14=12,896, 09-15=4,301, 09-16=5,052, 09-17=260; decided kinds approved 22,846 / denied 3 (all three denied with layer "paused", i.e. not a policy judgement); every one of the 22,849 was proposed_by "interface:dash", never by the model. cam_stream is indeed second at 721. ~/.simorgh/ledger/streams holds 118,215 files; selfcheck.py:23 rates "A ledger of hundreds of thousands of files" as medium. (5) _ACTIVITY_SILENT_TOOLS = frozenset({"ring_live"}) at httpapi.py:815 with the comment explaining the tool had to be hidden from the dashboard's own activity feed. (6) Not already known: grep for ring_live in docs/architecture-review-2026-09-18.html, docs/architecture-audit-2026.md and docs/architecture-third-opinion-2026-09-18.md returns 0 hits each; the known "Ledger ~1.4 GB JSONL" finding is about the backend, not about which caller fills it. The classification "wrong-design" is fair: the design intent (Guardian sees who opens a live view) is defeated in practice because the proposer is always the page itself and approval is 100% mechanical. One wording caveat that does not change the verdict: "single largest writer to the ledger" is true by file count among action streams and by count overall after trace streams, but by bytes trace (144 MB), metrics (119 MB) and curiosity (45 MB) streams are larger than all action streams combined (22 MB); the ring_live problem is file-count and per-call overhead, not bytes. The recommendation (one approved open -> TTL grant, page talks to the Ring client directly) is consistent with the code: RingLiveTool already obtains the client via self._cloud() and the keepalive/close steps carry no new authority.

### evidence

- simorgh/interface/httpapi.py:476-487 — `_ring_live` handler builds args from camera/action/sdp/session and returns `await _run_for_page("ring_live", args, 30.0)`; route registered `POST /api/dash/ring/live ... rate=(120, 60.0)`
- simorgh/interface/httpapi.py:387-419 — `_run_for_page` calls `dispatch._run_tool(bus=..., ledger=..., tool=tool, ..., session_id="dash", action_id=action_id)`; comment: 'a proposal Guardian sees, the result read back'
- simorgh/interface/dispatch.py:1298-1365 — `_run_tool` publishes `topics.ACTION_PROPOSED` with proposed_by=f"interface:{session_id}" and awaits ACTION_RESULT/ACTION_DENIED
- simorgh/execution/service.py:143 `self._verifier = ApprovalVerifier(self._secret)`; :756 `outcome = self._verifier.verify(approved, args, now=now)`; :791/:937 append started/finished to `execution:inflight`; :857 publishes `topics.TOOL_INVOKED`
- simorgh/execution/home/ring.py:691-696 RingLiveTool docstring: 'Sim carries only the signalling ... Each step is a tool call, so Guardian sees who is opening a live view of the house'; :706-732 offer/keepalive/close branches
- simorgh/interface/static/dash.html:427 offer POST per tile; :432 `pc._keep=setInterval(... action:"keepalive" ...,20000)`; :437/:449 close POST on rotation; :383 `LIVE_STEP_S=6`, :195 floor 0.5s
- simorgh/interface/httpapi.py:809-815 — comment 'called on every camera rotation of the dashboard's own live grid ... drowned out everything else' and `_ACTIVITY_SILENT_TOOLS = frozenset({"ring_live"})`
- Measured (python over ~/.simorgh/ledger/streams): action streams 26,737; ring_live 22,849; offer 9,318 / close 8,301 / keepalive 5,230; bytes 18,579,811; events per stream 3 (received/decided/verified); by day 2026-09-14=12,896, 09-15=4,301, 09-16=5,052, 09-13=324, 09-17=260, 09-12=16
- Measured: decided kinds for ring_live = approved 22,846 / denied 3, all 3 denials `{"kind": "denied", "layer": "paused"}`; proposed_by for all 22,849 = `interface:dash` (never the model)
- Measured: `ls ~/.simorgh/ledger/streams | wc -l` = 118215; prefixes trace 88,356 / action 26,737 / task 2,431; cam_stream = 721 action streams (second after ring_live)
- simorgh/execution/security/selfcheck.py:23 '**A ledger of hundreds of thousands of files** is medium'
- grep -c ring_live docs/architecture-review-2026-09-18.html docs/architecture-audit-2026.md docs/architecture-third-opinion-2026-09-18.md -> 0, 0, 0 (not previously reported)
- Caveat measured: bytes by stream prefix — trace 144,289,993; metrics 119,099,341; curiosity 45,075,623; action 22,069,453 — ring_live dominates file count and per-call overhead, not ledger bytes

**severity adjustment:** keep

**corrected claim:** Each dashboard offer/keepalive/close for a Ring live view is a full Guardian-gated action (bus proposal -> Guardian decision -> HMAC verify in Execution -> three events in its own action stream + inflight started/finished + tool.invoked), producing 22,849 of 26,737 action streams (85%) in six days, all proposed by the page itself (interface:dash, never the model), approved 22,846 times with the only 3 denials being 'paused'; the interface already special-cases the tool to hide it from its activity feed. It is the largest source of action streams and ledger files by count, though trace/metrics/curiosity streams hold more bytes.

