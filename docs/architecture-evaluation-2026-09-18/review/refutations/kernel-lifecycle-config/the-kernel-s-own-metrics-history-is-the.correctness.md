# refute:correctness:The Kernel's own metrics history is the

*Workflow: review · Phase: Refute · Agent id: `a910cdd944891be4b` · Tool calls: 6*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "kernel-lifecycle-config". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Inspect ledger stream sizes on disk | metrics%3Ahistory.jsonl curiosity%3Aticks.jsonl persona%3Astate.jsonl execution%3Ainflight.jsonl execution%3Atools.jsonl -rw-r--r--@ 1 saeed staff 119099341 Sep |
| 2 | Bash | Read metrics writer code, config, retention grep, and sample stream records |  raise KernelBootError(str(exc)) from exc self.progress.stage("ticks, status, metrics") self._scheduler = Scheduler( bus=self.bus, ledger=self.ledger, clock=sel |
| 3 | Bash | Check ledger-level retention, history reader, whether finding already known, and per-day growth math | simorgh/ledger/api.py:84: async def truncate_below(self, stream: str, seq: int) -> int: ... simorgh/ledger/client.py:18:- `rebuild()`/`materialize()` for projec |
| 4 | Bash | Read compaction policy, its callers, live config, and compaction stream | """Record compaction (02-ledger section 5.2) -- retention of the *log itself*, distinct from context compaction (which is Cognition's job and operates on what a |
| 5 | Bash | Find retention config wiring, snapshot presence, and history reader bounds | simorgh/ledger/streams.py:18:# `retention` policies in config are keyed by these prefixes. simorgh/ledger/config.py:25: retention: dict = field(default_factory= |
| 6 | Bash | Read the /api/history handler | 582: self.register_route("GET", "/api/history", _json_route(self._history_json)) 1186: async def _history_json(self, query: dict) -> bytes: async def _history_j |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The measurable core of the claim holds today: `metrics%3Ahistory.jsonl` is 119,099,341 bytes / 50,677 events, the largest stream by bytes; `MetricsHistoryWriter._loop` appends one full deep-copied `per_subsystem` table per tick (simorgh/kernel/metrics.py:245-260); `service.py:289-293` wires it to `runtime.metrics_every_s`, default 10.0 (api.py:42) and ~/.simorgh/simorgh.toml has no `[runtime]` override; the last two records are 10 s apart (ts 1789776848 -> 1789776858); avg 2,350 B/event => 20.3 MB per day of uptime (the finding's 19.4 used the rounded 114M). The `/api/history` reader only takes the last 500 events (`_read_tail(self._history_stream, self._history_max_points)`, httpapi.py:1186ff, default 500 = ~83 min at 10 s), so nothing older than ~83 minutes is reachable through the dashboard even though the route accepts `minutes` up to 1440 -- which strengthens the "derivable telemetry nobody reads" point.

What the finding gets wrong is the "no compaction or age cap anywhere" framing and, consequently, the recommendation. The ledger already has a per-prefix retention mechanism: `simorgh/ledger/compaction.py` (`RetentionPolicy`, `run_compaction`), constructed in `ledger/service.py:46` from `[ledger] retention`, and it actually runs -- `ledger%3Acompaction.jsonl` holds 129 `ledger.compacted` passes with `reason: sleep_tick` (6-hourly). It never touches `metrics:history` because `DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"}` (compaction.py:36) has no `metrics:` key, the live toml has no `[ledger]` section, so `window_for("metrics:history")` returns None (= forever), and a forever stream is only truncated if it has a snapshot (compaction.py:93-104); `~/.simorgh/ledger/snapshots` has no metrics snapshot. Every recorded pass shows `events_truncated: 0`. So this is the project's known "unconnected wire" shape (retention slot exists, nobody set it for this stream) rather than a missing subsystem; the fix is one line in `DEFAULT_RETENTION` (e.g. `"metrics:": "1d"`) or a `[ledger] retention` entry, not a rolling file outside the ledger. Kind: genuine bug (a) in defaults, not a design error. Not present in docs/architecture-audit-2026.md or docs/architecture-review-2026-09-18.html (grep for metrics:history / MetricsHistory: no hits), so it is materially new. Severity stays low: boot scan is cheap and it is disk weight only.

**corrected claim:** MetricsHistoryWriter appends a full MetricsTable snapshot every metrics_every_s=10 s to the `metrics:history` stream (119 MB / 50,677 events, the largest stream, ~20 MB per day of uptime). The ledger does have a working per-prefix retention pass (ledger/compaction.py, run 6-hourly; 129 passes logged) but DEFAULT_RETENTION names only `trace:`, `dead:` and `activity`, the live simorgh.toml sets no `[ledger] retention`, and the stream has no snapshot, so it resolves to "forever" and every pass truncates 0 events. Meanwhile `/api/history` only ever reads the last 500 events (~83 min), so nothing older is reachable. Fix: add `"metrics:"` (e.g. "1d") to DEFAULT_RETENTION; no new rolling-file mechanism is needed.

### evidence

- `ls -la ~/.simorgh/ledger/streams/metrics%3Ahistory.jsonl` -> 119099341 bytes; `wc -l` -> 50677; `ls -S | head` -> metrics%3Ahistory first, then curiosity%3Aticks, persona%3Astate; streams/ 696M, blobs/ 325M, 118215 stream files, index.json 12784528 bytes.
- Computed: avg 2350 B/event, 50677 x 10 s = 140.8 h uptime, 20.3 MB/day of uptime; last two records ts 1789776848.06 and 1789776858.06 (10 s apart); last record 2440 B covering 9 subsystems.
- simorgh/kernel/metrics.py:245-260 `snapshot_once` appends Event(stream=HISTORY_STREAM, payload={'metrics': copy.deepcopy(self._metrics.per_subsystem)}) every `self._interval` (max(1.0, interval_s)); no cap/retention in the file (grep retention|compact|truncat|prune: none relevant).
- simorgh/kernel/service.py:285-293 wires ProcessMetricsPublisher and MetricsHistoryWriter to `self.runtime.metrics_every_s`; simorgh/kernel/api.py:42 `metrics_every_s: float = 10.0`; ~/.simorgh/simorgh.toml has sections [voice],[interface],[execution],[cognition...] only -- no [runtime], no [ledger].
- simorgh/ledger/compaction.py:36 `DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"}`; :69-75 `window_for` returns None (forever) when no prefix matches; :90-104 forever streams are only truncated below a snapshot; `ls ~/.simorgh/ledger/snapshots | grep -i metrics` -> nothing.
- simorgh/ledger/service.py:46 `self.policy = RetentionPolicy.parse(config.retention, keep_tail=config.keep_tail)`; :129-132 one pass per sleep tick calls run_compaction. `tail -n 3 ~/.simorgh/ledger/streams/ledger%3Acompaction.jsonl` -> seq 127/128/129, reason sleep_tick, `events_truncated: 0` on every pass, streams_deleted 16894/7267/4476 (trace streams only).
- simorgh/interface/httpapi.py:144-145 `history_default_minutes=10.0, history_max_points=500`; :1186ff `_history_json` clamps minutes to <= 1440 but reads `await self._read_tail(self._history_stream, self._history_max_points)` -> only the last 500 events (~83 min) are ever served.
- grep -n -i 'metrics:history|MetricsHistory' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md -> no hits (not previously reported).

**severity adjustment:** keep

