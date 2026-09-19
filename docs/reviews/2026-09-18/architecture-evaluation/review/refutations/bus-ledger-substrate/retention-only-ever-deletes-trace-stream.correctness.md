# refute:correctness:Retention only ever deletes trace stream

*Workflow: review · Phase: Refute · Agent id: `aa3ce19e57416dce5` · Tool calls: 10*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "bus-ledger-substrate". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Retention only ever deletes trace streams; every journal stream grows forever because truncation requires a snapshot and one snapshot exists",
    "kind": "right-design-undermined",
    "severity": "high",
    "claim": "The compaction design (snapshot + keep_tail for forever streams, windows for the rest) is sound, but DEFAULT_RETENTION names only trace/dead/activity and the forever path is a no-op without a snapshot, so metrics:history, curiosity:ticks, persona:state, execution:inflight, execution:tools and config:effective are append-forever; in 129 recorded passes not one event was ever truncated.",
    "evidence": [
      "simorgh/ledger/compaction.py:36 -- `DEFAULT_RETENTION = {\"trace:\": \"2d\", \"dead:\": \"30d\", \"activity\": \"90d\"}`; compaction.py:93-98 -- `if window is None: snapshot = await backend.read_snapshot(stream); if snapshot is None: continue`",
      "`ls ~/.simorgh/ledger/snapshots` -> 1 file (planning%3Aindex.json); heads/ empty",
      "ledger:compaction over all passes: `streams_deleted=235527 events_truncated=0`",
      "metrics:history: 119,099,341 bytes, 50,677 events, written every 10 s (kernel/metrics.py:218-258, kernel/api.py:42 `metrics_every_s: float = 10.0`); /api/history reads only the last 10 minutes (interface/httpapi.py:144)",
      "curiosity:ticks: 45,068,994 bytes, 161,096 events, last one `\"skipped_reason\":\"autonomy_paused\"`; written at curiosity/service.py:584 and :175, read nowhere (grep for readers returns only the constant)",
      "persona:state: 17,819,390 bytes, 47,784 events; persona/service.py:155-157 reads only the head event at start",
      "execution:inflight: 10,150,896 bytes, 53,406 events; execution/service.py:702-703 `events = await self._ctx.ledger.read(INFLIGHT_STREAM)` reads all of it at every boot; execution:tools 20,110 lines read in full at orchestration/service.py:158 and interface/dispatch.py:1236",
      "config:effective: 248 boot records, 4,025,584 bytes"
    ],
    "why_it_matters": "This is the substrate-level instance of the project's 'unconnected wire': compaction waits for snapshots that no subsystem writes. The journals are the biggest byte consumers after trace (metrics 119 MB, curiosity 45 MB) and grow without bound on an 8%-free disk; the ones read in full at boot make boot time a function of lifetime history.",
    "recommendation": "Make retention windows the default for journal-shaped streams (metrics: 7d, curiosity:ticks 1d or do not append a tick that did nothing, config:effective keep last N) and let compaction truncate a snapshot-less singleton stream to keep_tail when a window is set. For execution:inflight and execution:tools, either snapshot (they are trivially foldable) or read from a bounded tail.",
    "confidence": 0.95
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/ledger/compaction.py | 1 """Record compaction (02-ledger section 5.2) -- retention of the *log 2 itself*, distinct from context compaction (which is Cognition's job and 3 operates on  |
| 2 | Bash | List ledger snapshots, heads, directory layout and disk usage | /Users/saeed/.simorgh/ledger/heads: total 0 drwxr-xr-x@ 2 saeed staff 64 Sep 10 15:14 . drwxr-xr-x@ 9 saeed staff 288 Sep 18 17:14 .. /Users/saeed/.simorgh/ledg |
| 3 | Bash | Measure sizes and event counts of the named journal streams |  118215 --- metrics%3Ahistory.jsonl bytes=119099341 lines= 50677 curiosity%3Aticks.jsonl bytes=45068994 lines= 161096 persona%3Astate.jsonl bytes=17819390 lines |
| 4 | Bash | Sum compaction pass reports across the ledger:compaction stream |  129 ledger%3Acompaction.jsonl passes 129 streams_deleted 235527 events_truncated 0 {"causation_id":"8bc3d31b-4fc1-4d31-81c0-43b795142e6c","idempotency_key":nul |
| 5 | Bash | Check config overrides for retention and who writes snapshots | --- snapshot writers: (eval):1: no matches found: --include=*.py --- RetentionPolicy.parse callers: simorgh/ledger/service.py:46: self.policy = RetentionPolicy. |
| 6 | Bash | Read metrics history writer and the /api/history reader |  idle_tick_cooldown_s: float = 3.0 sleep_every_s: float = 6 * 3600 metrics_every_s: float = 10.0 health_every_s: float = 5.0 supervisor_backoff_s: tuple[float,  |
| 7 | Bash | Read the cited writer and reader sites for the journal streams | --- curiosity ticks refs: (eval):1: no matches found: --include=*.py --- curiosity/service.py 170-178, 580-590 async def stop(self) -> None: for sub in self._su |
| 8 | Bash | Find snapshot writers, curiosity tick readers, and retention wiring | --- snapshot writers: simorgh/ledger/client.py:228: await self.backend.write_snapshot(stream, state, at_seq) simorgh/ledger/projection.py:45: await backend.writ |
| 9 | Bash | Check whether prior reviews already report compaction or journal growth | --- known-findings mentions: docs/architecture-audit-2026.md:23:5. **Cognition Compaction Pipeline:** A 5-layer graduated pipeline (budget reduction → snip → mi |
| 10 | Bash | Identify the sole snapshot writer and the config:effective writer |  await asyncio.sleep(interval) except asyncio.CancelledError: raise except Exception: # noqa: BLE001 -- polling must never die silently... but must never crash  |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every factual element of the claim reproduces against the code today and the live ledger. simorgh/ledger/compaction.py:36 has exactly `DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"}`; `window_for` (compaction.py:65-71) returns None for any stream not matching those prefixes, and run_compaction (compaction.py:93-97) `continue`s when a forever stream has no snapshot -- so a journal stream with no snapshot and no configured window is never touched. ~/.simorgh/simorgh.toml has no `[ledger]` section, so the defaults are what runs (ledger/service.py:46,59-60 adopts ctx.config only when present). The only production callers of backend.write_snapshot are ledger/client.py:228 and ledger/projection.py:45, and the only snapshot on disk is snapshots/planning%3Aindex.json (heads/ is empty), so no other subsystem produces the snapshot the forever path waits on. Summing the 129 records on ledger:compaction gives streams_deleted=235527 events_truncated=0 -- exactly as claimed. Stream sizes on disk match the finding byte-for-byte (metrics:history 119,099,341 B / 50,677 lines; curiosity:ticks 45,068,994 B / 161,096; persona:state 17,819,390 B / 47,784; execution:inflight 10,150,896 B / 53,406; execution:tools 20,110 lines; config:effective 4,025,584 B / 248). The writer/reader citations are accurate: MetricsHistoryWriter appends every tick (kernel/metrics.py:218-258) at metrics_every_s=10.0 (kernel/api.py:42) while HttpApi defaults history_default_minutes=10.0 (interface/httpapi.py:144); curiosity:ticks is appended at curiosity/service.py:175 and :584 and the only other reference is a docstring in sampler.py:86 (no reader); persona/service.py:155-157 reads only the head event; execution/service.py:702-703, orchestration/service.py:158 and interface/dispatch.py:1236 each `ledger.read(...)` the whole stream with no from_seq/limit. Disk is 92% used (39 GiB free), consistent with '8%-free'. The known-findings list mentions the JSONL backend being ~1.4 GB, but none of the three prior review documents mention retention, keep_tail, compaction of the ledger log, metrics:history or curiosity:ticks; the mechanism (forever-path is a no-op for journals because only planning writes snapshots) is materially new. Classification as right-design-undermined is apt: the compaction module's own docstring describes the snapshot+tail scheme, and it is inert because no one writes the snapshots.

### evidence

- simorgh/ledger/compaction.py:36 `DEFAULT_RETENTION: dict[str, str] = {"trace:": "2d", "dead:": "30d", "activity": "90d"}`
- simorgh/ledger/compaction.py:93-97 `window = policy.window_for(stream); if window is None: snapshot = await backend.read_snapshot(stream); if snapshot is None: continue`
- simorgh/ledger/compaction.py:65-71 window_for: `return self.windows[best] if best is not None else None` (no match = forever)
- `grep -n -A8 '^\[ledger\]' ~/.simorgh/simorgh.toml` -> no output (no retention override configured; defaults run)
- `grep -rn write_snapshot simorgh | grep -v 'def \|tests/'` -> only simorgh/ledger/client.py:228 and simorgh/ledger/projection.py:45
- `ls -la ~/.simorgh/ledger/snapshots ~/.simorgh/ledger/heads` -> snapshots/ holds one file planning%3Aindex.json (109187 B); heads/ empty
- python sum over ~/.simorgh/ledger/streams/ledger%3Acompaction.jsonl -> `passes 129 streams_deleted 235527 events_truncated 0`; last record: `{"events_truncated":0,"reason":"sleep_tick","streams_deleted":4476,"streams_seen":106918}`
- stat/wc on streams: metrics%3Ahistory.jsonl bytes=119099341 lines=50677; curiosity%3Aticks.jsonl bytes=45068994 lines=161096; persona%3Astate.jsonl bytes=17819390 lines=47784; execution%3Ainflight.jsonl bytes=10150896 lines=53406; execution%3Atools.jsonl bytes=8298845 lines=20110; config%3Aeffective.jsonl bytes=4025584 lines=248
- simorgh/kernel/api.py:42 `metrics_every_s: float = 10.0`; simorgh/kernel/metrics.py:218-258 MetricsHistoryWriter appends one event per tick to metrics:history
- simorgh/interface/httpapi.py:144 `history_stream: str = "metrics:history", history_default_minutes: float = 10.0`
- `grep -rn 'curiosity:ticks\|_TICKS_STREAM' simorgh` -> service.py:49 (constant), :175 and :584 (appends), sampler.py:86 (docstring only) -- no reader
- simorgh/persona/service.py:155-157 reads `head` then `ledger.read("persona:state", from_seq=head, limit=1)`
- simorgh/execution/service.py:702-703 `events = await self._ctx.ledger.read(INFLIGHT_STREAM)` (full stream, every boot)
- simorgh/orchestration/service.py:158 `events = await ctx.ledger.read(_TOOLS_STREAM)`; simorgh/interface/dispatch.py:1236 `events = await ledger.read(TOOLS_STREAM)`
- `df -h ~` -> 92% used, 39Gi free
- grep of docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html, docs/architecture-third-opinion-2026-09-18.md for retention|keep_tail|metrics:history|curiosity:ticks -> no hits (only cognition context compaction is discussed)

**severity adjustment:** keep

