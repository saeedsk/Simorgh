# refute:proportionality:The Supervisor never supervises: no heal

*Workflow: review · Phase: Refute · Agent id: `a4677d6ddeb9b7ab8` · Tool calls: 1*

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
    "title": "The Supervisor never supervises: no health ticker, restart never restarts, auto-pause on Guardian-down is unreachable",
    "kind": "right-design-undermined",
    "severity": "high",
    "claim": "Supervisor.poll_once (which is the only path to _restart, and therefore to _on_critical_down) has no production caller, health_every_s is parsed and never read, and _restart stops a service without ever calling start() again, so the S3 invariant 'Guardian/Execution down => system pauses' is not enforced at runtime and the status snapshot's per-subsystem health is frozen at boot-time values.",
    "evidence": [
      "grep -rn 'poll_once\\|_health_task' across simorgh/ and tests/: the only callers are tests/simorgh/kernel/test_supervisor.py:99,106,122 and tests/simorgh/integration/test_guardian_down_autopauses.py:76, whose docstring (lines 8-13) says: 'Phase 0 has no periodic health-poll driver wired into Kernel.boot() yet -- poll_once() is called directly here, standing in for that future ticker.'",
      "simorgh/kernel/service.py:157-327 (Kernel.boot) creates the Supervisor at 226-230 and never create_task()s a poll loop; grep 'health_every_s' hits only kernel/config.py:81,115 and kernel/api.py:43.",
      "simorgh/kernel/supervisor.py:116-124: after `await supervised.service.stop()` the method ends with the comment 'The concrete restart (re-start()) is driven by the caller (Kernel service loop)' -- no such loop exists; supervisor.py:79 stores `asyncio.current_task()` (the boot coroutine) as the service's task.",
      "simorgh/kernel/metrics.py:101-102 `_on_health: pass  # the supervisor's own poll is the source of truth` and 110-119 snapshot() reads s.status/s.last_health, which only _boot_one and poll_once write.",
      "docs/blueprint/subsystems/03-kernel.md:281-290 promises 'Health is polled every health_every_s; three consecutive non-ok polls -> degraded ... Guardian and Execution are special: if either is down, the Kernel transitions to paused automatically'."
    ],
    "why_it_matters": "This is the project's own dominant bug shape (designed slot, one side built, nobody drives it) sitting in the kernel that is supposed to catch it elsewhere. The safety story leans on 'nothing may execute without the safety path' being enforced by wiring; today it is hoped for. The dashboard's subsystem health column is a boot-time screenshot, and three [runtime] knobs (health_every_s, supervisor_backoff_s, supervisor_max_restarts_per_10m) are inert while being exempt from the dead-config probe (configcheck.KERNEL_SECTIONS).",
    "recommendation": "Pick one of two small changes. (a) Wire the ticker: in Kernel.boot after the layer loop, `self._health_task = asyncio.create_task(self._health_loop())` that sleeps health_every_s, awaits supervisor.poll_once(), and publishes system.health for each changed service; cancel it in shutdown. (b) For one laptop, simpler and probably better: delete the in-process restart/backoff machinery and keep only 'down => pause + publish', because a subsystem that crashed mid-state is safer taken down with the process and relaunched by the loader, which is already the process-level restart mechanism. Either way, delete the dead runtime fields or make configcheck cover [runtime].",
    "confidence": 0.95
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Find callers of poll_once and readers of runtime health config | simorgh/kernel/README.md:73:`boot()` yet — `Supervisor.poll_once()` exists and is exercised directly simorgh/kernel/supervisor.py:49: self._health_task: asyncio |

## Structured reply

_No result recorded (agent still running, skipped, or failed)._

## Final text

I'll verify the cited evidence directly.