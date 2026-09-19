# refute:proportionality:The Kernel's own metrics history is the

*Workflow: review · Phase: Refute · Agent id: `a1d2ef6a9030d5ccb` · Tool calls: 13*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "kernel-lifecycle-config". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "The Kernel's own metrics history is the largest ledger stream and grows ~19 MB per day of uptime with no retention",
    "kind": "bug",
    "severity": "low",
    "claim": "MetricsHistoryWriter appends a full MetricsTable snapshot every metrics_every_s=10 s to the append-only `metrics:history` stream, which is now 114 MB / 50,677 events, larger than any other stream, with no compaction or age cap anywhere in kernel/metrics.py.",
    "evidence": [
      "`ls -S ~/.simorgh/ledger/streams | head`: metrics%3Ahistory.jsonl 114M, curiosity%3Aticks.jsonl 43M, persona%3Astate.jsonl 17M; `wc -l` metrics history = 50677 lines; 50677 x 10 s = 140.8 h of uptime => 19.4 MB per day.",
      "simorgh/kernel/service.py:289-293 MetricsHistoryWriter(interval_s=self.runtime.metrics_every_s); api.py:42 metrics_every_s = 10.0; grep 'retention|compact|truncat|keep' in kernel/metrics.py: no hits.",
      "Ledger totals: 118,215 stream files, streams/ 696M, blobs/ 325M, index.json 12.8 MB."
    ],
    "why_it_matters": "The ledger is meant to be the durable record; the kernel is filling it with derivable telemetry (metrics.py's own docstring calls the table a 'justified cache'). Boot cost is fine (0.27 s scan measured), so this is disk and backup weight, but it is the kernel doing it to its own store.",
    "recommendation": "Snapshot every 60 s and write to a rolling file outside the ledger (or a single `metrics:history` stream truncated by age at boot); the dashboard's /api/history needs the last hours, not five days at 10 s resolution.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Check ledger stream sizes and metrics history line count | total 1425296 -rw-r--r--@ 1 saeed staff 119099341 Sep 18 17:14 metrics%3Ahistory.jsonl -rw-r--r--@ 1 saeed staff 45068994 Sep 18 17:14 curiosity%3Aticks.jsonl - |
