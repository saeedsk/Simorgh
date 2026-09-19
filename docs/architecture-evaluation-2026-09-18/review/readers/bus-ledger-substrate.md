# read:bus-ledger-substrate

*Workflow: review · Phase: Read · Agent id: `a715acf78cfb36ac4` · Tool calls: 37*

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
  
  
  CONCERN: the substrate -- Bus, Ledger, and the event-sourcing claim.
  Read simorgh/bus/ (client, core, policy, enforcement, backends), simorgh/ledger/ (client, store, projections, backends/jsonl.py, backends/sqlite.py, compaction), simorgh/contracts/envelope*.py and contracts/topics.py.
  Questions to settle from code: Is the bus really the only path (or do subsystems share objects/ctx)? What are the delivery semantics (at-most-once? ordering? backpressure? what happens when a handler raises or is slow -- there was a 300s per-handler timeout once)? Is "every message is also a ledger event" literally true, and what does that cost (count streams in ~/.simorgh/ledger/streams if present; du -sh)? Are projections actually rebuilt from the log or are there in-memory-only state holders? What does the memory-backend bus do under load (queues, unbounded growth)? Is the SQLite ledger backend used anywhere real? Is the trace:<id> stream design sane at this scale? Is the AWS SNS/SQS backend dead weight? Evaluate: is event-sourcing + message bus the right architecture for a single-process personal agent, and if the design is right, where does the implementation undermine it?
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | List substrate modules and their sizes | simorgh/bus: __init__.py __pycache__ api.py backends client.py config.py enforcement.py factory.py metrics.py policy.py README.md router.py service.py trace.py  |
| 2 | Bash | Read bus and ledger README files | # `simorgh/bus/` — the nervous system Spec: [`docs/blueprint/subsystems/01-bus.md`](../../docs/blueprint/subsystems/01-bus.md). Contracts it speaks: `docs/bluep |
| 3 | Bash | Read bus client |  1 """`BusClient` -- the public Bus every subsystem holds (docs/blueprint/ 2 subsystems/01-bus.md sections 3.4, 5.1, 5.2). This is the ONLY module in 3 `simorgh |
| 4 | Bash | Read memory bus backend |  1 """In-process asyncio backend (docs/blueprint/subsystems/01-bus.md section 2 5.3) -- the guaranteed floor: zero configuration, zero dependencies, 3 every tes |
| 5 | Bash | Read bus api and config |  1 """Internal interfaces of the Bus (docs/blueprint/subsystems/01-bus.md 2 section 3.4). Everything a backend implements and everything the public 3 client dep |
| 6 | Bash | Read bus trace writer and factory |  1 """The trace writer: every message -> Ledger stream `trace:<trace_id>`, 2 sampled per type (docs/blueprint/subsystems/01-bus.md section 5.6; 03 3 section 5 " |
| 7 | Bash | Read bus enforcement, policy, router, service |  1 """Reserved-topology enforcement (docs/blueprint/03 section 3 and section 2 10; 02 section 3). The Kernel wires this policy into every BusClient; 3 the bus o |
| 8 | Bash | Read ledger client, api, projection |  1 """`LedgerClient` -- the `contracts.protocols.Ledger` implementation 2 every subsystem talks to (and the only ledger module a subsystem may 3 import: `02` se |
| 9 | Bash | Read JSONL ledger backend | <persisted-output> Output too large (43.9KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 10 | Bash | Read SQLite ledger backend, factory, config, compaction, streams, service | <persisted-output> Output too large (40.2KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 11 | Bash | Read envelope contract and topics head |  1 """The message envelope (docs/blueprint/03-contracts-and-messaging.md 2 section 2) and the Ledger `Event` shape (section 6), plus canonical 3 JSON so hashes  |
| 12 | Bash | Inspect live config and ledger directory size and stream counts | === toml === [voice] barge_in = false keep_audio = true vad_sensitivity = "high" barge_in_calibrate_ms = 1200 barge_in_speech_ms = 350 barge_in_ratio = 2.8 min_ |
| 13 | Bash | Find kernel wiring of bus and ledger | simorgh/kernel/cli.py:244: from simorgh.ledger.factory import make_ledger simorgh/kernel/cli.py:246: ledger = make_ledger({"backend": "jsonl", "data_dir": str(c |
| 14 | Bash | Read JSONL backend lines 36-420 | 36 import time 37 from collections import OrderedDict 38 from pathlib import Path 39 40 from simorgh.contracts.envelope import Event, canonical_json 41 42 from  |
| 15 | Bash | Read JSONL backend lines 420-815 | 420 # the index exists to remove. 421 cached = self._offsets.get(event.stream) 422 if cached is not None: 423 size_when_built, offsets = cached 424 if size_when |
| 16 | Bash | Measure ledger stream prefixes, idem cache, biggest streams, index load time | === streams by prefix === 88356 trace 26737 action 2431 task 350 verify 310 reflect 5 memory 5 curiosity 5 cognition 3 persona 2 guardian 2 execution 1 voice 1  |
| 17 | Bash | Read kernel context and service wiring section |  1 """Builds the `Context` handed to one subsystem's `Service.start()` 2 (docs/blueprint/subsystems/03-kernel.md section 5). Each subsystem gets 3 its own `BusC |
| 18 | Bash | Map cross-subsystem Python imports | === cross-subsystem imports (subsystem A importing subsystem B, excluding contracts/bus.client/ledger.client) === (eval):1: no matches found: --include=*.py (ev |
| 19 | Bash | Find projections, rebuild callers, and ledger read/append/tail usage by package | === Projection subclasses === (eval):1: no matches found: --include=*.py |
| 20 | Bash | Map cross-subsystem imports and ledger usage by package | === cross-subsystem imports === cognition -> from simorgh.contracts memory -> from simorgh.contracts planning -> ledger execution -> from simorgh.contracts from |
| 21 | Bash | Read compaction, ledger service, idempotency index, and contracts protocols |  1 """Record compaction (02-ledger section 5.2) -- retention of the *log 2 itself*, distinct from context compaction (which is Cognition's job and 3 operates on |
| 22 | Bash | Find kernel backend selection and any real use of sqlite backends | === kernel bus/ledger config helpers === 65:def _bus_config_for(config: LoadedConfig, runtime: RuntimeConfig): 66- """Shared by `Kernel` and `WorkerKernel` so b |
| 23 | Bash | Count subscription styles, wildcard subscribers, tick subscribers, and handler timeout overrides | === subscribe calls: group vs broadcast === 161 5 --- wildcard '#' subscriptions: --- tick.second subscribers: simorgh/memory/service.py:27: topics.SYSTEM_TICK_ |
| 24 | Bash | Measure on-disk vs apparent sizes, stream file ages, and sample the biggest streams | === apparent vs on-disk sizes === streams: files=118215 apparent=389.7MB on_disk=729.8MB idem: files=90755 apparent=5.5MB on_disk=372.2MB blobs: files=42624 app |
| 25 | Bash | Skim sqlite and cloud backends and their test footprint | Exit code 1 40 -- compaction removed every live event, so the next append reused seq 1 41 -- and every reader already past it dropped the new events as ones it  |
| 26 | Bash | Read stream grammar, list competing-consumer subscriptions, find readers of the largest streams |  1 """Stream naming (02-ledger section 4.1): the grammar, the filename 2 escaping the `jsonl` backend uses, and the registry of known prefixes 3 with their owni |
| 27 | Bash | Read kernel factory wiring and metrics history writer cadence | 85:def build_factories( 86- *, bus_client: BusClient, ledger_client: LedgerClient, run_repl: bool = False, 87- execution_config: object \| None = None, guardian_ |
| 28 | Bash | Measure ledger walk/sweep/parse costs, JSONL append latency, and idle bus CPU | (a) streams('') scandir+stat over 118215 files: 0.306s (b) snapshot exists() x118215: 0.372s (0 snapshots) (c) blob sweep read+regex: 10.958s wall, 3.579s cpu,  |
| 29 | Bash | Count subscriptions per package, size the unused backends, check run mode defaults | === real subscription count at boot (subscribe calls in services, excluding tests/bus) === 33 interface 19 worldmodel 18 reflection 14 kernel 12 guardian 10 per |
| 30 | Bash | Read ledger config defaults and kernel cadence settings | === ledger config === 1 """`[ledger]` configuration (02-ledger section 3.5). Loaded by the 2 Kernel from `simorgh.toml`; `SIMORGH_LEDGER_BACKEND` and 3 `SIMORGH |
| 31 | Bash | Find what writes and reads curiosity ticks and execution inflight streams | === curiosity:ticks writer === 47-) 48- 49:_TICKS_STREAM = "curiosity:ticks" 50-_CANDIDATES_STREAM = "curiosity:candidates" 51-_INTERESTS_STREAM = "curiosity:in |
| 32 | Bash | Check persona persistence cadence and HTTP history endpoint read pattern | === persona persist triggers === 211- await self._ctx.bus.publish(Message.new(topics.PERSONA_STATE_CHANGED, source=self._ctx.source, payload=payload)) 212: awai |
| 33 | Bash | Check tools-stream readers, chat handler shape, request timeouts, trace sampling entry, and boot counts | === execution:tools readers === 1:simorgh/orchestration/service.py:21:_TOOLS_STREAM = "execution:tools" 6:simorgh/orchestration/service.py:158: events = await c |
| 34 | Bash | Check worldmodel persistence, partition-key usage, and how many publishes carry causation | === worldmodel ledger usage === (end) === reflection/curiosity ledger reads === (end) === partition_key set by publishers (outside bus/contracts/tests) === 32 1 |
| 35 | Bash | Read the duplicated-stream-constant comment, current free disk, and live bus counters from the last metrics record | # Must match `execution/tools.py::MCP_PROPOSALS_STREAM` -- a plain string # agreement, not a shared import, since `interface` may not import # `execution` (`tes |
| 36 | Bash | Read live compaction reports and bus drop/nack counters | === ledger compaction records (what passes actually removed) === 127 {'events_truncated': 0, 'reason': 'sleep_tick', 'streams_deleted': 16894, 'streams_seen': 1 |
| 37 | Bash | Sum all compaction passes and inspect the module boundary test | compaction passes=129 reasons={'start': 120, 'sleep_tick': 9} streams_deleted=235527 events_truncated=0 blobs_swept=0 === module boundary test === tests/simorgh |

## Structured reply

**concern:** The substrate: Bus, Ledger, and the event-sourcing claim (delivery semantics, trace-per-message cost, projections vs in-memory state, backend dead weight, whether bus+event-sourcing fits a single-process personal agent)

**summary of what is actually there:** The Bus is an in-process asyncio pub/sub (simorgh/bus/backends/memory.py) behind a typed client (simorgh/bus/client.py): publish = validate against the catalog (contracts/envelope.py:163-197) -> policy checked against the client's fixed identity (client.py:184) -> backpressure -> trace -> enqueue. Every subscription gets its own lane with a priority heap and a dispatcher task; competing-consumer lanes (group=) get ack/nack/retry(1,2,4,8s)/dead-letter, broadcast lanes drop a raising handler's delivery outright (memory.py:275-279) and are exempt from backpressure (client.py:196-197 measures only groups_for). Only 5 of 157 subscribe sites use group= (guardian action.proposed, execution action.approved, learning, verification); the other 152 are broadcast. Per-handler timeout is still 300s by default (config.py:36) except the two UNBOUNDED handlers (execution/service.py:209, orchestration/worker.py:215); chat turns are spawned as tasks (orchestration/service.py:279) so they are not bound. Ordering is per partition_key within a lane, with up to 16 handlers in flight per subscription (api.py:66); only 32 publish sites set a partition_key, all in planning/orchestration/verification/benchmark. A 5 ms ticker wakes every lane (memory.py:132-139). "Every message is a ledger event" is literally true: TraceWriter (bus/trace.py:97-108) writes each published message, minus seven zero-sampled heartbeat types, to stream trace:<trace_id>, and an uncaused message gets a fresh uuid4 trace_id (envelope.py:98), so every uncaused broadcast becomes its own one-event stream. The Ledger is one shared LedgerClient handed to every subsystem via Context.ledger (kernel/context.py:141); the live backend is JSONL (no [ledger]/[bus] section in ~/.simorgh/simorgh.toml, defaults jsonl + memory), one fsync'd file per stream plus one idempotency sidecar per keyed stream (backends/jsonl.py:397-437, 442-449), all file I/O synchronous inside async methods on the event loop. Projections rebuilt from the log exist for exactly three views: kernel/scheduler.py:89 ScheduleView, learning/service.py:74 (learn:outcomes), planning/service.py:145 (task streams, the only snapshot on disk); everything else is either a journal written and read in full at boot (execution:inflight, execution:tools), a journal written and never read (curiosity:ticks, reflect:*), or pure in-memory state (worldmodel has zero ledger calls across 19 subscriptions). Ledger.tail() has zero callers. Retention (ledger/compaction.py:36) covers only trace: (2d), dead:, activity; every other stream is "forever" and is only truncated if it has a snapshot, which one stream does; across all 129 recorded compaction passes events_truncated=0 and 235,527 trace streams were deleted. The sqlite/aws bus backends and sqlite/dynamodb ledger backends, WorkerKernel and IdentityRegistry exist and are tested against fakes but nothing outside tests selects them.

### strengths

- Module boundaries are enforced by a test, not convention: tests/simorgh/test_module_boundaries.py:139 test_no_subsystem_imports_another; the import map confirms no subsystem imports another (only contracts, bus.client, ledger.client), and the kernel is the sole composer (kernel/registry.py:85-157).
- Policy is checked against the client's construction-time identity, not the envelope's source field (bus/client.py:170-184), closing the spoofing hole found live 2026-09-08; replies are point-to-point (bus/router.py:49-50) so one requester's answers never fan out.
- Handler exceptions are loud by default (bus/factory.py:25-52 default_handler_error prints and tracebacks to stderr unconditionally) and the request future is cleaned up when publish itself rejects (client.py:270-282) -- both are lessons from real incidents encoded where they bite.
- JSONL crash-safety discipline is careful and asymmetric on purpose: only a trailing partial line is truncated, an interior unparseable line is kept as a gap (jsonl.py:276-352, 516-526), head never regresses via durable marks (jsonl.py:117-150), rewrites are tmp->fsync->replace (jsonl.py:698-709).
- Boot no longer scans every stream: index.json + one stat per stream (jsonl.py:215-247); measured 0.306 s to scandir+stat 118,215 files and 0.078 s to load the 12.8 MB index.
- Append itself is cheap on this machine even with fsync: 0.13 ms/append to one stream, 0.23 ms to a new stream (measured); the per-record cost is not the problem, the file count is.
- Retention actually runs now (config.py:31 compact_after_start_s=30 plus the 6 h sleep tick): 129 passes recorded, nothing in trace: older than 2 days (age histogram 46,264 / 28,286 / 13,806 for days 0/1/2).
- The trace writer never blocks publish: bounded queue, drop counter, degraded buffer with replay (bus/trace.py:78-158).

### findings

##### 1. Compaction's blob sweep reads the entire ledger synchronously on the event loop, 30 s after every boot and every 6 h

- **kind:** bug
- **severity:** high
- **claim:** sweep_unreferenced_blobs reads every stream file's bytes with plain open().read() inside an async method with no to_thread, and the ledger Service awaits it on the event loop, so the whole process (voice, TUI, HTTP, every bus handler) stalls for roughly ten seconds at +30 s after each boot and on each sleep tick.
- **evidence:**
  - simorgh/ledger/backends/jsonl.py:739-753 -- `for subdir in ("streams", "snapshots"): ... data = Path(entry.path).read_bytes()` with no to_thread
  - simorgh/ledger/service.py:141-144 -- `sweep = getattr(self.client.backend, "sweep_unreferenced_blobs", None) ... payload["blobs_swept"] = await sweep()`
  - simorgh/ledger/service.py:65 and simorgh/ledger/config.py:31 -- first pass is `asyncio.create_task(self._compact_after_start())` after `compact_after_start_s: float = 30.0`
  - measured in isolation on the live ledger dir: `(c) blob sweep read+regex: 10.958s wall, 3.579s cpu, 390MB, 21312 refs`
  - ledger:compaction stream: `compaction passes=129 reasons={'start': 120, 'sleep_tick': 9}` -- 120 boots each paid this
  - run_compaction's per-stream loop is also synchronous: `(a) streams('') scandir+stat over 118215 files: 0.306s`, `(b) snapshot exists() x118215: 0.372s`
- **why it matters:** A ten-second freeze of the single event loop is exactly the 'Sim went silent' symptom; it lands right when the creator has just restarted and is typing or talking. The known finding 'STT latency degrades under self-inflicted load' has this as one concrete, periodic source.
- **recommendation:** Run run_compaction + sweep under asyncio.to_thread (the JSONL backend is synchronous anyway and holds its own locks), and only sweep blobs when the pass actually deleted or truncated something. Longer term keep a per-blob reference count updated at append/delete time instead of rescanning 390 MB.
- **confidence:** 0.92

##### 2. One file plus one sidecar per trace_id: 76% of trace streams hold a single event, and block slack makes 575 MB of data occupy 1.44 GB

- **kind:** wrong-design
- **severity:** high
- **claim:** Keying trace storage by trace_id, combined with a fresh uuid4 trace_id for every uncaused publish, turns every periodic broadcast (ui.notice, persona.state.changed, ui.hook.received, world.camera.event, voice.listening, system.status.request) into its own stream file and its own idempotency sidecar; at this scale the cost is inode churn and filesystem block slack, not bytes, and the zero-sample exclusion list is whack-a-mole.
- **evidence:**
  - simorgh/bus/trace.py:102 -- `stream=f"trace:{message.trace_id}"`; simorgh/contracts/envelope.py:98 -- `trace_id=trace_id or str(uuid.uuid4())`
  - simorgh/ledger/backends/jsonl.py:442-449 -- `_append_idem_line` writes `<root>/idem/<stream>.idx` for every keyed event; trace events are keyed by message.id (trace.py:107)
  - index.json: `trace streams=88356 head==1: 67421 (76%), median head 1.0, max 1195`
  - root-type sample of 400 trace streams: `ui.notice 57, persona.state.changed 51, ui.hook.received 49, world.camera.event 42, voice.listening 37, system.status.request 31`
  - on-disk vs apparent: `streams: files=118215 apparent=389.7MB on_disk=729.8MB`, `idem: files=90755 apparent=5.5MB on_disk=372.2MB`, `blobs: files=42624 apparent=179.8MB on_disk=340.4MB`
  - trace age histogram (2-day window): `0d: 46264, 1d: 28286, 2d: 13806` -- about 40k new stream files per day, 235,527 deleted across 129 passes
  - simorgh/bus/config.py:63 `"_inbox.#": 0.0` is dead config: `matches(_inbox.#, cognition.think.reply) = False`, `sample_rate(cognition.think.reply) = 1.0`
  - live ledger gauge in the last metrics:history record: `free_fraction 0.0833973484195818` (degraded threshold is 0.05, ledger/service.py:25)
- **why it matters:** The 1.4 GB ledger the earlier reviews reported is ~60% filesystem slack from tiny files; the idem sidecars alone cost 372 MB of disk for 5.5 MB of data, and none of that dedupe ever fires in production (ledger counters `dedupes: 0`). The disk is at 8% free and heading for the 5% degraded line, and every compaction pass walks and unlinks tens of thousands of files on the loop.
- **recommendation:** Traces are a query index, not a stream. Either (a) write traces to one stream per hour (trace:2026-09-18-17) and keep an in-memory trace_id -> (stream, seq) map for the `trace` command, or (b) move the ledger to the already-built, parity-tested sqlite backend (simorgh/ledger/backends/sqlite.py, to_thread'd, one file, (stream,seq) PK) and add a `ledger dump <stream>` command for readability. Also stop tracing messages that neither have a causation_id nor are ever caused-from, and delete the dead `_inbox.#` entry.
- **confidence:** 0.93

##### 3. Retention only ever deletes trace streams; every journal stream grows forever because truncation requires a snapshot and one snapshot exists

- **kind:** right-design-undermined
- **severity:** high
- **claim:** The compaction design (snapshot + keep_tail for forever streams, windows for the rest) is sound, but DEFAULT_RETENTION names only trace/dead/activity and the forever path is a no-op without a snapshot, so metrics:history, curiosity:ticks, persona:state, execution:inflight, execution:tools and config:effective are append-forever; in 129 recorded passes not one event was ever truncated.
- **evidence:**
  - simorgh/ledger/compaction.py:36 -- `DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"}`; compaction.py:93-98 -- `if window is None: snapshot = await backend.read_snapshot(stream); if snapshot is None: continue`
  - `ls ~/.simorgh/ledger/snapshots` -> 1 file (planning%3Aindex.json); heads/ empty
  - ledger:compaction over all passes: `streams_deleted=235527 events_truncated=0`
  - metrics:history: 119,099,341 bytes, 50,677 events, written every 10 s (kernel/metrics.py:218-258, kernel/api.py:42 `metrics_every_s: float = 10.0`); /api/history reads only the last 10 minutes (interface/httpapi.py:144)
  - curiosity:ticks: 45,068,994 bytes, 161,096 events, last one `"skipped_reason":"autonomy_paused"`; written at curiosity/service.py:584 and :175, read nowhere (grep for readers returns only the constant)
  - persona:state: 17,819,390 bytes, 47,784 events; persona/service.py:155-157 reads only the head event at start
  - execution:inflight: 10,150,896 bytes, 53,406 events; execution/service.py:702-703 `events = await self._ctx.ledger.read(INFLIGHT_STREAM)` reads all of it at every boot; execution:tools 20,110 lines read in full at orchestration/service.py:158 and interface/dispatch.py:1236
  - config:effective: 248 boot records, 4,025,584 bytes
- **why it matters:** This is the substrate-level instance of the project's 'unconnected wire': compaction waits for snapshots that no subsystem writes. The journals are the biggest byte consumers after trace (metrics 119 MB, curiosity 45 MB) and grow without bound on an 8%-free disk; the ones read in full at boot make boot time a function of lifetime history.
- **recommendation:** Make retention windows the default for journal-shaped streams (metrics: 7d, curiosity:ticks 1d or do not append a tick that did nothing, config:effective keep last N) and let compaction truncate a snapshot-less singleton stream to keep_tail when a window is set. For execution:inflight and execution:tools, either snapshot (they are trivially foldable) or read from a bounded tail.
- **confidence:** 0.95

##### 4. The at-least-once machinery covers 5 subscriptions; the other 152 are broadcast with drop-on-error, no backpressure, and no replay path

- **kind:** right-design-undermined
- **severity:** medium
- **claim:** Ack/nack/retry/dead-letter, backpressure and pause apply only to competing-consumer lanes; broadcast lanes drop a raising handler's delivery, accept unbounded queue growth, and keep delivering while paused. The stated justification 'events are facts; the ledger has them' is not implemented: Ledger.tail has no callers and only three views rebuild from the log, so a dropped broadcast is simply lost.
- **evidence:**
  - grep subscribe sites outside bus/: 157 total, 5 with `group=` (learning/service.py:84, verification/service.py:88, guardian/service.py:171, execution/service.py:209 plus selfcheck)
  - simorgh/bus/backends/memory.py:275-279 -- `if outcome == "ack" or lane.group is None: # broadcast: a failing handler's delivery is dropped (events are facts; the ledger has them)`
  - simorgh/bus/client.py:196-197 -- backpressure targets are `groups_for(message)`; memory.py:171 pushes to every broadcast heap unconditionally; memory.py:196 pause skips only `lane.group is not None`
  - `grep -rn "ledger\.tail(" simorgh` -> no callers; rebuild/materialize callers: kernel/scheduler.py:188, learning/service.py:74, planning/service.py:145 only
  - live bus counters in the last metrics record: `{'published': 206877, 'delivered': 656420, 'acked': 656420, 'dropped': None, 'nacked': None, 'dead': None}`; no dead: streams on disk; ledger `dedupes: 0`
- **why it matters:** For a single-process agent this asymmetry is tolerable, but it means the design's own safety story (retry or replay) is a fiction for 97% of subscriptions, while the code still pays for the story (idem sidecars, dedupe windows, dead-letter plumbing). A transient LedgerUnavailable at 5% disk inside a broadcast handler silently loses the event.
- **recommendation:** Pick one honestly: either shrink the memory backend to what is used (broadcast + 5 command lanes, bound broadcast heaps with drop-oldest and a counter, drop the idem sidecar for unkeyed streams), or make the replay story real by having the few subsystems that must not miss events (guardian, execution) rebuild from their streams at start. Surface `dropped` in bus health either way.
- **confidence:** 0.88

##### 5. The 5 ms wake-all ticker costs ~5% of a core when the system is idle

- **kind:** bug
- **severity:** medium
- **claim:** InMemoryBackend wakes every lane's dispatcher every 5 ms so a retry can become ready without a timer, which with the live system's ~170 lanes is ~34,000 coroutine resumptions per second doing nothing; retries have a minimum 1 s backoff, so the tick is 200x finer than anything it serves.
- **evidence:**
  - simorgh/bus/backends/memory.py:82 `tick_seconds: float = 0.005`; :132-139 `_tick_loop ... self._wake_all()` sets every lane's Event
  - memory.py:299 backoff `min(60.0, 2.0 ** (entry.attempt - 1))` -> 1, 2, 4, 8 s
  - measured: `(h) InMemoryBackend idle, 170 lanes, tick=0.005s: 5.6% of one core` vs `tick=1.0s: 0.0% of one core`
  - 157 subscribe sites plus one inbox lane per requesting client (client.py:247-252) ~ 170 lanes at boot
- **why it matters:** On a laptop that also runs STT/TTS and camera decoding, a permanent 5% idle tax from the bus is pure waste and shows up as heat, battery, and the already-reported STT latency under load.
- **recommendation:** Replace the global tick with per-lane `loop.call_at(retry_at)` wakeups (only lanes holding a retry-pending entry need a timer), or at minimum raise tick_seconds to 0.25 s; retry_after from explicit nack is the only sub-second case and can schedule its own timer.
- **confidence:** 0.9

##### 6. Broadcast subscriptions run up to 16 handlers concurrently and almost nobody sets a partition_key, so per-subscriber ordering is not guaranteed

- **kind:** right-design-undermined
- **severity:** medium
- **claim:** Ordering is designed per partition_key, but only 32 publish sites set one (all in planning/orchestration/verification/benchmark); every other subscription (voice, interface, persona, worldmodel, memory...) dispatches up to max_inflight=16 handlers of the same subscriber concurrently, so two consecutive voice.transcript or ui.* events can interleave at every await and complete out of order.
- **evidence:**
  - simorgh/bus/api.py:66 `max_inflight: int = 16`; simorgh/bus/backends/memory.py:215-240 `while lane.inflight < max_inflight: ... task = asyncio.create_task(self._run(...))`
  - memory.py:199 and :231-232 -- only `m.partition_key is not None` entries take the lane's partition lock
  - `grep -rn "partition_key=" simorgh` outside bus/contracts (non-None): 32 sites -- planning/service.py 16, orchestration/worker.py 4, orchestration/session.py 4, verification/service.py 3, benchmark 4, planning/scheduler.py 1; zero in interface, voice, persona, memory, worldmodel
  - memory note (project history): 'per-turn fact in a session singleton read across an await; failed both directions 2026-09-18' is the symptom shape this produces
- **why it matters:** Most handlers mutate in-memory state without locks and assume one-at-a-time delivery; the bus silently gives them 16-way concurrency. This is a source of Heisenbugs that unit tests (single message at a time) never see.
- **recommendation:** Default max_inflight=1 for broadcast subscriptions (a subscriber that wants concurrency opts in explicitly), and keep partition keys as the concurrency knob for the competing-consumer lanes where they are already used.
- **confidence:** 0.72

##### 7. The Ledger is a second, untyped, unguarded channel between subsystems, and 'all state in the ledger' is true for three views only

- **kind:** wrong-design
- **severity:** medium
- **claim:** Every subsystem receives the same LedgerClient with no source binding and no writer enforcement; stream names are plain-string agreements duplicated across packages; several subsystems keep pure in-memory state (worldmodel persists nothing), others write journals nobody reads, and only three views are rebuilt from the log -- so the bus is not the only path and the event-sourcing claim is a journal with three projections.
- **evidence:**
  - simorgh/kernel/context.py:141 -- `Context(... bus=bus, ledger=self._ledger ...)` -- one shared client, versus a per-subsystem BusClient with fixed source (context.py:113)
  - simorgh/ledger/streams.py:16-17 -- `Prefix -> owning subsystem. Informational (the Ledger does not enforce writers`
  - simorgh/interface/dispatch.py:50-70 -- six stream constants documented as 'a plain string agreement, not a shared import'; same constants at execution/service.py:62-63 and orchestration/service.py:21
  - `grep -rn "ledger\." simorgh/worldmodel` -> no matches, while worldmodel has 19 subscribe sites; reflection and curiosity: 0 ledger.read/head calls, 310 reflect: and 5 curiosity: streams on disk
  - Projection subclasses in the whole tree: `simorgh/kernel/scheduler.py:89:class ScheduleView(Projection)` only; rebuild callers: learning/service.py:74, planning/service.py:145, kernel/scheduler.py:188
- **why it matters:** The typed bus catalog and the boundary test are the project's best architectural asset, and the ledger quietly bypasses both: a stream name typo or a foreign write is invisible, and the Guardian audit trail (action:* streams, 26,737 of them) is writable by anyone holding ctx.ledger. It also means a restart loses camera/presence/world state entirely while 45 MB of never-read curiosity ticks are fsync'd to disk.
- **recommendation:** Move stream names and owners into contracts (contracts/streamnames.py already holds the grammar) and hand each subsystem a LedgerClient bound to its source that refuses writes outside its prefixes (reads stay open). Then decide per subsystem, explicitly: projection (rebuild at boot), journal (window retention), or ephemeral (do not write). Worldmodel should be a projection; curiosity:ticks should not exist.
- **confidence:** 0.85

##### 8. Multi-process and cloud substrate (sqlite bus, SNS/SQS, DynamoDB, WorkerKernel, identity tokens, tail polling) is never used and its security premise is documented as unfinished

- **kind:** over-engineering
- **severity:** medium
- **claim:** About 2,000 lines of backends plus 740 test lines, WorkerKernel, IdentityRegistry, the durable flag, cross_process polling and Ledger.tail exist for local-multi/aws modes that nothing selects, while their abstractions leak into the single-process path (an extra stat per append because jsonl declares cross_process=True; tail's poll loop; durable accepted and ignored).
- **evidence:**
  - ~/.simorgh/simorgh.toml has no [bus] or [ledger] section -> defaults `backend: str = "memory"` (bus/config.py:30) and `backend: str = "jsonl"` (ledger/config.py:18); kernel/api.py:34 `mode: str = "single"`
  - grep for sqlite/aws/dynamodb backend selection outside tests and the backends themselves: only docstrings (kernel/service.py:70, :546, :574)
  - wc -l: bus/backends/sqlite.py 422, bus/backends/aws.py 269, ledger/backends/sqlite.py 275, ledger/backends/dynamodb.py 282, tests 740; WorkerKernel = 135 lines from kernel/service.py:570
  - kernel/service.py:593-595 -- 'is *not*, and today cannot be, the same secret the main process's own IdentityRegistry holds: policy is enforced client-side, per process ... unfinished'
  - bus/backends/sqlite.py:18-21 -- 'DB calls are synchronous on the event loop' (its own docstring), contradicting the ledger sqlite backend's to_thread design
  - jsonl.py:71 `cross_process = True` -> `_refresh_if_grown` stat on every append (jsonl.py:402) and every find_by_idempotency (jsonl.py:452); `Ledger.tail` (contracts/protocols.py:58, ledger/client.py:199-224) has zero callers
- **why it matters:** For one laptop and one family this is maintenance surface without a user: every ledger change must keep four backends in parity, and the interfaces carry flags that lie (durable). The one piece that would actually help today -- the sqlite ledger backend, for the tiny-file problem -- is the part not being used.
- **recommendation:** Delete the aws bus backend, dynamodb backend, WorkerKernel and identity-token paths (git keeps them); drop tail/durable/cross_process from the protocols. Keep exactly two ledger backends, memory for tests and sqlite for the laptop, and promote sqlite to the default once traces move there.
- **confidence:** 0.85

##### 9. The compaction record never contains blobs_swept

- **kind:** bug
- **severity:** low
- **claim:** The Service builds `payload` with blobs_swept but appends `report.as_payload()` to ledger:compaction, so the audit record omits what the sweep removed.
- **evidence:**
  - simorgh/ledger/service.py:134 `payload = report.as_payload()`, :144 `payload["blobs_swept"] = await sweep()`, :150-155 appends `**report.as_payload()` not `**payload`
  - all 129 ledger:compaction records: `blobs_swept=0`, while the last metrics:history record shows `'last_compaction': {'blobs_swept': 147, ...}`
- **why it matters:** Small, but the stream exists precisely so forgetting is auditable, and the field it forgets is the one deletion that is irreversible (blobs are content-addressed and shared).
- **recommendation:** Append `payload` instead of `report.as_payload()`.
- **confidence:** 0.95


### measurements

- `du -sh ~/.simorgh/ledger` -> 1.4G; by dir: streams 696M, idem 355M, blobs 325M, index.json 12M
- apparent vs on-disk: `streams: files=118215 apparent=389.7MB on_disk=729.8MB`; `idem: files=90755 apparent=5.5MB on_disk=372.2MB`; `blobs: files=42624 apparent=179.8MB on_disk=340.4MB`
- streams by prefix: trace 88356, action 26737, task 2431, verify 350, reflect 310, memory 5, curiosity 5, cognition 5, persona 3, guardian 2, execution 2
- bytes by prefix (index.json): trace 144,289,993; metrics 119,099,341; curiosity 45,075,623; action 22,069,453; execution 18,449,741; persona 17,819,923; task 6,210,592
- `trace streams=88356 head==1: 67421 (76%), median head 1.0, max 1195`; `action streams=26737 median head 3 median bytes 799`
- trace root types, 400-file sample: ui.notice 57, persona.state.changed 51, ui.hook.received 49, world.camera.event 42, voice.listening 37, system.status.request 31, action.proposed 23, tool.invoked 21, tool.registered 20
- trace file age: 0d 46264, 1d 28286, 2d 13806 (2-day retention working; ~40k new stream files/day)
- `(c) blob sweep read+regex: 10.958s wall, 3.579s cpu, 390MB, 21312 refs`
- `(a) streams('') scandir+stat over 118215 files: 0.306s`; `(b) snapshot exists() x118215: 0.372s (0 snapshots)`; `index load s 0.078 entries 118215`
- `(d) full parse metrics:history 50677 lines: 0.659s wall` (119 MB, one record every 10 s)
- `(g1) 300 appends to NEW trace streams (fsync): 0.23 ms/append`; `(g2) ONE stream (fsync): 0.13 ms/append`; `(g3) ONE stream (no fsync): 0.11 ms/append`
- `(h) InMemoryBackend idle, 170 lanes, tick=0.005s: 5.6% of one core`; `tick=1.0s: 0.0% of one core`
- compaction history: `passes=129 reasons={'start': 120, 'sleep_tick': 9} streams_deleted=235527 events_truncated=0 blobs_swept=0`; last three sleep passes deleted 16894 / 7267 / 4476 streams
- live counters (last metrics:history record): bus `published 206877, delivered 656420, acked 656420`, no dropped/nacked/dead keys; ledger `appends 60111, conflicts 0, dedupes 0, blobs_put 323`; `free_fraction 0.0834`, `events 559169`, `streams 102443`
- `df -h ~` -> 460Gi total, 39Gi free (92% used)
- subscribe sites outside bus/: 157 (interface 33, worldmodel 19, reflection 18, kernel 14, guardian 12, persona 10, ...); 5 with group=; partition_key set at 32 publish sites; `ledger.tail(` callers: 0; Projection subclasses: 1
- unused-backend code: bus sqlite 422 + aws 269 + ledger sqlite 275 + dynamodb 282 lines; tests 740 lines; WorkerKernel 135 lines
- `matches('_inbox.#','cognition.think.reply') = False`; `sample_rate('cognition.think.reply') = 1.0`
- config:effective 248 boot records / 4,025,584 bytes; execution:tools 20,110 lines / 8,298,845 bytes; execution:inflight 53,406 lines / 10,150,896 bytes; curiosity:ticks 161,096 lines; persona:state 47,784 lines; snapshots dir: 1 file; heads dir: 0 files

