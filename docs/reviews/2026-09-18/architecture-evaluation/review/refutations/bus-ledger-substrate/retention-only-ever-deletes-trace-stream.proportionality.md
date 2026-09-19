# refute:proportionality:Retention only ever deletes trace stream

*Workflow: review · Phase: Refute · Agent id: `a04ff2b83bdf9f7d6` · Tool calls: 13*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "bus-ledger-substrate". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 2 | Bash | List ledger snapshot and head directories, ledger size, disk free | /Users/saeed/.simorgh/ledger/heads: total 0 drwxr-xr-x@ 2 saeed staff 64 Sep 10 15:14 . drwxr-xr-x@ 9 saeed staff 288 Sep 18 17:14 .. /Users/saeed/.simorgh/ledg |
| 3 | Bash | Measure journal stream sizes and largest streams |  118215 metrics%3Ahistory.jsonl 119099341 bytes 50677 lines curiosity%3Aticks.jsonl 45068994 bytes 161096 lines persona%3Astate.jsonl 17819390 bytes 47784 lines |
| 4 | Bash | Sum compaction reports and check ledger retention config |  129 ledger%3Acompaction.jsonl passes 129 streams_deleted 235527 events_truncated 0 {"causation_id":"8bc3d31b-4fc1-4d31-81c0-43b795142e6c","idempotency_key":nul |
| 5 | Bash | Find snapshot writers and retention wiring | (eval):1: no matches found: --include=*.py --- ledger service simorgh/ledger/service.py:4:runs record compaction on `system.tick.sleep`, publishes simorgh/ledge |
| 6 | Bash | Check retention config on disk, snapshot writers, LedgerConfig | /Users/saeed/.simorgh/secrets.toml /Users/saeed/.simorgh/simorgh.toml --- snapshot writers simorgh/ledger/client.py:228: await self.backend.write_snapshot(strea |
| 7 | Bash | Read metrics history writer and readers | --- metrics writer while True: await self._clock.sleep(self._interval) try: await self.publish_once() except Exception: # noqa: BLE001 -- metrics reporting must |
| 8 | Bash | Read curiosity ticks and persona state writers/readers | --- curiosity ticks (eval):1: no matches found: --include=*.py async def stop(self) -> None: for sub in self._subs: await sub.unsubscribe() self._subs.clear() i |
| 9 | Bash | Read execution inflight/tools and config effective readers | --- execution inflight 62:INFLIGHT_STREAM = "execution:inflight" 703: events = await self._ctx.ledger.read(INFLIGHT_STREAM) 713: await self._ctx.ledger.append(I |
| 10 | Bash | Find stream readers, snapshot callers, and ledger config | --- toml rc=1 --- readers curiosity:ticks simorgh/curiosity/service.py:49:_TICKS_STREAM = "curiosity:ticks" simorgh/curiosity/service.py:175: await self._append |
| 11 | Bash | Read /api/history handler and Ledger read implementation | --- /api/history handler 6:metrics history, logs), *talk* to it from the same page (asked for 11:6.1); one chat box, one turn in flight at a time, no session hi |
| 12 | Bash | Measure journal growth rates, full-parse cost, and tail reader | metrics%3Ahistory.jsonl n= 50677 span= 8.8d first=09-09 last=09-18 MB/day= 13.5 full-parse= 1609ms curiosity%3Aticks.jsonl n=161096 span= 8.8d first=09-09 last= |
| 13 | Bash | Read the JSONL backend read path and seek index |  path = self._stream_path(stream) if not path.exists(): return [] if from_seq > 1: seeked = self._read_from_offset(stream, path, from_seq, limit) if seeked is n |

## Structured reply

**refuted:** False

**verdict:** confirmed

**severity adjustment:** lower

**reasoning:** Every factual element of the claim checks out against the code and the live ledger. compaction.py:36 names only trace:/dead:/activity; window_for() (compaction.py:65-71) returns None for any other stream; run_compaction (compaction.py:93-97) then does `read_snapshot` and `continue`s when it is None. The only snapshot writers in the tree are ledger/client.py:228 and ledger/projection.py:45, and the only subsystem calling them is planning/store.py (:200, :439), which matches the single file in ~/.simorgh/ledger/snapshots (planning%3Aindex.json; heads/ is empty). ~/.simorgh/simorgh.toml has no [ledger] retention overrides (grep rc=1), so DEFAULT_RETENTION is the effective policy. Summing all 129 ledger:compaction records gives streams_deleted=235527 events_truncated=0 exactly as claimed. The six streams' byte and line counts match the finding to the byte. Readers were verified: metrics:history is read only by httpapi._read_tail via head()+from_seq (httpapi.py:1178-1182); curiosity:ticks has no reader anywhere (only the constant at curiosity/service.py:49 and two appends at :175/:584); persona:state reads head only (persona/service.py:155-157); execution:inflight is read in full at execution/service.py:703 and execution:tools in full at orchestration/service.py:158 and dispatch.py:1236.

Where the skeptic lens bites is severity, not truth. Measured growth over the 8.8-day span: metrics 13.5 MB/day, curiosity:ticks 5.1 MB/day, persona 2.0, inflight 1.3, tools 1.0, config 0.5 -- about 23 MB/day total, roughly 205 MB so far out of a 1.4 GB ledger. At that rate the 39 GB free would take ~4.5 years to fill, so "unbounded on an 8%-free disk" is true but not urgent. The boot-time cost is likewise real but small today: a full JSON parse of execution:inflight takes 110 ms and execution:tools 59 ms on this machine, growing ~20 ms/day; metrics:history's 1.6 s full parse is paid once per process (the JSONL offset index then seeks incrementally, jsonl.py:502-504, :548+). So this is (b) right design undermined by implementation, with a genuine but modest present-day cost. The recommendation is proportionate -- three entries added to DEFAULT_RETENTION and one skip-the-no-op-tick guard, no new subsystem or snapshot machinery required -- so it does not create more work than it saves. The strongest concrete item is curiosity:ticks: 161k append-only audit records that nothing reads, written even when the tick did nothing ("autonomy_paused"). Severity should be medium rather than high.

### evidence

- simorgh/ledger/compaction.py:36 `DEFAULT_RETENTION: dict[str, str] = {"trace:": "2d", "dead:": "30d", "activity": "90d"}`; :65-71 window_for returns None (forever) on no prefix match; :93-97 `if window is None: snapshot = await backend.read_snapshot(stream); if snapshot is None: continue`
- Only snapshot writers: simorgh/ledger/client.py:228 and simorgh/ledger/projection.py:45; only subsystem caller is simorgh/planning/store.py:200 and :439 (`self._ledger.snapshot(self._index_stream, ...)`). `ls ~/.simorgh/ledger/snapshots` -> planning%3Aindex.json only; heads/ empty
- `grep -n -i 'retention|keep_tail|[ledger' ~/.simorgh/simorgh.toml` -> no matches (rc=1): defaults are the effective policy; simorgh/ledger/config.py:25 `retention: dict = field(default_factory=dict)`, service.py:46 `RetentionPolicy.parse(config.retention, ...)`
- Sum over ~/.simorgh/ledger/streams/ledger%3Acompaction.jsonl: `passes 129 streams_deleted 235527 events_truncated 0`; last record `{"events_truncated":0,"reason":"sleep_tick","streams_deleted":4476,"streams_seen":106918}`
- Stream sizes (stat/wc): metrics%3Ahistory 119099341 B / 50677 lines; curiosity%3Aticks 45068994 / 161096; persona%3Astate 17819390 / 47784; execution%3Ainflight 10150896 / 53406; execution%3Atools 8298845 / 20110; config%3Aeffective 4025584 / 248. These are the six largest files in streams/ (118,215 files total; trace* count 0 after compaction)
- Growth measured from first/last ts: metrics 13.5 MB/day, curiosity:ticks 5.1 MB/day, persona 2.0, inflight 1.3, tools 1.0, config 0.5 over an 8.8-day span (Sep 9 -> Sep 18); ~23 MB/day total. `df -h`: 39 GiB free (92% used)
- Full-parse cost (python json.loads over each file): metrics 1609 ms, curiosity 995 ms, persona 173 ms, inflight 110 ms, tools 59 ms, config 22 ms
- Writers: simorgh/kernel/metrics.py:218-258 MetricsHistoryWriter appends one event per interval; simorgh/kernel/api.py:42 `metrics_every_s: float = 10.0`. curiosity/service.py:175 and :584 append a tick record on every pass including skipped ones
- Readers: httpapi.py:1178-1182 `_read_tail` uses head()+from_seq (bounded, but first call per process is a full parse per jsonl.py:502-506); curiosity:ticks has no reader (grep returns only service.py:49 constant, :175, :584 appends, sampler.py:86 docstring); persona/service.py:155-157 reads head only; execution/service.py:703 `events = await self._ctx.ledger.read(INFLIGHT_STREAM)` full read at boot; orchestration/service.py:158 and interface/dispatch.py:1236 read execution:tools in full

**corrected claim:** The compaction design is sound but its 'forever' path is inert for every stream nobody snapshots (all but planning:index); DEFAULT_RETENTION covers only trace/dead/activity and no toml override exists, so metrics:history, curiosity:ticks, persona:state, execution:inflight, execution:tools and config:effective grow forever and 129 passes truncated zero events. At this system's scale the present cost is modest -- ~205 MB and ~23 MB/day of journals, ~170 ms of boot-time full reads growing ~20 ms/day -- so it is a medium-severity substrate defect with a cheap fix (add windows to the default map; stop appending no-op curiosity ticks), not a high-severity one.

