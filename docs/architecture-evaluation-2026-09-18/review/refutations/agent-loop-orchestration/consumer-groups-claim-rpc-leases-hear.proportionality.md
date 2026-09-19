# refute:proportionality:Consumer groups, claim RPC, leases, hear

*Workflow: review · Phase: Refute · Agent id: `abc266c2b13b053eb` · Tool calls: 21*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "agent-loop-orchestration". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Read cited worker.py regions |  parallel_read_tools=parallel_read_tools, skills_enabled=skills_enabled, skills_catalog_max_chars=skills_catalog_max_chars, skills_roots=skills_roots, skills_ch |
| 2 | Bash | Read cited scheduler, store, config regions |  payload={"task_id": task.id, "kind": task.kind, "lease_seconds": self._lease_seconds}, ) await self._bus.publish(message) # Only what is ready right now: a tas |
| 3 | Bash | Check deployed config for orchestration/bus sections | 1:[voice] 15:[interface] 18:[execution] 22:[cognition] 24:[cognition.providers] 26:[cognition.providers.ollama] ---- benchmark benchmark-waves benchmarks bus co |
| 4 | Bash | Inspect kernel worker forcing, bus backend default, multi mode |  `jsonl` ledger) the main `simorgh run` process -- and every sibling worker process -- also opens against the same `simorgh.toml`/`--config` (`_bus_config_for`/ |
| 5 | Bash | Check sqlite bus lease and callers of lease machinery | ---- __init__.py __pycache__ api.py backends client.py config.py enforcement.py factory.py metrics.py policy.py README.md router.py service.py trace.py ---- (ev |
| 6 | Bash | Locate the measured task in the ledger | blobs heads idem index.json LOCK (eval):1: no matches found: /Users/saeed/.simorgh/ledger/*.jsonl sample file: (eval):1: no matches found: /Users/saeed/.simorgh |
| 7 | Bash | Count event types in the measured task and ledger-wide |  35 /Users/saeed/.simorgh/ledger/streams/task%3A5ad4ce1cce7d.jsonl {'created': 1, 'claimed': 2, 'task.step': 10, 'task.started': 2, 'lease_refreshed': 16, 'stat |
| 8 | Bash | Find callers of lease machinery and the runtime mode in config | simorgh/contracts/topics.py:96:# all until it finished, and `Scheduler.scan_leases` could hand the same simorgh/contracts/topics.py:102:TASK_LEASE_HEARTBEAT = " |
| 9 | Bash | Check Planning boot-time recovery path | 151: priority_weights=self.config.priority_weights, lease_seconds=self.config.lease_seconds, 167: topics.TASK_LEASE_HEARTBEAT: self._on_task_lease_heartbeat, 32 |
| 10 | Bash | Read the multi-worker crash test and sim.sh mode | """`local-multi` mode's crash/resume drill (docs/blueprint/04-build-plan- and-roadmap.md Phase 5 item 1: "`local-multi` mode: Worker processes on the SQLite bus |
| 11 | Bash | Read runtime defaults, index size, and tick handler | 94: mode = str(section.get("mode", RuntimeConfig.mode)) 11: lease_seconds: float = 600.0 38: human_approval_timeout_seconds: float = 3600.0 92: data["lease_seco |
| 12 | Bash | Estimate scan set size and inspect the 8 lease expiries | task streams 2431 [('task.completed', 2334), (None, 58), ('task.failed', 39)] ---- expiries context == task%3A34d1db3f6dd3.jsonl created \| claimed \| task.step \| |
| 13 | Bash | Timestamp the 8 lease expiries, read mode default and boot recovery | == task%3A34d1db3f6dd3.jsonl expired at 2026-09-13 17:11:46.453698: 600s after last lease_refreshed; lease.until was 600.0s ahead; next=claimed +0.0s expired at |
| 14 | Bash | Check bus timeout, preemption code, heartbeat default, module sizes | 38:def _handler_timeout(requested: float \| None, default: float) -> float \| None: 41: `api.UNBOUNDED` -- a handler whose bound is the work's own.""" 80: handler |
| 15 | Bash | Inspect trace activity in the dead windows before each expiry | == 34d1db3f6dd3 reflect%3Acritique%3A34d1db3f6dd3.jsonl 1 events in window 17:01:37 critique {} task%3A34d1db3f6dd3.jsonl 70 events in window 17:01:00 lease_ref |
| 16 | Bash | Read worker outcome and cleanup path |  kind = str(task.get("kind") or kind) mode = task.get("mode", "execute") description = await self._full_description(task) profile = profiles.for_claimed(kind, m |
| 17 | Bash | Size the task streams against the whole ledger | 2431 88356 trace 26737 action 2431 task 350 verify 310 reflect 5 memory 5 curiosity 5 cognition 3 persona 2 guardian ---- ledger size 1.4G /Users/saeed/.simorgh |
| 18 | Bash | Read think-timeout, handler exception and inflight handling | simorgh/orchestration/worker.py:136: assemble_timeout_s: float = DEFAULT_TIMEOUT_S, think_timeout_s: float \| None = None, simorgh/orchestration/worker.py:163: # |
| 19 | Bash | Find logs mentioning the measured task | benchmark benchmark-waves benchmarks bus cognition curiosity execution guardian interface learning ledger memory orchestration persona planning reflection secre |
| 20 | Bash | Check heartbeat presence in each dead window across all expiries | == 34d1db3f6dd3 expiry 09-13 17:11:46: heartbeats in dead window=0; last trace events before silence: [] == 34d1db3f6dd3 expiry 09-13 17:39:51: heartbeats in de |
| 21 | Bash | Read bus handler-error path and worker report path |  delivery.delivery_id = f"{lane.key}:{m.id}:{entry.attempt}" self._active[m.id] = delivery try: await asyncio.wait_for(member.handler(m), timeout=timeout) expli |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** Every file:line and config fact in the finding checks out: worker.py:192-210 subscribes with group='workers', max_inflight=1, UNBOUNDED; :279 claim RPC with 2s timeout; :350-378 heartbeat loop at min(heartbeat_s=30, lease/3); scheduler.py:233-247 scan_leases on every second tick; store.py:355-374 appends lease_refreshed per step and per heartbeat; orchestration/config.py:29-40 says lease_seconds/max_depth/max_children_concurrent/needs_human_timeout_s are declared but unread; ~/.simorgh/simorgh.toml has no [runtime], [orchestration] or [bus] section so mode='single', workers=1, bus backend='memory' (bus/config.py:30) all fall to defaults; kernel/service.py:649-651 additionally forces workers=1 per WorkerKernel process; the measured task stream really holds 16 lease_refreshed against 10 task.step.

Two load-bearing parts of the claim do not survive the code and the ledger, and they are what carry the recommendation. (1) 'Generated more incidents than it prevented' is history, not current state: all three named incidents are fixed in the code as it stands (scan_leases skips TERMINAL/PAUSED at scheduler.py:239-247; the 300s wall budget is gone via UNBOUNDED at worker.py:209; the preemption kill is handled by the requeued branch at worker.py:314-323). (2) 'The same guarantees come for free from a started-without-outcome check at boot' is refuted by the ledger: of the 8 lease_expired events ever recorded, 7 fired exactly 600-601s after the last renewal, with zero task.lease_heartbeat events in the dead window (a live session publishes one every 30s, visible in the 8db trace), and were re-claimed by the same process 0-295s later; the process never restarted. Those are in-process recoveries of a session that ended without reporting an outcome, and a boot-only check would have left every one of them in_progress for the life of the process. The mechanism is visible in the code: the chat path (worker.py:410-420) wraps run() in except Exception and always calls _report, but the task path (worker.py:304-323) has only a finally for the heartbeat, so an exception escapes the handler, the memory bus catches BaseException and nacks (memory.py:265-270), and nobody writes a terminal event. The lease is currently the only thing that recovers from that.

Under the skeptic lens the cost side is also overstated for this scale: all 2431 task streams together are 6.2 MB of a 1.4 GB ledger (0.4%; the bulk is 88k trace and 27k action streams), 3008 lease_refreshed events total over the project's life, and the per-second scan walks at most ~2.4k in-memory dataclasses inside a tick that already runs for four other reasons (planning/service.py:920-955), so it is sub-millisecond and adds no timer of its own. local-multi is a real, tested third mode (kernel/config.py:84; tests/simorgh/integration/test_local_multi_worker_crash_resume.py SIGKILLs a worker OS process and resumes on a second), so the machinery is not dead code. The recommendation (a second, mode-conditional path with heartbeats off in single mode and on in local-multi) would create exactly the two-paths-one-tested 'unconnected wire' shape the project already suffers from, remove a working safety net, and save roughly nothing measurable.

What is genuinely there: the design is over-scaled for the deployed single mode (category a, but cheap), the unread [orchestration] keys are a real, if already-catalogued, unconnected wire, and the ledger exposes a real bug the finding did not name: task sessions can end without an outcome because _on_available lacks the except-and-report that _on_percept has (category c). That bug, not the lease protocol, is the thing worth a finding.

### evidence

- simorgh/orchestration/worker.py:206-210: subscribe(topics.TASK_AVAILABLE, ..., group="workers", max_inflight=1, max_handler_seconds=UNBOUNDED) -- matches the finding
- simorgh/orchestration/worker.py:279: reply = await self._bus.request_or_error(claim_req, timeout=2.0) -- claim RPC confirmed
- simorgh/orchestration/worker.py:371-378: interval = max(0.1, min(self._heartbeat_s, lease_seconds / 3.0)); loop publishes TASK_LEASE_HEARTBEAT -- heartbeat confirmed; orchestration/config.py:96 heartbeat_s: int = 30; planning/config.py:11 lease_seconds: float = 600.0
- simorgh/planning/scheduler.py:233-247 scan_leases skips TERMINAL_STATUSES and PAUSED before expiring -- the 'resurrected finished tasks' incident is fixed in current code
- simorgh/orchestration/worker.py:314-323: `requeued = self._requeued(task_id) ... if requeued: return` -- the preemption-kills-what-it-postponed incident is fixed in current code
- simorgh/orchestration/config.py:29-40: lease_seconds, max_depth, max_children_concurrent, needs_human_timeout_s 'no code path reads them yet' -- confirmed unread
- grep -nE '^\[' ~/.simorgh/simorgh.toml -> [voice] [interface] [execution] [cognition] [cognition.providers] [cognition.providers.ollama]; no [runtime]/[orchestration]/[bus]; simorgh/bus/config.py:30 backend: str = "memory"; orchestration/config.py:50 workers: int = 1; kernel/service.py:651 OrchestrationService(dataclasses.replace(orch_config, workers=1))
- python3 count of ~/.simorgh/ledger/streams/task%3A5ad4ce1cce7d.jsonl -> {'created': 1, 'claimed': 2, 'task.step': 10, 'task.started': 2, 'lease_refreshed': 16, 'status_changed': 2, 'lease_expired': 1, 'task.failed': 1} -- the 16/10 measurement is accurate
- Ledger-wide over 2431 task streams: task.step 4386, lease_refreshed 3008, lease_expired 8, task.completed 2334, task.failed 39; task streams total 6,210,592 bytes vs `du -sh ~/.simorgh/ledger` = 1.4G (0.4%); stream families: 88356 trace, 26737 action, 2431 task
- Timestamps of all 8 lease_expired events: 7 fired 600-601s after the last renewal with lease.until 600s ahead and next event `claimed` +0.0s/+0.0s/+0.0s/+0.0s/+295.5s/+5.5s/+62.0s; only aee5d8ca6f26 (23746s gap) looks like a boot-time recovery
- Trace stream for 5ad4ce1cce7d: 18:26:33 cognition.think, then nothing until 18:36:33 task.claim; heartbeats in dead window = 0 for all 7 same-process expiries, whereas the 8db trace shows task.lease_heartbeat at 18:06:18 and 18:06:48 while its session was live -- the sessions had ended without a terminal event, and the lease is what re-queued them without a reboot
- simorgh/orchestration/worker.py:304-312: `try: outcome = await self.run(...) finally: heartbeat.cancel()` with no except clause on the task path, versus worker.py:410-420 chat path `except Exception as exc: outcome = Outcome("failed", ...)` 'never let a turn vanish' -- the asymmetry that lets a task session end unreported
- simorgh/bus/backends/memory.py:265-270: `except BaseException as exc: error = exc; outcome = "nack"; ... self._on_handler_error(m, exc)` -- a raising task handler is swallowed by the bus, no outcome is written
- simorgh/planning/service.py:920-955 _on_tick_second: scan_leases is one of five calls on a tick that already exists for _end_cancelled_after_expiry, _reconsider_blocked, _reconsider_awaiting_human and dispatch_ready -- the scan adds no timer of its own
- simorgh/kernel/config.py:84 _VALID_MODES = ("single", "local-multi", "aws"); tests/simorgh/integration/test_local_multi_worker_crash_resume.py:1-60 SIGKILLs a real `simorgh worker` OS process on the sqlite bus and resumes on a second -- the lease path serves a built, tested mode

**severity adjustment:** lower

**corrected claim:** The worker/lease design (claim RPC, per-step and 30s lease renewal, per-second scan, redelivery) is scaled for the built-and-tested local-multi mode while the deployed configuration is single mode, workers=1, in-memory bus. That over-scaling is real but nearly free at this scale: all task streams are 0.4% of the ledger, 3008 renewal events over the project's life, and the scan walks ~2.4k in-memory objects inside a tick that already exists. The three historical incidents the finding cites are fixed in current code. The proposed replacement (boot-time 'started without outcome' check, lease path only under local-multi) would not be equivalent: 7 of the 8 lease expiries ever recorded happened in-process with no restart, recovering task sessions that had ended without reporting an outcome, which a boot check would never see, and forking a mode-conditional path would reproduce the project's dominant two-paths-one-tested bug shape. The genuine bug underneath is that Worker._on_available (worker.py:304-323) lacks the except-and-report that Worker._on_percept (worker.py:410-420) has, so a task session that raises is swallowed by the bus (memory.py:265-270) and only the lease brings the task back ten minutes later; fix that asymmetry and keep the lease as the backstop. The unread [orchestration] lease_seconds/max_depth/max_children_concurrent/needs_human_timeout_s keys are a real but already-catalogued unconnected wire.

