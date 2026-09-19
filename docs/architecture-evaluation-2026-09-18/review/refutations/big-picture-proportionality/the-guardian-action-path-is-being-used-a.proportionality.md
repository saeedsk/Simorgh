# refute:proportionality:The Guardian action path is being used a

*Workflow: review · Phase: Refute · Agent id: `af9cfc00c99c034cb` · Tool calls: 11*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "big-picture-proportionality". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "The Guardian action path is being used as the RPC channel for dashboard video signalling",
    "kind": "wrong-design",
    "severity": "high",
    "claim": "85% of all Guardian proposals ever made (22,849 of 26,737 action streams) are `ring_live` offer/keepalive/close calls from the dashboard page at 3.6 per minute, each minting an HMAC token, three ledger events and a stream file; the safety audit trail is dominated by UI plumbing that carries no decision.",
    "evidence": [
      "ls ~/.simorgh/ledger/streams | grep '^action%3A' | xargs -I{} head -1 {} | grep -o '\"tool\":\"[a-z_]*\"' | sort | uniq -c -> \"22849 ring_live / 721 cam_stream / 570 run_shell / 473 read_file ...\"; proposed_by -> \"23560 interface:dash / 2979 orchestration / 18 verification\"",
      "ring_live actions: \"8301 close / 5230 keepalive / 9318 offer\"; ts span -> \"n=22849 span_hours=106.8 per_minute=3.6\"",
      "simorgh/interface/httpapi.py:476-487 `_ring_live` -> `_run_for_page(\"ring_live\", args, 30.0)`, route POST /api/dash/ring/live rate=(120, 60.0); :815 `_ACTIVITY_SILENT_TOOLS = frozenset({\"ring_live\"})` -- the code already knows this traffic is not activity",
      "simorgh/execution/home/ring.py:698-703 -- ring_live is WebRTC signalling (`sdp`, `session`), not an effect on the house",
      "Guardian decision sample over 3,000 streams: \"2995 approved / 5 denied\""
    ],
    "why_it_matters": "'Every effect goes through Guardian' is the right principle for effects; applying it to a keepalive turns the decision log into noise (a human reading `action:*` to answer 'what did Sim do to my house' has to skip 22k rows), costs a ledger stream per call, and trains everyone -- including the model -- to see approval as free. It also inflates the ledger the creator already flagged as 1.4 GB.",
    "recommendation": "Classify tools: a session-scoped, read-only signalling call (ring_live keepalive/close, cam_stream renegotiation) should be a `world.*` query or a direct HTTP handler, gated once per session by a single `ring_live offer` proposal whose token authorises the follow-ups. Add `action:` retention for read-only tools (ledger/compaction.py:36 DEFAULT_RETENTION currently keeps action:* forever) and a test that the dashboard's steady state produces zero action.proposed per minute.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read the cited code regions |  self.register_route("POST", "/api/dash/cameras/main", _cameras_main, max_body=1024, rate=(30, 60.0)) self.register_route("POST", "/api/dash/youtube", _youtube_ |
