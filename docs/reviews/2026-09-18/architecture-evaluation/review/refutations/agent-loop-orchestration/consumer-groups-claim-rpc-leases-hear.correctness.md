# refute:correctness:Consumer groups, claim RPC, leases, hear

*Workflow: review · Phase: Refute · Agent id: `add7b786fc2dd315b` · Tool calls: 8*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "agent-loop-orchestration". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Consumer groups, claim RPC, leases, heartbeats and lease scans for one worker in one process",
    "kind": "over-engineering",
    "severity": "medium",
    "claim": "The worker design is a distributed competing-consumer protocol (claim request/reply, lease renewal on every step and every 30s, a per-second lease scan, redelivery on crash) but the deployed configuration is workers=1 on the in-memory bus in a single process, and the project's own history shows this machinery generated more incidents (lease expiry resurrecting finished tasks, preemption killing the task it postponed, the 300s handler timeout acting as every task's wall budget) than it prevented.",
    "evidence": [
      "simorgh/orchestration/worker.py:192-210 subscribe(TASK_AVAILABLE, group='workers', max_inflight=1, max_handler_seconds=UNBOUNDED); :279 `reply = await self._bus.request_or_error(claim_req, timeout=2.0)`; :350-378 _heartbeat_loop publishes task.lease_heartbeat every min(heartbeat_s, lease/3)",
      "simorgh/planning/scheduler.py:233-247 scan_leases on every system.tick.second; planning/store.py:355-374 refresh_lease appends lease_refreshed per task.step and per heartbeat",
      "simorgh/orchestration/config.py:1-45 docstring: lease_seconds, max_depth, max_children_concurrent, needs_human_timeout_s 'declared ... but no code path reads them yet'",
      "~/.simorgh/simorgh.toml has no [orchestration] or [bus] section: workers=1, bus backend=memory",
      "Measured task:5ad4ce1cce7d: 16 lease_refreshed for 10 task.step"
    ],
    "why_it_matters": "For one laptop the same guarantees (one task at a time, crash detection, resume) come from a task.started without a matching terminal event at boot; the lease protocol adds a write per step, a scan per second, and a family of race conditions with no second process to justify them.",
    "recommendation": "Keep Planning as the queue owner and keep the message contracts, but when workers==1 and the bus is in-memory: do not heartbeat, do not refresh the lease per step, and treat 'started, no outcome, worker gone' at boot as the crash signal. Re-enable the lease path only under local-multi mode where it is actually needed.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read worker subscribe and claim code |  parallel_read_tools=parallel_read_tools, skills_enabled=skills_enabled, skills_catalog_max_chars=skills_catalog_max_chars, skills_roots=skills_roots, skills_ch |
