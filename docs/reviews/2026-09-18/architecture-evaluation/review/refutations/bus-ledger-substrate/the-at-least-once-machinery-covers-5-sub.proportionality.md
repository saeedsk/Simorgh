# refute:proportionality:The at-least-once machinery covers 5 sub

*Workflow: review · Phase: Refute · Agent id: `a6573895925969da3` · Tool calls: 18*

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
| 1 | Bash | Read memory bus backend dispatch and pause logic |  lane.task = asyncio.create_task(self._dispatch(lane, spec), name=f"bus-memory-{lane_key}") lane.members.append(reg) async def _unsub() -> None: if reg in self. |
| 2 | Bash | Read bus client backpressure logic |  # Policy must be checked against THIS client's own identity, fixed at # construction by the Kernel, never against `message.source` -- that # field is just data |
| 3 | Bash | Count subscribe sites, group lanes, tail and rebuild callers | (eval):1: no matches found: --include=*.py 0 --- (eval):1: no matches found: --include=*.py --- (eval):1: no matches found: --include=*.py --- (eval):1: no matc |
| 4 | Bash | Count subscribe sites, group lanes, tail/rebuild callers |  161 --- group= simorgh/learning/service.py:84: self._subs.append(await ctx.bus.subscribe(topics.LEARN_PIPELINE_RUN, self._on_pipeline_run, group="learning")) s |
| 5 | Bash | Look for ledger read APIs, dropped counter in health, durable flag use | simorgh/ledger/api.py:74: async def read(self, stream: str, *, from_seq: int, limit: int \| None) -> list[Event]: ... simorgh/ledger/client.py:189: async def rea |
| 6 | Bash | Inspect idem sidecar, dedupe window and queue depth config | 5:One priority heap per competing group and one per broadcast 23:import heapq 62: heap: list[_Entry] = field(default_factory=list) 67: dedupe: OrderedDict = fie |
| 7 | Bash | Check ledger.read callers, bus health surface, handler_error consumers | --- ledger.read callers simorgh/benchmark/store.py:67: events = await self._ledger.read(STREAM) simorgh/benchmark/store.py:101: events = await self._ledger.read |
| 8 | Bash | List bus package and read metrics module | __init__.py __pycache__ api.py backends client.py config.py enforcement.py factory.py metrics.py policy.py README.md router.py service.py trace.py --- metrics " |
| 9 | Bash | Inspect live ledger streams and bus metrics values | blobs heads idem index.json LOCK snapshots streams --- metrics stream (eval):1: no matches found: /Users/saeed/.simorgh/ledger/*metric* --- dead streams --- bac |
| 10 | Bash | Read live bus metrics record and check for dead streams | Exit code 1 118215 action%3Ab67584acdead.jsonl metrics%3Ahistory.jsonl task%3A30d75067-9341-4a85-8df9-c7deadccafa7.jsonl trace%3A063ddead-d335-49cc-91e2-17c0752 |
| 11 | Bash | Check guardian/execution subscription types and error hooks | simorgh/guardian/service.py:171: self._subs.append(await ctx.bus.subscribe(topics.ACTION_PROPOSED, self._on_proposed, group="guardian")) --- guardian ledger wri |
| 12 | Bash | Read bus factory wiring and README on broadcast drop semantics | from .trace import TraceWriter Clock = Callable[[], float] def default_handler_error(message, exc: BaseException) -> None: """Say that a subscriber raised, on s |
| 13 | Bash | Extract live bus counters and handler-error prints from logs | --- "queue_depth.verification":0 "queue_depth.workers":0 "queue_depth.execution":0 "queue_depth.guardian":0 "queue_depth.kernel-status":0 "queue_depth.learning" |
| 14 | Bash | Check blueprint's stated broadcast semantics and live bus backend | 21:commands at-least-once with acknowledgement and dead-lettering, preempts 32:- Consumer groups (competing consumers) versus broadcast subscriptions. 34:- Ack/ |
| 15 | Bash | Read blueprint broadcast semantics and live bus counter values | ``` ### 5.2 Delivery semantics (all backends) - **Broadcast (`group=None`)**: each matching subscription gets its own delivery; auto-ack after the handler retur |
| 16 | Bash | Tally subscribe sites per subsystem and inspect idem sidecar wiring | --- subscribe sites by subsystem 33 interface 19 worldmodel 18 reflection 15 kernel 12 guardian 10 persona 9 execution 8 learning 7 orchestration 6 voice 6 memo |
| 17 | Bash | Search whole metrics history for dropped/nacked/dead counters | 50677 --- any dropped ever 22 20 "dropped":1 2 "dropped":2 --- any nacked/dead ever 1061 "nacked":2 |
| 18 | Bash | Show latest bus counters and which types were dropped | "counters":{"acked":656420,"delivered":656420,"published":206877} |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The mechanics the finding describes are all real in the code I read: memory.py:275-279 auto-acks and drops a raising broadcast handler; client.py:196-201 backpressure targets only `groups_for(message)` while memory.py:171 pushes to every broadcast heap unconditionally with no bound; memory.py:196 pause skips only `lane.group is not None`; `ledger.tail(` has zero callers outside simorgh/ledger; rebuild/materialize have only three callers. The live metrics history confirms the quoted counters exactly (`acked:656420, delivered:656420, published:206877`). However, the finding mischaracterises the situation in four ways. (1) It is not a "right design undermined" -- it is the documented design: docs/blueprint/subsystems/01-bus.md section 5.2 specifies broadcast as "auto-ack ... a handler exception is logged, counted, and the delivery is dropped", and section 7 says backpressure deliberately targets consumer groups. So the correct kind is "design decision", and the question is whether that decision is wrong at this scale. (2) Drops are not silent: bus/factory.py:24-52 installs `default_handler_error` which prints the exception and traceback to stderr unconditionally, client.py:223 increments a `dropped` counter, and bus/metrics.py:33-38 dumps all counters into the `system.metrics` snapshot -- the live history contains 22 records with `"dropped":1` or `2`, so the recommendation "surface dropped in bus health" is already implemented (the counter is just absent when zero because of defaultdict). (3) Counts are slightly off: 161 subscribe sites, 8 with `group=` (the finding missed orchestration/worker.py:214 `group="workers"` and kernel/metrics.py:91 `group="kernel-status"`, both multi-line). (4) "Replay story is a fiction" overstates: `ledger.read(` has ~20 callers (memory/store.py x5, interface/dispatch.py x7, benchmark/store.py, cognition/budget.py, memory/recall.py, learning/outcomes.py) that rebuild state from streams on demand; what does not exist is replay of bus *messages* to *subscribers*, which the blueprint never promised. On the lens question: for a single asyncio process on one laptop, drop-on-error for broadcast events is the standard pattern -- retrying event handlers produces duplicate side effects, and the observed loss rate is roughly 20-30 drops across 656k deliveries with every queue depth gauge at 0. The unbounded broadcast heap is theoretical at this throughput. The "idem sidecar" cost cited is a Ledger feature (5 streams, ~355 MB in ~/.simorgh/ledger/idem) unrelated to the bus's dedupe window (a 5000-entry OrderedDict per lane). The at-least-once machinery is ~100 lines and is used by exactly the lanes that matter (guardian, execution, workers, verification, learning); removing it would save little and cost the safety it provides. Recommending guardian/execution rebuild from streams is moot: both already run on competing lanes with retry and dead-letter, and guardian appends each decision to a per-action ledger stream (guardian/service.py:547,583). The one legitimately open item is a bounded broadcast heap with an overflow counter -- a small change, low urgency.

### evidence

- simorgh/bus/backends/memory.py:275-279 -- `if outcome == "ack" or lane.group is None:` then `# broadcast: a failing handler's delivery is dropped (events are facts; the ledger has them)` -- CONFIRMED
- simorgh/bus/client.py:196-201 -- `_backpressure` uses `groups_for(message)`; simorgh/bus/backends/memory.py:165-172 `enqueue` heappushes to every routed lane with no depth check -- CONFIRMED unbounded broadcast heaps
- simorgh/bus/backends/memory.py:196 -- `if self._state == "paused" and lane.group is not None and not m.type.startswith("system.")` -- CONFIRMED pause skips broadcast
- `grep -rn '\.subscribe(' simorgh | grep -v '^simorgh/bus/' | wc -l` -> 161; with `group=` (incl. multi-line): learning/service.py:84, verification/service.py:88, guardian/service.py:171, kernel/selfcheck.py:73,123, execution/service.py:209, orchestration/worker.py:214 (workers), kernel/metrics.py:91 (kernel-status) -> 8, not 5
- `grep -rn 'ledger\.tail(\|\.tail(' simorgh | grep -v '^simorgh/ledger/'` -> empty -- CONFIRMED no tail callers; rebuild/materialize callers: learning/service.py:74, planning/service.py:145, kernel/scheduler.py:188 -- CONFIRMED
- `grep -rn 'ledger\.read(' simorgh | grep -v '^simorgh/ledger/'` -> 20 call sites (memory/store.py:395,448,484,514,520; interface/dispatch.py:758,1236,1393,1471,1534,1599,1638; benchmark/store.py:67,101; cognition/budget.py:62; memory/recall.py:212,256; learning/outcomes.py:89; httpapi.py:1182-1183) -- state rebuild from ledger streams is real, just via read() not tail()
- docs/blueprint/subsystems/01-bus.md:254-257 -- 'Broadcast (group=None): ... auto-ack after the handler returns; a handler exception is logged, counted, and the delivery is *dropped* (events are facts; the Ledger already has them).' and :431-434 backpressure deliberately by groups -- this is the documented design, not an undermined one
- simorgh/bus/factory.py:24-52 -- `default_handler_error` prints `[bus] handler for {kind} raised ...` plus traceback to stderr unconditionally; factory.py:58 installs it by default -- drops are not silent
- simorgh/bus/client.py:223 -- `self._metrics.inc("nacked" if spec.group is not None else "dropped", message.type)`; simorgh/bus/metrics.py:33-38 snapshot includes `dict(self.counters)` -- dropped IS in bus health when nonzero
- ~/.simorgh/ledger/streams/metrics%3Ahistory.jsonl: `grep -o '"dropped": *[0-9]*' | sort | uniq -c` -> 20 x "dropped":1, 2 x "dropped":2 (22 of 50677 records); latest bus counters `{"acked":656420,"delivered":656420,"published":206877}` -- matches finding; all `queue_depth.*` gauges 0
- simorgh/bus/config.py:31 `max_queue_depth: int = 10_000  # per consumer group`, :66 `dedupe_window: int = 5000` -- bus dedupe is a small per-lane OrderedDict; the 'idem sidecar' (~/.simorgh/ledger/idem, 355M, 5 streams) is a Ledger feature keyed on idempotency_key, not bus plumbing
- simorgh/bus/config.py + `python -c 'from simorgh.bus.config import Config; print(Config().backend)'` -> memory; no [bus] section in ~/.simorgh/simorgh.toml

**corrected claim:** Broadcast subscriptions (153 of 161 subscribe sites; 8 use competing groups) are drop-on-error, unbounded, and keep delivering while paused -- but this is the bus blueprint's stated design (01-bus.md section 5.2, 7), not an undermined one. A raising broadcast handler is printed to stderr with traceback, counted as `dropped`, and that counter already appears in the `system.metrics` bus snapshot (22 historical records show 1-2 drops against ~656k deliveries). What does not exist is replay of bus messages to subscribers; ledger-backed state rebuild via `ledger.read()` is used at ~20 sites. At one-laptop scale the only open item is bounding broadcast heaps with an overflow counter; shrinking the at-least-once machinery would remove the retry/dead-letter path that guardian and execution actually use.

**severity adjustment:** lower