| 2 | Bash | Inspect how page-initiated tool calls are routed | 387: async def _run_for_page(tool: str, args: dict, timeout: float) -> tuple[int, bytes, str]: 423: status, body, kind = await _run_for_page("cam_stream", {"cam |
| 3 | Bash | Confirm dispatch publishes an action.proposed the Guardian handles | 1:1298:async def _run_tool(*, bus: BusClient, ledger: LedgerClient, tool: str, raw: str, 2:1299- session_id: str, timeout: float, action_id: str \| None = None)  |
| 4 | Bash | Count action streams and tool distribution in the live ledger (first 20k) | 26737 17118 "tool":"ring_live" 545 "tool":"cam_stream" 427 "tool":"run_shell" 344 "tool":"read_file" 326 "tool":"search_code" 222 "tool":"web_fetch" 152 "tool": |
| 5 | Bash | Measure ledger size, per-stream cost of ring_live, and retention config | 696M . 12M total sample: action%3A00058d0478bb.jsonl 3 action%3A00058d0478bb.jsonl 839 action%3A00058d0478bb.jsonl 1 "type":"decided" 1 "type":"received" 1 "typ |
| 6 | Bash | Find how Guardian classifies ring_live and whether it prompts a human | simorgh/execution/home/ring.py:15: ring_live WebRTC signalling for the dashboard's live view simorgh/execution/home/ring.py:25:Ring's media servers directly, an |
| 7 | Bash | Check ring_live read_only flag, keepalive cadence in the page, ledger boot cost, and whether prior reviews already covered this |  cloud: object = None watcher: object = None cameras: list = field(default_factory=list) seen: set = field(default_factory=set) # event ids already announced cl |
| 8 | Bash | Get keepalive cadence, ledger boot scan, and Guardian rule path for interface:dash reversible actions | Exit code 1 (eval):1: === not found |
| 9 | Bash | Get keepalive cadence, ledger boot scan, and Guardian rule path for interface:dash reversible actions | -- cadence simorgh/interface/httpapi.py simorgh/interface/static/dash.html 487: self.register_route("POST", "/api/dash/ring/live", _ring_live, max_body=65536, r |
| 10 | Bash | Read keepalive cadence in the dashboard page, the reversible rule path, and the ledger stat implementation | -- dash.html 166:setInterval(()=>{if(OFFLINE){const s=Math.round((Date.now()-OFFLINE_AT)/1000);$("#offline-since").textContent="offline for "+(s<90?s+" s":Math. |
| 11 | Bash | Measure action-stream byte share of the ledger and check the boot-time stat implementation | -- bytes 22069453 144289993 389721139 -- stat impl simorgh/ledger/api.py:92: async def stat(self) -> dict: ... simorgh/ledger/api.py:114: def state(self) -> dic |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core measurement holds and the finding is not in any prior review (grep for ring_live/keepalive/signalling across docs/architecture-review-2026-09-18.html, architecture-audit-2026.md, architecture-third-opinion-2026-09-18.md returns nothing). I re-counted the live ledger: 26,737 action streams; in the first 20,000, 17,118 (85.6%) are ring_live, matching the claimed 85%. The route really does go through Guardian: httpapi.py:387-403 `_run_for_page` calls dispatch `_run_tool`, which publishes ACTION_PROPOSED with proposed_by=interface:dash (dispatch.py:1330-1338); each stream holds exactly received/decided/verified (3 events, ~839 bytes). The cadence is by design of the page: a keepalive every 20 s per Ring tile (dash.html:432) and a live window that rotates one camera per second (dash.html:882), which is why offers+closes (17.6k) outnumber keepalives (5.2k). `_ACTIVITY_SILENT_TOOLS = frozenset({"ring_live"})` at httpapi.py:815 confirms the code itself treats the traffic as plumbing, and compaction.py:36 DEFAULT_RETENTION has no `action:` entry.

Where the finding overreaches, at this system's scale: (1) The ledger-inflation argument is wrong in proportion. All 26,737 action streams together are 22.0 MB of the 389.7 MB of stream bytes (5.7%); trace streams are 144 MB and 88,356 of the 118,215 files. ring_live is not what makes the ledger 1.4 GB, and the boot-stat cost the compaction comment describes is a trace problem. (2) Guardian evaluation is in-process and 3.6 proposals/min is negligible CPU on a laptop; nothing is slower because of it. (3) "Trains the model to see approval as free" is speculation: proposed_by is interface:dash, the model never sees these proposals, and they are already filtered from the activity feed. (4) The recommendation of a "direct HTTP handler" bypassing Guardian conflicts with the creator's own stated invariant (Guardian must see every call; ring.py:698-703 docstring says explicitly "Each step is a tool call, so Guardian sees who is opening a live view of the house"), so it was a deliberate choice, not an accident; the disproportionate part of the recommendation is re-architecting a bypass channel rather than fixing the classification.

What survives, and is materially new: the real defect is granularity plus misclassification. RingLiveTool inherits `read_only = False` and `reversibility = "reversible"` from `_RingTool` (ring.py:325-326) and sets neither, so Guardian treats a WebRTC keepalive as a reversible house effect. Consequence: under a locked posture, ReversibilityRule denies it (rules.py:729-731) and ModeRule denies it for a non-autonomous non-read-only origin (rules.py:264), so the TV's Ring live view silently breaks whenever posture is locked, while `ring_light`/`ring_siren` (the actual effects) are the ones locking was meant for. The audit signal-to-noise point (85% of `action:*` rows answer no question about the house) is true and cheap to fix within the invariant: declare keepalive/close read_only, add a read-only `action:` retention, and keep only the `offer` as a reversible proposal. That is a small (b)/(c) fix, not a high-severity wrong-design.

### evidence

- ls ~/.simorgh/ledger/streams | grep -c '^action%3A' -> 26737; first 20000 streams head -1 | grep tool | uniq -c -> 17118 ring_live / 545 cam_stream / 427 run_shell / 344 read_file (85.6% ring_live, matches claim)
- simorgh/interface/httpapi.py:387-403 _run_for_page -> dispatch._run_tool(bus, ledger, tool, session_id="dash", action_id=...); simorgh/interface/dispatch.py:1330-1338 publishes topics.ACTION_PROPOSED with proposed_by=f"interface:{session_id}" -- Guardian path confirmed
- simorgh/interface/httpapi.py:476-487 POST /api/dash/ring/live rate=(120, 60.0); :815 _ACTIVITY_SILENT_TOOLS = frozenset({"ring_live"}) -- confirmed
- simorgh/interface/static/dash.html:432 pc._keep=setInterval(... action:"keepalive" ..., 20000); :882 'the live window slides one camera every LIVE_STEP_S (1 s)' -- cadence is designed into the page, explains 9318 offers / 8301 closes vs 5230 keepalives
- simorgh/execution/home/ring.py:325-326 class _RingTool: read_only = False; reversibility = "reversible"; RingLiveTool (ring.py:698) overrides neither (ast scan: only name/description/args_schema assigned) -- every keepalive is classified as a reversible effect
- simorgh/guardian/rules.py:729-731 ReversibilityRule: r == "reversible" and mode == "locked" -> deny; rules.py:264 ModeRule locked + non-autonomous non-read-only -> deny -- locked posture breaks the dashboard's Ring live view
- simorgh/execution/home/ring.py:698-703 docstring: 'Each step is a tool call, so Guardian sees who is opening a live view of the house' -- deliberate design, not an accident
- simorgh/ledger/compaction.py:36 DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"} -- no action: retention, confirmed
- Byte share (cat | wc -c over ~/.simorgh/ledger/streams): action%3A* = 22,069,453; trace* = 144,289,993; all streams = 389,721,139 -> action streams are 5.7% of stream bytes; file counts: 88,356 trace of 118,215 total. The '1.4 GB ledger' inflation argument does not hold
- Sample stream action%3A00058d0478bb.jsonl: 3 lines, 839 bytes, types received/decided/verified
- grep -n -i 'ring_live|keepalive|signalling' docs/architecture-review-2026-09-18.html docs/architecture-audit-2026.md docs/architecture-third-opinion-2026-09-18.md -> no matches (finding is new)

**severity adjustment:** lower

**corrected claim:** 85% of Guardian action streams (about 22.8k of 26.7k) are ring_live WebRTC signalling from the dashboard page, driven by a 20 s keepalive per Ring tile and a 1 s live-window rotation (dash.html:432, :882). This is a deliberate application of the 'Guardian sees every call' invariant (ring.py:698-703), and its cost is audit signal-to-noise, not resources: the action streams total 22 MB of a 390 MB stream store (traces are 144 MB) and Guardian evaluation is negligible at 3.6/min. The genuine defect is classification granularity: RingLiveTool inherits read_only=False / reversibility='reversible' (ring.py:325-326), so keepalive/close are logged and ruled as reversible house effects, which means a locked posture denies them (rules.py:729-731, :264) and silently breaks the TV's Ring live view while the real effects (ring_light, ring_siren) are the ones locking targets. Fix within the invariant: mark keepalive/close read_only (offer stays a proposal), add a read-only `action:` retention in compaction.py:36, and drop them from the audit view; no bypass channel is needed. Severity: medium (implementation undermines the design), not high.

