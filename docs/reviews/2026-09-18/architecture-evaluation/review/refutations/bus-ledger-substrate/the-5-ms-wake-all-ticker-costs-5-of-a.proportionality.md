# refute:proportionality:The 5 ms wake-all ticker costs ~5% of a

*Workflow: review · Phase: Refute · Agent id: `a818056e1aa1c9c94` · Tool calls: 10*

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
| 2 | Bash | Locate backend construction, config and subscribe count | (eval):1: no matches found: --include=*.py ---backend config--- ---subscribe sites--- (eval):1: no matches found: --include=*.py 0 ---sqlite backend tick?--- 25 |
| 3 | Bash | Locate backend construction, config, subscribe count, sqlite poll interval | simorgh/ledger/factory.py:24: return InMemoryBackend() simorgh/memory/service.py:38: self._tick_seconds = 0 simorgh/memory/service.py:258: self._tick_seconds += |
| 4 | Bash | Read bus factory backend selection and live config |  dropped in complete silence, and that silence is the single most expensive thing in this codebase's history: - a stale-cursor ConflictError in `refresh_lease`  |
| 5 | Bash | Check bus backend default, live config, and client inbox lane | 3:field has a working default so the `memory` backend needs no config at 30: backend: str = "memory" # memory \| sqlite \| aws 36: handler_timeout_seconds: float  |
| 6 | Bash | Confirm which bus backend the live kernel uses | class KernelBootError(RuntimeError): pass def _bus_config_for(config: LoadedConfig, runtime: RuntimeConfig): """Shared by `Kernel` and `WorkerKernel` so both pr |
| 7 | Bash | Measure idle CPU of InMemoryBackend ticker at several tick rates and lane counts | Exit code 1 Traceback (most recent call last): File "/private/tmp/claude-501/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/scratchpad/tick_cost.p |
| 8 | Bash | Measure idle CPU of InMemoryBackend ticker at several tick rates and lane counts | tick=0.005s lanes=170: cpu 0.827s over 5.0s wall = 16.5% of one core tick=0.005s lanes=20: cpu 0.186s over 5.0s wall = 3.7% of one core tick=0.05s lanes=170: cp |
| 9 | Bash | Check how tests depend on the ticker and FakeClock | tests/simorgh/ledger/test_projection.py tests/simorgh/ledger/test_backends.py tests/simorgh/ledger/test_head_never_regresses.py tests/simorgh/ledger/test_servic |
| 10 | Bash | See how bus tests drive retries via FakeClock against the real ticker | 20: # backend compares against (the harness's FakeClock), or `now > ts + 22: # FakeClock's fixed start, so an unset clock silently makes TTL never 23: # expire  |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every code citation checks out and the cost is real; my own measurement on this laptop is worse than the finding's (16.5% of one core at 170 lanes, not 5.6%). The live system does use this backend with this tick: `bus/config.py:30` defaults `backend = "memory"`, `~/.simorgh/simorgh.toml` has no `[bus]` section, `sim.sh`/`simloader.py` do not set `SIMORGH_BUS_BACKEND`, and `bus/factory.py:59-62` constructs `InMemoryBackend` WITHOUT passing `tick_seconds`, so the 5 ms default is not tunable from config at all. `_wake_all` (memory.py:137-139) sets every lane's Event unconditionally, whether or not that lane's heap holds anything — the 170 idle-lane dispatchers each resume, `clear()`, call `_ready()` on an empty heap and go back to sleep 200 times a second. The scaling is linear in lanes (20 lanes: 3.7%; 170 lanes: 16.5%) and in tick rate (0.05 s: 2.0%; 0.25 s: 0.5%; 1.0 s: 0.2%).

Through the skeptic's lens: this is category (b) — the design (injectable clock + coarse tick so FakeClock tests never wall-sleep, memory.py:15-17) is sound; the implementation undermines it by waking lanes that have nothing to check. It is not an over-built architecture, it is a ~3-line implementation flaw, so 'architectural problem' overstates it, but the cost is concrete on the one machine that also runs STT/TTS/camera decode, so it belongs in the report.

One part of the recommendation is wrong and would create more work than it saves: `loop.call_at(retry_at)` schedules on loop time, not on the injected `clock`, so the bus parity tests that do `h.clock.advance(2.0)` and then wait for the real ticker to notice (tests/simorgh/bus/test_backends_parity.py:125,145,167,249; harness.py:40 uses FakeClock) would stop working — the tick exists precisely to bridge the fake clock. Raising the tick to 0.25 s also slows every FakeClock retry test by up to 0.25 s per retry step. The proportionate fix keeps the ticker and makes `_wake_all` (or the tick path only) wake just lanes with a non-empty heap; with zero queued entries at idle, the tick then costs a dict iteration and nothing else, and FakeClock semantics are untouched. Sub-second `retry_after` from an explicit nack (memory.py:311-312, 299) is still served because that lane's heap is non-empty.

### evidence

- simorgh/bus/backends/memory.py:82 `tick_seconds: float = 0.005,` — default confirmed
- simorgh/bus/backends/memory.py:132-139 `_tick_loop`: `await asyncio.sleep(self._tick); self._wake_all()` and `_wake_all` does `for lane in self._lanes.values(): lane.wake.set()` with no check that the lane's heap is non-empty
- simorgh/bus/backends/memory.py:208-219 `_dispatch`: every woken lane runs `lane.wake.clear()`, `self._clock()`, `_ready()` on an empty heap, breaks — pure overhead at idle
- simorgh/bus/backends/memory.py:299 `backoff = retry_after if retry_after is not None else min(60.0, 2.0 ** (entry.attempt - 1))` — implicit backoff floor is 1 s; only explicit `nack(retry_after=...)` (line 311) can be sub-second
- simorgh/bus/factory.py:59-62 `InMemoryBackend(clock=clock, max_deliveries=..., handler_timeout=..., dedupe_window=..., on_handler_error=...)` — `tick_seconds` is never passed, so it is not configurable
- simorgh/bus/config.py:30 `backend: str = "memory"`; `grep -n -i 'backend\|\[bus' ~/.simorgh/simorgh.toml` -> no output; `grep -n 'SIMORGH_BUS_BACKEND' sim.sh simloader.py` -> no output — the live kernel runs the memory backend
- `grep -rn '\.subscribe(' simorgh/ | grep -v /tests/ | wc -l` -> 162, plus one broadcast inbox lane per requesting client (simorgh/bus/client.py:247-252 `_ensure_inbox` registers `group=None`) — ~170 lanes is a fair estimate
- Measured (PYTHONPATH=. python3 scratchpad/tick_cost.py, 5 s idle each, ru_utime+ru_stime): `tick=0.005s lanes=170: 16.5% of one core`; `tick=0.005s lanes=20: 3.7%`; `tick=0.05s lanes=170: 2.0%`; `tick=0.25s lanes=170: 0.5%`; `tick=1.0s lanes=170: 0.2%`
- simorgh/bus/backends/memory.py:15-17 docstring: 'Time comes from an injectable clock so tests drive TTL/retry with FakeClock; the dispatcher wakes ... on a small real-time tick so a retry becomes ready without wall-clock sleeps' — the tick is load-bearing for FakeClock tests
- tests/simorgh/bus/harness.py:40 `self.clock = clock or FakeClock()`; tests/simorgh/bus/test_backends_parity.py:125,145,167,249 `h.clock.advance(2.0/3.0/5.0/4.0)` then await the retry — these rely on the real ticker re-reading the fake clock, which `loop.call_at` (loop time) would not do

**severity adjustment:** keep

**corrected claim:** InMemoryBackend's 5 ms ticker (memory.py:82,132-139) wakes all ~170 lane dispatchers unconditionally, including the ~170 that hold nothing; measured here at 16.5% of one core idle with 170 lanes (linear in lanes and tick rate), and the tick is not configurable because factory.py:59-62 never passes tick_seconds. Implicit retry backoff floors at 1 s (memory.py:299); only explicit nack retry_after can be sub-second. This is an implementation flaw in a sound design, not an architectural mistake. The proposed `loop.call_at` fix is wrong for this codebase because the tick exists to bridge the injected FakeClock (memory.py:15-17; test_backends_parity.py:125,145,167,249 advance the fake clock and wait for the ticker). The proportionate fix is to have the tick wake only lanes whose heap is non-empty (idle cost then ~0), optionally with a coarser tick; that preserves test semantics and still serves sub-second retry_after.

