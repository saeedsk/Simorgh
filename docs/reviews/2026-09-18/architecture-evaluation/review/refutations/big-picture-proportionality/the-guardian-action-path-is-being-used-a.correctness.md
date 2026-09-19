# refute:correctness:The Guardian action path is being used a

*Workflow: review · Phase: Refute · Agent id: `a4657fadee03799c5` · Tool calls: 5*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "big-picture-proportionality". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Read cited httpapi lines and grep ring_live routing |  self.register_route("POST", "/api/dash/cameras/main", _cameras_main, max_body=1024, rate=(30, 60.0)) self.register_route("POST", "/api/dash/youtube", _youtube_ |
| 2 | Bash | Read _run_for_page, silent-tools block, ring_live handler, retention table |  self.register_route("POST", "/api/dash/key", _dash_key_post, max_body=512, rate=(300, 60.0)) self.register_route("POST", "/api/dash/state", _dash_state_post, m |
| 3 | Bash | Recount action streams by tool, proposer, ring_live action, and rate | 26737 action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl ---- total 26737 [('ring_live', 22849), ('cam_stream', 721), ('run_she |
| 4 | Bash | Check dispatch Guardian path, events per stream, retention config, prior reviews, and byte share | Exit code 1 33:1330- await bus.publish(bus.new(topics.ACTION_PROPOSED, { 36:1333- # The floor. Guardian recomputes the real class itself and ---- events per str |
| 5 | Bash | Check retention config, prior review mentions, action byte share, Guardian decision sample, token minting | ---- known docs/architecture-audit-2026.md:0 docs/architecture-third-opinion-2026-09-18.md:0 docs/architecture-review-2026-09-18.html:0 ---- size 696M /Users/sa |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line and every number was re-verified against the code and the live ledger. httpapi.py:387-419 `_run_for_page` calls `interface/dispatch._run_tool`, which at dispatch.py:1330-1338 publishes a full ACTION_PROPOSED (proposed_by "interface:dash") for every page call, so each ring_live offer/keepalive/close goes through the Guardian pipeline and the HMAC TokenIssuer (guardian/service.py:3, tokens.py:19-23). httpapi.py:476-487 routes POST /api/dash/ring/live to `_run_for_page("ring_live", ...)` at rate (120, 60.0); httpapi.py:815 `_ACTIVITY_SILENT_TOOLS = frozenset({"ring_live"})` with the comment explaining the SDP blob drowned the activity feed. ring.py:690-703 RingLiveTool's docstring says outright it "carries only the signalling" and "each step is a tool call, so Guardian sees who is opening a live view" -- i.e. this is a deliberate design choice, not an accident, which makes it a wrong-design finding rather than a bug. Recount of ~/.simorgh/ledger/streams: 26,737 action streams, 22,849 ring_live (85.5%), proposed_by interface:dash 23,560; ring actions offer 9,318 / close 8,301 / keepalive 5,230; span 106.8 h, 3.56/min; each stream is exactly 3 events (proposed/decided/verified, 400/400 sampled); decided sample over 3,000 streams = 2,995 approved / 5 denied. compaction.py:36 DEFAULT_RETENTION has no `action:` key and ~/.simorgh/simorgh.toml sets no retention override, so action:* is kept forever. The finding is not in any prior review: grep for ring_live/keepalive in architecture-audit-2026.md, architecture-review-2026-09-18.html and architecture-third-opinion-2026-09-18.md returns 0 hits. Only correction: the ledger-bloat sub-argument is weak in bytes -- all 26,737 action streams total 21 MB of a 696 MB streams directory (the sdp is already stored as a blob hash), so the cost is 22.8k small files and audit-trail signal-to-noise, not gigabytes. The core proportionality claim stands.

### evidence

- simorgh/interface/httpapi.py:387-419 `_run_for_page` -> `_run_tool(bus=..., ledger=..., tool=tool, ..., session_id="dash", action_id=action_id)`; comment: 'The page's own calls -- a camera rotation's signalling, the strip kept live -- are plumbing, not something Sim did.'
- simorgh/interface/httpapi.py:476-487 `_ring_live` -> `_run_for_page("ring_live", args, 30.0)`; `register_route("POST", "/api/dash/ring/live", _ring_live, max_body=65536, rate=(120, 60.0))`
- simorgh/interface/httpapi.py:808-815 `_ACTIVITY_SILENT_TOOLS = frozenset({"ring_live"})` with comment that its SDP output 'drowned out everything else' in the dashboard Sim box
- simorgh/interface/dispatch.py:1330-1338 publishes ACTION_PROPOSED with proposed_by f"interface:{session_id}" for every page call -- full Guardian path, no shortcut
- simorgh/guardian/service.py:3 'mints a real HMAC token on' approval; guardian/tokens.py:19-23 TokenIssuer.mint
- simorgh/execution/home/ring.py:690-703 RingLiveTool docstring: 'Sim carries only the signalling ... Each step is a tool call, so Guardian sees who is opening a live view of the house.' -- deliberate design
- simorgh/ledger/compaction.py:36 `DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"}` -- no action: entry; `grep -i retention ~/.simorgh/simorgh.toml` -> no output
- Recount (python over ~/.simorgh/ledger/streams): total 26737 action streams; tools: ring_live 22849, cam_stream 721, run_shell 570, read_file 473, search_code 431; proposed_by: interface:dash 23560, orchestration 2979, verification 18; ring acts offer 9318 / close 8301 / keepalive 5230; span_h 106.8, per_min 3.56
- Events per action stream: 400 sampled, all exactly 3 lines (proposed, decided, verified); sample stream action:00058d0478bb shows sdp stored as `blob:731ac8...`
- Guardian decided sample over first 3000 action streams: Counter({'approved': 2995, 'denied': 5})
- grep -ic ring_live docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md -> 0, 0, 0 (not previously reported)
- du -sh ~/.simorgh/ledger/streams -> 696M; sum of action%3A* sizes -> 21.0 MB (3% of bytes; the cost is 22.8k files and audit noise, not gigabytes)

**severity adjustment:** keep

**corrected claim:** 85% of all Guardian proposals ever made (22,849 of 26,737 action streams) are `ring_live` offer/keepalive/close signalling calls from the dashboard page at 3.6 per minute, each running the full Guardian pipeline (HMAC token, three ledger events, one stream file), and RingLiveTool's docstring shows this was a deliberate design choice. The safety audit trail is dominated by UI plumbing that carries no decision (2,995 approved / 5 denied in a 3,000-stream sample). The byte cost is small (21 MB of a 696 MB streams directory, since the SDP is stored as a blob hash); the real costs are 22.8k files kept forever (no `action:` retention in compaction.py DEFAULT_RETENTION or simorgh.toml) and an `action:*` log that no longer answers 'what did Sim do to my house' without filtering.

