# refute:correctness:The at-least-once machinery covers 5 sub

*Workflow: review · Phase: Refute · Agent id: `ac407f184ceea7741` · Tool calls: 16*

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
    "title": "The at-least-once machinery covers 5 subscriptions; the other 152 are broadcast with drop-on-error, no backpressure, and no replay path",
    "kind": "right-design-undermined",
    "severity": "medium",
    "claim": "Ack/nack/retry/dead-letter, backpressure and pause apply only to competing-consumer lanes; broadcast lanes drop a raising handler's delivery, accept unbounded queue growth, and keep delivering while paused. The stated justification 'events are facts; the ledger has them' is not implemented: Ledger.tail has no callers and only three views rebuild from the log, so a dropped broadcast is simply lost.",
    "evidence": [
      "grep subscribe sites outside bus/: 157 total, 5 with `group=` (learning/service.py:84, verification/service.py:88, guardian/service.py:171, execution/service.py:209 plus selfcheck)",
      "simorgh/bus/backends/memory.py:275-279 -- `if outcome == \"ack\" or lane.group is None: # broadcast: a failing handler's delivery is dropped (events are facts; the ledger has them)`",
      "simorgh/bus/client.py:196-197 -- backpressure targets are `groups_for(message)`; memory.py:171 pushes to every broadcast heap unconditionally; memory.py:196 pause skips only `lane.group is not None`",
      "`grep -rn \"ledger\\.tail(\" simorgh` -> no callers; rebuild/materialize callers: kernel/scheduler.py:188, learning/service.py:74, planning/service.py:145 only",
      "live bus counters in the last metrics record: `{'published': 206877, 'delivered': 656420, 'acked': 656420, 'dropped': None, 'nacked': None, 'dead': None}`; no dead: streams on disk; ledger `dedupes: 0`"
    ],
    "why_it_matters": "For a single-process agent this asymmetry is tolerable, but it means the design's own safety story (retry or replay) is a fiction for 97% of subscriptions, while the code still pays for the story (idem sidecars, dedupe windows, dead-letter plumbing). A transient LedgerUnavailable at 5% disk inside a broadcast handler silently loses the event.",
    "recommendation": "Pick one honestly: either shrink the memory backend to what is used (broadcast + 5 command lanes, bound broadcast heaps with drop-oldest and a counter, drop the idem sidecar for unkeyed streams), or make the replay story real by having the few subsystems that must not miss events (guardian, execution) rebuild from their streams at start. Surface `dropped` in bus health either way.",
    "confidence": 0.88
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read memory bus backend delivery code |  lane.task = asyncio.create_task(self._dispatch(lane, spec), name=f"bus-memory-{lane_key}") lane.members.append(reg) async def _unsub() -> None: if reg in self. |
| 2 | Bash | Read bus client backpressure code |  # Policy must be checked against THIS client's own identity, fixed at # construction by the Kernel, never against `message.source` -- that # field is just data |
| 3 | Bash | Count subscribe sites and group= usage | (eval):1: no matches found: --include=*.py 0 --- (eval):1: no matches found: --include=*.py --- (eval):1: no matches found: --include=*.py |
| 4 | Bash | Count subscribe sites, group usage, tail and rebuild callers |  161 --- group sites simorgh/learning/service.py:84: self._subs.append(await ctx.bus.subscribe(topics.LEARN_PIPELINE_RUN, self._on_pipeline_run, group="learning |
| 5 | Bash | Read the group subscribe sites and dropped counter surfacing |  self._subs.append(await ctx.bus.subscribe(topics.TASK_BLOCKED, self._on_task_blocked)) self._subs.append(await ctx.bus.subscribe(topics.VERIFY_RESULT, self._on |
| 6 | Bash | Check lane bounds, idempotency sidecar, sqlite backend broadcast handling | 9:expiry (a handler that never returns) is bounded by a per-handler 41: `api.UNBOUNDED` -- a handler whose bound is the work's own.""" 49:class _Entry: 57:class |
| 7 | Bash | Check metrics group lane, Ledger.tail, and ledger.read callers outside ledger |  self._status_sub = None async def start(self) -> None: self._metrics_sub = await self._bus.subscribe(topics.SYSTEM_METRICS, self._on_metrics) self._health_sub  |
| 8 | Bash | Check guardian rebuild source and bus health fields | 21:189- async def stop(self) -> None: 28:204: async def _rebuild_rejected_index(self) -> None: 29:205- events = await self._ctx.ledger.read(REJECTED_STREAM) 32: |
| 9 | Bash | Check live bus backend config, pause semantics, queue depth config | --- factory 15:from .backends.memory import InMemoryBackend 16:from .backends.sqlite import SqliteBackend 25:def default_handler_error(message, exc: BaseExcepti |
| 10 | Bash | Check metrics snapshot fields, tail callers, live bus backend | """Delivery counters and gauges, snapshotted into `system.metrics` (docs/blueprint/subsystems/01-bus.md section 3.2). Plain dicts, no locking: everything that t |
| 11 | Bash | Check design intent for pause and broadcast drop semantics | 25:\| **Event** (pub/sub, broadcast) \| Something happened; anyone may care \| Every subscriber gets a copy \| `task.completed`, `persona.state.changed` \| 52: prior |
| 12 | Bash | Look for dead-letter streams and last metrics record on disk | Exit code 1 blobs heads idem index.json LOCK snapshots streams 7 --- metrics stream (eval):1: no matches found: /Users/saeed/.simorgh/ledger/*metric* |
| 13 | Bash | Check blueprint's stated broadcast drop and pause semantics; dead streams on disk | ## 9. Error handling conventions - Handlers never raise across the bus boundary. An unhandled exception is caught by the Kernel's dispatcher, logged as `system. |
| 14 | Bash | Read last bus counters from the metrics stream on disk | metrics%3Ahistory.jsonl /Users/saeed/.simorgh/ledger/streams/metrics%3Ahistory.jsonl (eval):1: no matches found: /Users/saeed/.simorgh/ledger/streams/metrics%3A |
| 15 | Bash | Check bus-side idempotency plumbing and startup replay in guardian/execution | 144: idempotency_key: str \| None = None, 157: "idempotency_key": idempotency_key, "clock": self._clock, 164: priority=priority, ttl_seconds=ttl_seconds, idempot |
| 16 | Bash | Extract last bus counters from metrics history; check execution startup replay; count dead streams | None no bus record --- execution INFLIGHT startup # the skill's own name in its text can out-score a fresh, accurate # one on lexical similarity alone (live-cau |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The mechanical claims check out against today's code: broadcast lanes drop a raising handler's delivery (simorgh/bus/backends/memory.py:275-279; same in sqlite.py:365-366 and aws.py:243), backpressure only measures competing-consumer depths (client.py:196-201 uses groups_for; memory.py:171 heappushes to every lane with no bound), pause skips only `lane.group is not None` (memory.py:196, sqlite.py:305), only 6 of 161 subscribe sites pass `group=` (the reader missed kernel/metrics.py:91 `group="kernel-status"`), `Ledger.tail` has no production callers, and there are no `dead:` streams on disk. However two load-bearing parts of the framing are wrong. (1) The asymmetry is the documented design, not an implementation undermining it: docs/blueprint/03-contracts-and-messaging.md:358-361 says a raising handler's message is "nacked (commands) or dropped (events)", and docs/blueprint/subsystems/01-bus.md:447 says on `system.pause` "Command dequeue for non-system.* types halts; events continue". So the kind should be a design-decision judgement, not "right-design-undermined". (2) "The replay story is not implemented / a dropped broadcast is simply lost" is overstated: the reader counted only `rebuild/materialize` callers and missed ~37 direct `ledger.read(` callers outside simorgh/ledger/, including exactly the two subsystems the recommendation names: Guardian rebuilds its rejected index from its stream at start (guardian/service.py:169, 204-205) and Execution replays its inflight stream at start and re-publishes `action.result` for interrupted actions (execution/service.py:702-712); memory/store.py, cognition/budget.py, learning/outcomes.py:89 and interface/dispatch.py also read streams back. The `dropped` counter is already emitted in `system.metrics` via Metrics.snapshot (metrics.py:33-38 dumps all counters; client.py:223 increments it), so `'dropped': None` in a record means zero drops, not "not surfaced". I could not locate the bus record in the metrics:history stream to confirm the quoted live counters (unverifiable). What survives as genuinely new and correct: broadcast heaps have no bound and no drop-oldest, publishers are never slowed by a slow broadcast handler, and the design deliberately trades broadcast durability for simplicity. Not in the known-findings list.

### evidence

- simorgh/bus/backends/memory.py:275-279 -- `if outcome == "ack" or lane.group is None: # broadcast: a failing handler's delivery is dropped (events are facts; the ledger has them)`
- simorgh/bus/backends/sqlite.py:365-366 -- `if delivery.group is None: self._ack_row(delivery)  # broadcast: dropped, not retried`
- simorgh/bus/client.py:196-201 -- `_backpressure` awaits only on `groups_for(message)` depths vs `max_queue_depth`; memory.py:165-172 `enqueue` heappushes to every routed lane unconditionally
- simorgh/bus/backends/memory.py:196 -- `if self._state == "paused" and lane.group is not None and not m.type.startswith("system.")`
- `grep -rn "\.subscribe(" simorgh | grep -v ^simorgh/bus/ | wc -l` -> 161; `group=` at learning/service.py:84, verification/service.py:88, guardian/service.py:171, kernel/selfcheck.py:73,123, kernel/metrics.py:91 (6, not 5)
- `grep -rn "\.tail(" simorgh` -> no production callers (only tests/simorgh/ledger/test_backends.py)
- docs/blueprint/03-contracts-and-messaging.md:358-361 -- 'the message is nacked (commands) or dropped (events) -- never re-raised into the publisher' (design intent)
- docs/blueprint/subsystems/01-bus.md:447 -- `system.pause`: 'Command dequeue for non-system.* types halts; events continue; in-flight handlers finish' (design intent)
- simorgh/guardian/service.py:169,204-205 -- `await self._rebuild_rejected_index()` reads `REJECTED_STREAM` from the ledger at start
- simorgh/execution/service.py:702-712 -- `_replay_inflight` reads `INFLIGHT_STREAM` and publishes `action.result` 'interrupted by restart' for started-but-unfinished actions
- `grep -rn "ledger\.read(" simorgh | grep -v ^simorgh/ledger/ | wc -l` -> 37 (memory/store.py, cognition/budget.py, learning/outcomes.py:89, interface/dispatch.py, benchmark/store.py ...)
- simorgh/bus/metrics.py:33-38 -- `snapshot` emits `dict(self.counters)`, which includes `dropped` (client.py:223) whenever it has been incremented
- `ls ~/.simorgh/ledger/streams | grep -c ^dead` -> 0

**severity adjustment:** lower

**corrected claim:** Broadcast subscriptions (155 of 161 subscribe sites) intentionally get fire-and-forget semantics: a raising handler's delivery is dropped (memory.py:275-279, sqlite.py:365-366), publish backpressure measures only competing-consumer lane depth so broadcast heaps are unbounded (client.py:196-201, memory.py:171), and `system.pause` gates only command lanes (memory.py:196). This matches the blueprint (03-contracts §9; 01-bus §8) rather than undermining it, so it is a design decision to evaluate, not a bug. The 'the ledger has them' justification is partially real: Guardian (guardian/service.py:205) and Execution (execution/service.py:703) rebuild their own state from their ledger streams at start, and ~37 other `ledger.read` call sites replay streams, though `Ledger.tail` is unused and there is no generic replay-on-drop path for other broadcast consumers. `dropped` is already emitted in `system.metrics` counters. The residual gaps are the unbounded broadcast heaps (no drop-oldest, no publisher slowdown behind a slow broadcast handler) and the ack/nack/dead-letter machinery being exercised by only 6 lanes.