| 2 | Bash | Read worker heartbeat loop |  return description try: return (await self._ledger.get_blob(ref)).decode("utf-8") except Exception as exc: # noqa: BLE001 -- a readable preview beats no task l |
| 3 | Bash | Read orchestration config, scheduler lease scan, store refresh_lease | """`simorgh.toml [orchestration]` (16 section 3.5). `Service.start()` adopts this section via `from_mapping` the same way `persona.service.Service` does (observ |
| 4 | Bash | Check toml config, planning service wiring, and whether prior reviews already covered leases | 1:[voice] 15:[interface] 18:[execution] 22:[cognition] 24:[cognition.providers] 26:[cognition.providers.ollama] --- 69: topics.SYSTEM_TICK_SECOND, 70: topics.SY |
| 5 | Bash | Measure the cited task's ledger stream and check bus mode config | blobs heads idem index.json LOCK snapshots streams (eval):1: no matches found: /Users/saeed/.simorgh/ledger/*5ad4ce1cce7d* file: --- 3:field has a working defau |
| 6 | Bash | Confirm tick wiring, find the cited task's stream, check sim.sh bus mode and recovery paths |  # -- ticks / pause ------------------------------------------------------------ async def _on_tick_idle(self, message: Message) -> None: if self._scheduler is  |
| 7 | Bash | Count event types on the cited task and ledger-wide, check sim.sh mode, boot recovery, and prior reviews for leases |  2 "type":"claimed" 1 "type":"created" 1 "type":"lease_expired" 16 "type":"lease_refreshed" 2 "type":"status_changed" 1 "type":"task.failed" 2 "type":"task.star |
| 8 | Bash | Pin exact line numbers for the cited evidence | 214: topics.TASK_AVAILABLE, self._on_available, group="workers", max_inflight=1, 279: reply = await self._bus.request_or_error(claim_req, timeout=2.0) 350: asyn |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every factual element of the claim is true of the code today, not history. (1) The worker really is a competing-consumer protocol: simorgh/orchestration/worker.py:212-216 subscribes to TASK_AVAILABLE with group="workers", max_inflight=1, max_handler_seconds=UNBOUNDED; :279 does a claim request/reply with a 2s timeout; :350-378 _heartbeat_loop publishes task.lease_heartbeat every min(heartbeat_s, lease/3). (2) The lease is renewed on every step AND on every heartbeat: planning/service.py:351-356 maps both TASK_STEP and TASK_LEASE_HEARTBEAT to store.refresh_lease, which appends a lease_refreshed event (planning/store.py:355-374). (3) scan_leases runs on every system.tick.second (planning/service.py:922-925 -> scheduler.py:233-247). (4) Deployment is single-process, one worker, in-memory bus: orchestration/config.py:48 `workers: int = 1`; bus/config.py:30 `backend = "memory"`; ~/.simorgh/simorgh.toml has only [voice],[interface],[execution],[cognition*] sections (no [orchestration] or [bus]); sim.sh sets no SIMORGH_BUS_BACKEND. (5) The four config fields lease_seconds/max_depth/max_children_concurrent/needs_human_timeout_s are declared and unread per orchestration/config.py:31-45 docstring. (6) The measured ledger numbers reproduce exactly: task:5ad4ce1cce7d has 16 lease_refreshed vs 10 task.step, plus lease_expired + 2 claimed + 2 task.started (i.e. this task was itself resurrected once by lease expiry before failing). Ledger-wide across 2431 task streams: 3008 lease_refreshed, 4386 task.step, only 8 lease_expired. (7) The 'more incidents than it prevented' judgement is corroborated by the code's own comments, not only EVOLUTION.md: scheduler.py:233-237 ('101 tasks generated 1,305 claims'), worker.py:243 ('Preemption destroyed exactly the work it was supposed to postpone'), worker.py:207-211 (300s handler default 'was silently the wall budget of every task'). The one positive use is the crash-resume path (tests/simorgh/integration/test_local_multi_worker_crash_resume.py), which is the multi-worker case the claim explicitly proposes keeping under local-multi mode. Nuance the finding could state more carefully: config.py:11-17 argues `workers` is meaningful in-process (N Worker instances in one process compete on the group), so the machinery is not dead code by design; but the deployed value is 1, so the classification 'over-built for real scale' is the right category (a), with the incident history being category (b). Not in the known-findings list: grep for lease/heartbeat across docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html and docs/architecture-third-opinion-2026-09-18.md returns nothing (the memory note about 'completed tasks resurrected by lease expiry' is the creator's own bug log, not a prior review finding, and it was about a bug since fixed, whereas this finding is about the design's cost/benefit at scale 1).

### evidence

- simorgh/orchestration/worker.py:212-216 `self._bus.subscribe(topics.TASK_AVAILABLE, self._on_available, group="workers", max_inflight=1, max_handler_seconds=UNBOUNDED)`
- simorgh/orchestration/worker.py:279 `reply = await self._bus.request_or_error(claim_req, timeout=2.0)`
- simorgh/orchestration/worker.py:350-378 `_heartbeat_loop`: `interval = max(0.1, min(self._heartbeat_s, lease_seconds / 3.0))`, publishes TASK_LEASE_HEARTBEAT in a `while True` loop
- simorgh/planning/service.py:351-356 `_on_task_step` -> `self._store.refresh_lease(...)`; `_on_task_lease_heartbeat = _on_task_step` (both paths append lease_refreshed)
- simorgh/planning/service.py:922-925 `_on_tick_second` -> `await self._scheduler.scan_leases()`; simorgh/planning/scheduler.py:233-247 scan_leases iterates every task each second
- simorgh/planning/store.py:355-374 refresh_lease appends a `lease_refreshed` Event to the task stream on every call
- simorgh/orchestration/config.py:31-45 docstring: lease_seconds, max_depth, max_children_concurrent, needs_human_timeout_s 'declared ... but no code path reads them yet'; :48 `workers: int = 1`
- simorgh/bus/config.py:30 `backend: str = "memory"`; :36 `handler_timeout_seconds: float = 300.0`
- `grep -nE '^\[' ~/.simorgh/simorgh.toml` -> [voice] [interface] [execution] [cognition] [cognition.providers] [cognition.providers.ollama] (no [orchestration], no [bus]); `grep -n BUS_BACKEND sim.sh` -> nothing
- `grep -o '"type":"[a-z_.]*"' ~/.simorgh/ledger/streams/task%3A5ad4ce1cce7d.jsonl | sort | uniq -c` -> 2 claimed, 1 created, 1 lease_expired, 16 lease_refreshed, 2 status_changed, 1 task.failed, 2 task.started, 10 task.step
- Ledger-wide over 2431 task streams: 3008 lease_refreshed, 4386 task.step, 8 lease_expired (`cat ~/.simorgh/ledger/streams/task%3A*.jsonl | grep -o ... | sort | uniq -c`)
- simorgh/planning/scheduler.py:233-237 scan_leases docstring: 'expiring it used to reset the task to available and hand it straight back to a worker, which is how 101 tasks generated 1,305 claims'
- simorgh/orchestration/worker.py:207-211: bus per-handler default 300s 'was silently the wall budget of every task'; :243 'Preemption destroyed exactly the work it was supposed to postpone'
- tests/simorgh/integration/test_local_multi_worker_crash_resume.py exists: the redelivery guarantee is exercised only in the multi-worker case
- `grep -in 'lease\|heartbeat' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md` -> no matches (not previously reported)

**severity adjustment:** keep

**corrected claim:** The worker/lease design is a distributed competing-consumer protocol (claim request/reply, lease refresh on every step and on a heartbeat, a per-second lease scan over every task, redelivery on lease expiry). The deployed configuration is workers=1 on the in-memory bus in one process (both defaults; simorgh.toml sets neither). Measured on the live ledger: 3008 lease_refreshed events against 4386 task.step across 2431 tasks, with only 8 lease_expired ever recorded; on task:5ad4ce1cce7d, 16 lease_refreshed for 10 steps. The code's own comments record three incidents caused by this machinery (1,305 claims for 101 tasks; preemption killing the task it postponed; the 300s handler timeout as every task's wall budget). One nuance: `workers` is not meaningless in one process (N in-process Worker instances can compete on the group), so the machinery is not dead code by design; it is over-built for the value actually deployed (1) and the crash-resume guarantee it exists for is only tested in the multi-worker case.

