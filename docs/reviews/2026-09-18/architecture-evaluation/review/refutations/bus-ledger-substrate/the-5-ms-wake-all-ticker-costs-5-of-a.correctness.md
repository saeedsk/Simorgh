# refute:correctness:The 5 ms wake-all ticker costs ~5% of a

*Workflow: review · Phase: Refute · Agent id: `ada0dc167c32480ae` · Tool calls: 5*

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
    "title": "The 5 ms wake-all ticker costs ~5% of a core when the system is idle",
    "kind": "bug",
    "severity": "medium",
    "claim": "InMemoryBackend wakes every lane's dispatcher every 5 ms so a retry can become ready without a timer, which with the live system's ~170 lanes is ~34,000 coroutine resumptions per second doing nothing; retries have a minimum 1 s backoff, so the tick is 200x finer than anything it serves.",
    "evidence": [
      "simorgh/bus/backends/memory.py:82 `tick_seconds: float = 0.005`; :132-139 `_tick_loop ... self._wake_all()` sets every lane's Event",
      "memory.py:299 backoff `min(60.0, 2.0 ** (entry.attempt - 1))` -> 1, 2, 4, 8 s",
      "measured: `(h) InMemoryBackend idle, 170 lanes, tick=0.005s: 5.6% of one core` vs `tick=1.0s: 0.0% of one core`",
      "157 subscribe sites plus one inbox lane per requesting client (client.py:247-252) ~ 170 lanes at boot"
    ],
    "why_it_matters": "On a laptop that also runs STT/TTS and camera decoding, a permanent 5% idle tax from the bus is pure waste and shows up as heat, battery, and the already-reported STT latency under load.",
    "recommendation": "Replace the global tick with per-lane `loop.call_at(retry_at)` wakeups (only lanes holding a retry-pending entry need a timer), or at minimum raise tick_seconds to 0.25 s; retry_after from explicit nack is the only sub-second case and can schedule its own timer.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/bus/backends/memory.py | 1 """In-process asyncio backend (docs/blueprint/subsystems/01-bus.md section 2 5.3) -- the guaranteed floor: zero configuration, zero dependencies, 3 every test |
| 2 | Bash | Check backend construction, config, subscribe counts | (eval):1: no matches found: --include=*.py ---toml--- ---subscribe sites--- (eval):1: no matches found: --include=*.py 0 ---client inbox--- d = self._current_de |
| 3 | Bash | Check backend construction, config and subscribe counts | simorgh/ledger/factory.py:24: return InMemoryBackend() simorgh/memory/service.py:38: self._tick_seconds = 0 simorgh/memory/service.py:258: self._tick_seconds += |
| 4 | Bash | Check default bus backend, runtime mode, and measure idle tick cost | ---bus config default--- 3:field has a working default so the `memory` backend needs no config at 30: backend: str = "memory" # memory \| sqlite \| aws 36: handle |
| 5 | Bash | Check live backend selection and whether finding is already known | (Bash completed with no output) |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every element of the claim checks out against the code as it exists today, and my own measurement reproduces (and exceeds) the reader's number. simorgh/bus/backends/memory.py:82 sets `tick_seconds: float = 0.005`; :104-106 `start()` spawns `_tick_loop`; :132-135 `_tick_loop` sleeps `self._tick` and calls `_wake_all()`; :137-139 `_wake_all` sets every lane's `asyncio.Event`, so every dispatcher (`_dispatch`, :208-219) resumes, calls `_ready` on an (idle) empty heap, and re-waits. The factory (simorgh/bus/factory.py:59-62) constructs `InMemoryBackend` without passing `tick_seconds`, so the 5 ms default is live; no other call site overrides it (grep for `tick_seconds` finds only the memory.py definition and unrelated counters in memory/service.py and cognition/service.py). The live system runs on this backend: simorgh/bus/config.py:30 defaults `backend = "memory"`, ~/.simorgh/simorgh.toml has no `[bus]` section, ~/.simorgh/bus/ is empty (no sqlite file), and nothing in sim.sh/simloader.py sets SIMORGH_BUS_BACKEND. Retry backoff is `min(60.0, 2.0 ** (entry.attempt - 1))` at memory.py:299 (1, 2, 4, 8... s), so the only sub-second wake need is an explicit `nack(retry_after=<1s)` (memory.py:311-312), as the reader says. Lane count: 162 `.subscribe(` sites in simorgh/ plus one broadcast inbox lane per requesting client (client.py:247-252) makes ~170 lanes plausible. Measured idle cost with 170 broadcast lanes and no traffic: tick=0.005s -> 12.5% of one core; tick=0.25s -> 0.5%; tick=1.0s -> 0.0%. The reader's 5.6% is if anything conservative on this machine. This is not on the known-findings list (no mention of tick/wake-all in docs/architecture-audit-2026.md or docs/architecture-review-2026-09-18.html). Classification stands: a design decision (a global fine-grained tick standing in for per-entry timers) whose cost is out of proportion to what it serves; the fix the reader proposes (per-lane `call_at(retry_at)`, or a coarser tick) is correct and small. Severity: medium is fair for a one-laptop system that also runs STT/TTS and camera decode; I would not raise it because the waste is bounded and the fix is a one-line default change at minimum.

### evidence

- simorgh/bus/backends/memory.py:82 `tick_seconds: float = 0.005,`
- simorgh/bus/backends/memory.py:132-139 `_tick_loop`: `await asyncio.sleep(self._tick); self._wake_all()`; `_wake_all` does `for lane in self._lanes.values(): lane.wake.set()`
- simorgh/bus/backends/memory.py:208-219 `_dispatch` wakes on the Event, calls `_ready`, breaks when nothing is ready, loops back to wait
- simorgh/bus/backends/memory.py:299 `backoff = retry_after if retry_after is not None else min(60.0, 2.0 ** (entry.attempt - 1))`
- simorgh/bus/factory.py:59-62 constructs `InMemoryBackend(clock=..., max_deliveries=..., handler_timeout=..., dedupe_window=..., on_handler_error=...)` -- no `tick_seconds`, so the 5 ms default is what runs
- simorgh/bus/config.py:30 `backend: str = "memory"`; ~/.simorgh/simorgh.toml has no [bus] section; ~/.simorgh/bus/ is empty; no SIMORGH_BUS_BACKEND in sim.sh/simloader.py -> live system is on the memory backend
- grep -rn '\.subscribe(' simorgh --include='*.py' | wc -l -> 162; client.py:247-252 `_ensure_inbox` registers one extra broadcast lane per requesting client
- Measured (scratchpad tick_bench.py, InMemoryBackend alone, 170 broadcast lanes, idle 3 s): `tick=0.005s lanes=170: 12.5% of one core`, `tick=0.25s lanes=170: 0.5% of one core`, `tick=1.0s lanes=170: 0.0% of one core`
- docs/architecture-audit-2026.md and docs/architecture-review-2026-09-18.html contain no mention of tick / wake-all -> not already known

**severity adjustment:** keep

