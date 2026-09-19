# refute:correctness:Broadcast subscriptions run up to 16 han

*Workflow: review · Phase: Refute · Agent id: `ab4c63e5bd7c74562` · Tool calls: 6*

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
    "title": "Broadcast subscriptions run up to 16 handlers concurrently and almost nobody sets a partition_key, so per-subscriber ordering is not guaranteed",
    "kind": "right-design-undermined",
    "severity": "medium",
    "claim": "Ordering is designed per partition_key, but only 32 publish sites set one (all in planning/orchestration/verification/benchmark); every other subscription (voice, interface, persona, worldmodel, memory...) dispatches up to max_inflight=16 handlers of the same subscriber concurrently, so two consecutive voice.transcript or ui.* events can interleave at every await and complete out of order.",
    "evidence": [
      "simorgh/bus/api.py:66 `max_inflight: int = 16`; simorgh/bus/backends/memory.py:215-240 `while lane.inflight < max_inflight: ... task = asyncio.create_task(self._run(...))`",
      "memory.py:199 and :231-232 -- only `m.partition_key is not None` entries take the lane's partition lock",
      "`grep -rn \"partition_key=\" simorgh` outside bus/contracts (non-None): 32 sites -- planning/service.py 16, orchestration/worker.py 4, orchestration/session.py 4, verification/service.py 3, benchmark 4, planning/scheduler.py 1; zero in interface, voice, persona, memory, worldmodel",
      "memory note (project history): 'per-turn fact in a session singleton read across an await; failed both directions 2026-09-18' is the symptom shape this produces"
    ],
    "why_it_matters": "Most handlers mutate in-memory state without locks and assume one-at-a-time delivery; the bus silently gives them 16-way concurrency. This is a source of Heisenbugs that unit tests (single message at a time) never see.",
    "recommendation": "Default max_inflight=1 for broadcast subscriptions (a subscriber that wants concurrency opts in explicitly), and keep partition keys as the concurrency knob for the competing-consumer lanes where they are already used.",
    "confidence": 0.72
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/bus/api.py | 1 """Internal interfaces of the Bus (docs/blueprint/subsystems/01-bus.md 2 section 3.4). Everything a backend implements and everything the public 3 client depe |
| 2 | Read | /Users/saeed/ws/Simorgh/simorgh/bus/backends/memory.py (from line 150) | 150 lane.task = asyncio.create_task(self._dispatch(lane, spec), name=f"bus-memory-{lane_key}") 151 lane.members.append(reg) 152 153 async def _unsub() -> None:  |
| 3 | Bash | Count partition_key publish sites and max_inflight usages; check configured bus backend | === partition_key= sites outside bus/contracts === (eval):1: no matches found: --include=*.py === max_inflight usage across simorgh === (eval):1: no matches fou |
| 4 | Bash | Count partition_key publish sites and max_inflight usages; check configured bus backend | === partition_key= sites outside bus/contracts === 16 simorgh/planning/service.py 4 simorgh/orchestration/worker.py 4 simorgh/orchestration/session.py 3 simorgh |
| 5 | Bash | Check envelope partition_key default, configured backend, and sqlite backend concurrency handling | === envelope partition_key === simorgh/bus/client.py:141: partition_key: str \| None = None, simorgh/bus/client.py:148: When `caused_by` is given and `partition_ |
| 6 | Bash | Read bus client publish/subscribe, sqlite dispatch loop, and configured backend | Exit code 1 === client.py 135-245 === def new( self, type: str, payload: dict, *, caused_by: Message \| None = None, partition_key: str \| None = None, priority:  |

## Structured reply

_No result recorded (agent still running, skipped, or failed)._

## Final text

I'll verify the claim against the bus code directly.