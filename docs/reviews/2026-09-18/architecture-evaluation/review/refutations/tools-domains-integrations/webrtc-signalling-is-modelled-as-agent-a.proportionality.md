# refute:proportionality:WebRTC signalling is modelled as agent a

*Workflow: review · Phase: Refute · Agent id: `a59cf96a3b9f24162` · Tool calls: 12*

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
| 1 | Bash | Read cited httpapi lines and grep for ring_live/cam_stream routes |  self.register_route("POST", "/api/dash/cameras/main", _cameras_main, max_body=1024, rate=(30, 60.0)) self.register_route("POST", "/api/dash/youtube", _youtube_ |
| 2 | Bash | Read _run_for_page and RingLiveTool |  self.register_route("POST", "/api/dash/key", _dash_key_post, max_body=512, rate=(300, 60.0)) self.register_route("POST", "/api/dash/state", _dash_state_post, m |
| 3 | Bash | List ledger layout and stream file counts by prefix | blobs heads idem index.json LOCK snapshots streams 118215 1 voice%3Aturns.jsonl 1 verify%3Afe1234ff5c0c.jsonl 1 verify%3Afd27f3be972a.jsonl 1 verify%3Afc892e053 |
| 4 | Bash | Count ring_live action streams, events, bytes, decisions in the ledger | 88356 trace 26737 action 2431 task 350 verify 310 reflect 5 memory 5 curiosity 5 cognition 3 persona 2 guardian 2 execution 1 voice 1 system.jsonl 1 schedule.js |
| 5 | Bash | Show a raw action stream and one ring_live stream | Exit code 1 {"causation_id":null,"idempotency_key":null,"payload":{"proposal":{"action_id":"00058d0478bb","args":{"action":"offer","camera":"Garden","sdp":"blob |
| 6 | Bash | Recount ring_live streams by action, day, decision, bytes; check blob store size | /private/tmp/claude-501/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/scratchpad/count2.py:18: DeprecationWarning: datetime.datetime.utcfromtimes |
| 7 | Bash | Inspect dispatch path, selfcheck docstring, ledger retention, action-stream consumers | == dispatch._run_tool 1:1298:async def _run_tool(*, bus: BusClient, ledger: LedgerClient, tool: str, raw: str, 8:1305- # No secret rides in a proposal: every pr |
| 8 | Bash | Read compaction policy, toml retention, selfcheck finding | == compaction default + how it treats action: # `trace:` is one stream -- and one idempotency file -- per traced # message, so its cost is file *count*, not byt |
| 9 | Bash | Grep action-stream consumers, execution verification, guardian decision layering | == consumers of action streams simorgh/execution/service.py:725: events = await self._ctx.ledger.read(f"action:{action_id}") simorgh/execution/service.py:758: a |
| 10 | Bash | Read Guardian decision path and Execution inflight/verify writes | == guardian decide path spilled[key] = await ledger.put_blob(value.encode("utf-8"), content_type="text/plain") else: spilled[key] = value return {**proposal, "a |
| 11 | Bash | Count blobs, size inflight stream, find dashboard cadence, sample traces, show denials | == blobs 42624 == inflight stream -rw-r--r--@ 1 saeed staff 10150896 Sep 17 21:20 /Users/saeed/.simorgh/ledger/streams/execution%3Ainflight.jsonl 53406 /Users/s |
| 12 | Bash | Find dashboard JS cadence, Guardian rules on ring_live, Ring client singleton, SDP blob count | == files mentioning ring/live simorgh/interface/httpapi.py simorgh/interface/static/dash.html -- simorgh/interface/static/dash.html 144:// News, Discover and Te |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** I tried to refute this on two fronts: (1) are the numbers real, and (2) even if real, is a laptop-scale ledger actually hurt by it. Both fronts held for the finding.

Numbers: a script over ~/.simorgh/ledger/streams reproduces the claim exactly: 26,737 action streams, 22,849 of them ring_live (offer 9,318 / close 8,301 / keepalive 5,230), 18,579,811 bytes, decided approved 22,846 / denied 3 (my per-day split is UTC and differs slightly from the claim's local-time split, same total). The 3 denials are `layer: "paused"` (system paused), not a judgement about the tool; every ring_live Guardian ever assessed was approved with `"layer": ""`, i.e. no rule fired, in ~0.25 ms. Guardian has no per-tool rate or frequency rule (grep of simorgh/guardian for rate/budget finds only budget-pressure config), so per-keepalive approval buys nothing the first approval did not.

Path: interface/httpapi.py:387-419 `_run_for_page` -> dispatch._run_tool publishes ACTION_PROPOSED on the bus; guardian/service.py:525-575 spills the SDP to a blob, appends `received` and `decided`; execution/service.py:751-759 verifies the HMAC token and appends `verified`; execution:inflight gets `started`/`finished`; the answer SDP goes to an output blob; TOOL_INVOKED is published (:857). Each browser keepalive (dash.html:432, every 20 s) and each 6-second live-slot rotation (dash.html:383, LIVE_STEP_S=6, 3 live tiles) runs this whole path. The special-casing the claim mentions is real and wider than cited: `_ACTIVITY_SILENT_TOOLS` at httpapi.py:815 is consulted at :821, :833, :841, and `_page_actions` at :400-402 hides the ACTION_RESULT too.

Scale lens, which is where I expected to refute it: ring_live is NOT the largest byte-writer (traces: 88,356 files; blobs: 325 MB) and 18.6 MB over five days is trivial on disk. But three things make it a genuine problem at this scale rather than a cosmetic one. First, `trace:` has a 2-day retention window (ledger/compaction.py:36) while `action:` and `execution:` have none ("no match means forever", compaction.py:71), so ring_live is the dominant PERMANENT growth: ~4.5k action files/day plus ~4.6k SDP blobs/day (9,318 blobs start with `v=0`, 42,624 blobs total) when the TV is on. Second, something the finding missed: `execution:inflight` is a single JSONL of 53,406 lines / 10.15 MB, 22,846 lines naming ring_live, with no retention and no snapshot, and execution/service.py:702-703 reads the whole stream at every boot. Third, the project's own selfcheck (selfcheck.py:201-231) warns at 50k files and the ledger is already at ~161k (118,215 streams + 42,624 blobs), past its own alarm, after a prior 192k-file incident the creator documented in compaction.py:30-35. On one laptop the damage is file count and boot-time replay, not bytes, and both are unbounded today.

Design verdict: (a) wrong design, not a bug. RingLiveTool's stated justification (ring.py:693-696, "Guardian sees who is opening a live view") is fully satisfied by one action per open; modelling keepalive/close as approvable actions produces a 100%-yes gate plus permanent records for protocol chatter. The recommendation is proportionate in effort, with one caveat the finding does not state: routing keepalive/close from httpapi straight to the Ring client bypasses Execution's token verifier for those calls, which is a deliberate architectural exception and should be written as one. A cheaper stopgap that preserves the architecture (a retention window for `action:` streams proposed_by interface:dash, and a snapshot/window for `execution:inflight`) would remove the unbounded growth in an hour, but would not fix the 6-second offer churn or the per-call bus round-trips, so the grant design is the right end state.

### evidence

- Ledger count (python over ~/.simorgh/ledger/streams): action streams 26737; by tool ring_live 22849, cam_stream 721, run_shell 570; ring actions offer 9318 / close 8301 / keepalive 5230; ring decisions approved 22846 / denied 3; ring stream bytes 18579811
- The 3 denials are system-pause, not tool judgement: action:0e9d955434df `{"kind":"denied","layer":"paused"}`; approvals carry `{"kind":"approved","layer":""}` (no rule fired), decided 0.26 ms after received
- simorgh/interface/httpapi.py:387-419 `_run_for_page` -> `dispatch._run_tool` (bus proposal, Guardian, result read back); :476-487 `POST /api/dash/ring/live` rate=(120, 60.0); :400-402 `_page_actions` hides ACTION_RESULT; :815 `_ACTIVITY_SILENT_TOOLS = frozenset({"ring_live"})` consulted at :821, :833, :841
- simorgh/interface/static/dash.html:432 keepalive `setInterval(... action:"keepalive" ..., 20000)`; :383 `CAM_LIVE_MAX=3, LIVE_STEP_S=6` live slots slide one camera every 6 s (:393-404); :427 offer, :437/:449 close
- simorgh/execution/home/ring.py:691-734 RingLiveTool docstring 'Each step is a tool call, so Guardian sees who is opening a live view'; :189-207 webrtc_offer/keepalive/close on the cloud client; :348 `_cloud()` cached in `self._prefs.cloud`
- simorgh/guardian/service.py:525-575: proposal `received` (SDP spilled to blob via _spill_oversized_args), `decided` appended per action; grep of simorgh/guardian for rate/per_minute/ring_live finds no per-tool frequency rule
- simorgh/execution/service.py:751-759 `verified` event per action; :702-715 `_replay_inflight` does `ledger.read(INFLIGHT_STREAM)` in full at boot; :857 TOOL_INVOKED per call
- ~/.simorgh/ledger/streams/execution%3Ainflight.jsonl: 10,150,896 bytes, 53,406 lines, 22,846 lines contain ring_live; ~/.simorgh/ledger/snapshots holds only planning%3Aindex.json (no inflight snapshot)
- simorgh/ledger/compaction.py:36 `DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"}`; :71 'no match means forever' -> `action:` and `execution:` streams are never pruned; ~/.simorgh/simorgh.toml has no [retention] override
- Blobs: `find ~/.simorgh/ledger/blobs -type f | wc -l` = 42624; `grep -rl '^v=0' blobs | wc -l` = 9318 (one SDP offer blob per offer, kept forever); blobs dir 325M
- Traces also carry it: 261 of a 3,000-file sample of trace: streams mention ring_live (~8.7%, ~7.7k files, but 2d-bounded)
- simorgh/execution/security/selfcheck.py:201-231 `check_ledger_size` warns at file_warn=50_000 with remediation 'a trace per action will do this'; ledger today is 118,215 stream files + 42,624 blobs; du 1.4G

**severity adjustment:** keep