| 2 | Bash | Read MetricsHistoryWriter and search for retention logic | simorgh/kernel/api.py:42: metrics_every_s: float = 10.0 simorgh/kernel/service.py:52:from .metrics import MetricsHistoryWriter, MetricsTable, ProcessMetricsPubl |
| 3 | Bash | Check for any retention of the metrics history stream and its read side | simorgh/interface/service.py:278: history_stream=self.config.history_stream, simorgh/interface/config.py:121: history_stream: str = "metrics:history" simorgh/in |
| 4 | Bash | Inspect ledger compaction policy, its callers, config, and history read path | # `trace:` is one stream -- and one idempotency file -- per traced # message, so its cost is file *count*, not bytes: 192,332 of them on # the creator's ledger  |
| 5 | Bash | Find compaction callers, ledger config, and JSONL read implementation | --- callers of run_compaction / RetentionPolicy simorgh/ledger/config.py:25: retention: dict = field(default_factory=dict) # prefix -> "7d" \| "forever" (default |
| 6 | Bash | Read ledger service compaction wiring and JSONL backend read path |  self._first_compaction: asyncio.Task \| None = None self.compactions = 0 self.last_report: dict \| None = None def _adopt(self, config: Config) -> None: self.con |
| 7 | Bash | Read JSONL read-offset index invalidation logic |  """ path = self._stream_path(stream) if not path.exists(): return [] if from_seq > 1: seeked = self._read_from_offset(stream, path, from_seq, limit) if seeked  |
| 8 | Bash | Time a full JSON parse of the metrics history file | full parse: 50677 lines in 0.64s line scan only: 0.04s |
| 9 | Bash | Find dashboard polling cadence for the history endpoint | simorgh/interface/config.py:120: # bounds for the `/api/history` and `/api/logs` read-only queries. simorgh/interface/httpapi.py:262: # observe-tier numbers `/a |
| 10 | Bash | Read how the offset index copes with a grown stream file |  # path and the index bought nothing (measured: no change at all # in Memory's 86 ms recall until this case was handled). start_seq = from_seq if from_seq in of |
| 11 | Bash | Find dashboard history polling interval | 386: const POLL_MS = 1000; 612: setTimeout(poll, POLL_MS); 708: const BENCH_POLL_MS = 15000; 795: const HISTORY_POLL_MS = 10000; 796: const HISTORY_MINUTES = 10 |
| 12 | Bash | Check stream classification and effective retention window for metrics history | 60:def is_per_id(name: str) -> bool: 61- return ":" in name 62- 63- 64-def escape(name: str) -> str: 65- """A filesystem-safe form. `%` is outside the grammar,  |
| 13 | Bash | Check compaction run history and naming of the other large streams |  129 /Users/saeed/.simorgh/ledger/streams/ledger%3Acompaction.jsonl {"causation_id":"8bc3d31b-4fc1-4d31-81c0-43b795142e6c","idempotency_key":null,"payload":{"ev |

## Structured reply

**refuted:** False

**verdict:** partly-true

**corrected claim:** MetricsHistoryWriter appends a ~2.3 KB MetricsTable snapshot every 10 s to `metrics:history` (119,099,341 bytes / 50,677 events today, the largest stream; ~13.5 MB per calendar day, ~20 MB per uptime day). The stream is never bounded, but NOT because retention is missing from the system: the Ledger already owns a working retention/compaction pass (simorgh/ledger/compaction.py, run after start and on every 6-hourly sleep tick; 129 passes recorded, the last saw 106,918 streams). It cannot reach this stream for two implementation reasons: (1) DEFAULT_RETENTION has no `metrics:` entry and ~/.simorgh/simorgh.toml has no [ledger] section, so window_for() returns None (forever) and the only forever-branch truncation requires a snapshot the writer never creates; (2) even with a `metrics:` window, `is_per_id()` is `":" in name`, so `metrics:history` is routed to the per-id branch that deletes a stream only when its last event is older than the window, which never happens on a stream appended to every 10 s. The same misnaming affects the next two largest streams, `curiosity:ticks` (45 MB) and `persona:state` (17 MB). The fix belongs inside the ledger (a singleton-override or rename to the singleton grammar plus a default window of a day or two), not a rolling file outside it.

**reasoning:** The numbers and the absence of any cap are verified against the live ledger and the code, so the finding stands. But the lens question is whether the recommendation is proportionate, and it is not. The finding's evidence stopped at kernel/metrics.py ("no retention there"), which is the wrong place to look: Simorgh's design deliberately puts log retention in the Ledger subsystem (RetentionPolicy + run_compaction), and that machinery demonstrably runs. What is wrong is (b) a right design undermined by implementation: the singleton-vs-per-id classification is done by naming grammar alone (`":" in name`), and three high-volume singleton streams were named with the per-id grammar, so the compaction pass can never truncate them regardless of any window the creator configures. That is a materially different diagnosis and a materially smaller fix (one entry in DEFAULT_RETENTION plus either a rename to `metrics_history`-style names or an explicit singleton list in compaction.py) than "snapshot to a rolling file outside the ledger", which would add a second storage path, bypass the existing compaction, and give up the /api/history read path that already works via head()-500 seeks. Consequences at this scale are disk and backup weight only: boot scan is cheap, a full parse of the 119 MB file costs 0.64 s once per process and the JSONL offset index survives growth (it is only discarded when the file shrinks), and the dashboard reads two 500-event tails every 10 s. Severity low is correct; keep it. Also the 60 s cadence suggestion is a taste call, not a fix: at 10 s the stream is 1.5 MB/hour, and a 2-day window would hold it at ~40 MB permanently.

### evidence

- `ls -lS ~/.simorgh/ledger/streams | head -3`: metrics%3Ahistory.jsonl 119099341 bytes, curiosity%3Aticks.jsonl 45068994, persona%3Astate.jsonl 17819390; `wc -l` metrics history = 50677; 2350 bytes/line; first ts 1789014458 last 1789776858 (8.8 calendar days => ~13.5 MB/day; 50677*10s = 140.8 h uptime => ~20 MB/uptime day).
- simorgh/kernel/metrics.py:45 HISTORY_STREAM = "metrics:history"; :225-260 MetricsHistoryWriter appends copy.deepcopy(per_subsystem) every max(1.0, interval_s) with no cap; grep -i 'retention|compact|truncat|keep|prune|trim' in kernel/metrics.py: no hits. simorgh/kernel/service.py:289-291 constructs it with interval_s=self.runtime.metrics_every_s; simorgh/kernel/api.py:42 metrics_every_s = 10.0.
- Retention exists and runs: simorgh/ledger/compaction.py:36 DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"} (no metrics/curiosity/persona entry); :86-133 run_compaction; simorgh/ledger/service.py:46,63-66,127-131 runs it compact_after_start_s after boot and on SYSTEM_TICK_SLEEP. `tail -1 ~/.simorgh/ledger/streams/ledger%3Acompaction.jsonl`: seq 129, ts 1789765048, streams_seen 106918, streams_deleted 4476, events_truncated 0.
- Why it cannot reach this stream: simorgh/ledger/streams.py:60-61 `def is_per_id(name): return ":" in name`; compaction.py:94-101 window None => only truncate below a snapshot (writer never writes one); :103-108 per-id branch deletes only when backend.last_ts(stream) < now - window. `python3 -c` (import simorgh.ledger.streams/compaction): is_per_id('metrics:history')=True; RetentionPolicy.parse({}).window_for('metrics:history')=None; with {'metrics:':'2d'} => 172800.0 but per-id branch applies.
- `grep -c ledger ~/.simorgh/simorgh.toml` = 0 and section list is [voice] [interface] [execution] [cognition]...: no [ledger] retention configured. simorgh/ledger/config.py:25,49-59 would accept one.
- Same misnaming on the other large streams: simorgh/curiosity/service.py:49 _TICKS_STREAM = "curiosity:ticks"; simorgh/persona/service.py:155-157 reads singleton "persona:state" by head().
- Read/boot cost is not a severity raiser: python3 full JSON parse of the 119 MB file = 0.64 s (line scan 0.04 s), done once per process; simorgh/ledger/backends/jsonl.py:479-545 builds a seq->offset index on the full pass and :564-568 discards it only when st_size < size_when_built (growth keeps it), :562 seeks from max(offsets) for newer seqs. simorgh/interface/httpapi.py:1169-1184 _read_tail reads head-cap+1 with limit=cap; interface/config.py:123 history_max_points=500; static/dashboard.html:795-796,826,848,860 polls /api/history for two subsystems every HISTORY_POLL_MS=10000 with HISTORY_MINUTES=10.

**severity adjustment:** keep

