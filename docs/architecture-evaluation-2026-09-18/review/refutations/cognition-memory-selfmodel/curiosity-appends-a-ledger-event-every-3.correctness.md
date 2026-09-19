# refute:correctness:Curiosity appends a ledger event every 3

*Workflow: review · Phase: Refute · Agent id: `a731b820e85a021bb` · Tool calls: 7*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "cognition-memory-selfmodel". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Curiosity appends a ledger event every 3 seconds while doing nothing: 161k events, 45 MB of 'autonomy_paused'",
    "kind": "bug",
    "severity": "high",
    "claim": "`_record_tick` is called on every skipped idle tick, the idle tick fires every 3 s, and `curiosity:` streams have no retention, so a paused Curiosity has written the largest single stream in the cognitive core (45,068,994 bytes) recording that it did nothing.",
    "evidence": [
      "`ls -la streams/curiosity%3Aticks.jsonl` -> `45068994` bytes; `wc -l` -> 161,096 events (vs `cognition:calls` 2.4 MB, `memory:episodic` 1.8 MB)",
      "ledger measurement: `curiosity ticks total 161096 last-20000 reasons: {'autonomy_paused': 20000}`; `mean interval last 2000 ticks: 3.02 s`; last record: `{\"backlog\":0,\"picked\":[],\"proposed\":[],\"skipped_reason\":\"autonomy_paused\",...}`",
      "simorgh/curiosity/service.py:396-403 -- `_run_tick_locked` calls `await self._record_tick(skipped_reason=\"autonomy_paused\")` (and the same for paused/backlog/cooldown/budget) on every idle tick; simorgh/kernel/api.py:40 `idle_tick_cooldown_s: float = 3.0`",
      "simorgh/ledger/compaction.py:36 `DEFAULT_RETENTION = {\"trace:\": \"2d\", \"dead:\": \"30d\", \"activity\": \"90d\"}` -- no entry for `curiosity:`, so 'no match means forever' (compaction.py:66)"
    ],
    "why_it_matters": "This is the same 'ledger growth' shape that produced the 192k-trace-file cleanup, coming from a subsystem that is switched off. It also makes the audit record useless: 99.99% of `curiosity:ticks` carries no information.",
    "recommendation": "Record a skipped tick only when `skipped_reason` changes from the previous tick (edge-triggered), and add `\"curiosity:ticks\": \"2d\"` to DEFAULT_RETENTION. Ten lines.",
    "confidence": 0.98
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read curiosity tick logic around the cited lines |  }) return 0 # async: the count arrives later via action.result -> curiosity.interest.updated # -- ticks ------------------------------------------------------- |
| 2 | Bash | Find all record_tick and skip reason call sites | 72: self._autonomy_paused = False 136: self._autonomy_paused = not self._config.autonomy_on_boot 175: await self._append(_TICKS_STREAM, "tick", {"ts": self._now |
| 3 | Bash | Read compaction retention defaults and kernel idle tick cooldown | from .streams import is_per_id _DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$") _UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0} # `trace: |
| 4 | Bash | Read record_tick body, stream name, and autonomy default |  "area": target.area, "why_this_area": f"drive-weighted sample (area={target.area})", "novelty_score": novelty, }) def _candidate_id(self, subject: str, descrip |
| 5 | Bash | Measure curiosity ticks stream size, reasons, and interval | -rw-r--r--@ 1 saeed staff 2482677 Sep 18 17:13 cognition%3Acalls.jsonl -rw-r--r--@ 1 saeed staff 4973 Sep 16 18:31 curiosity%3Acandidates.jsonl -rw-r--r--@ 1 sa |
| 6 | Bash | Check retention overrides in config and the idle tick publisher | --- kernel idle tick: /Users/saeed/ws/Simorgh/simorgh/kernel/api.py:40: idle_tick_cooldown_s: float = 3.0 /Users/saeed/ws/Simorgh/simorgh/kernel/config.py:80: " |
| 7 | Bash | Rank largest streams and check whether prior reviews already mention curiosity ticks | 119099341 metrics%3Ahistory.jsonl 45068994 curiosity%3Aticks.jsonl 17819390 persona%3Astate.jsonl 10150896 execution%3Ainflight.jsonl 8298845 execution%3Atools. |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line and measurement checks out against the code and the live ledger today. simorgh/curiosity/service.py:395-422 calls `await self._record_tick(skipped_reason=...)` on every guarded exit of `_run_tick_locked` (paused, autonomy_paused, backlog_nonempty, explore_cooldown, budget) plus `already_running` at :389; `_record_tick` (:567-583) unconditionally appends a "tick" event to `curiosity:ticks` with no edge-triggering or dedupe. The Kernel's scheduler publishes SYSTEM_TICK_IDLE once per `idle_tick_cooldown_s` (kernel/scheduler.py:304-307, default 3.0 at kernel/api.py:40), and `_on_tick_idle` (:364) calls `_run_tick` each time. `DEFAULT_RETENTION` at ledger/compaction.py:36 has only `trace:`, `dead:`, `activity`; `window_for` (:66) returns None (forever) for `curiosity:ticks`; ~/.simorgh/simorgh.toml has no retention override. Live ledger: `curiosity%3Aticks.jsonl` is 45,068,994 bytes / 161,096 lines, the last 20,000 events are 100% `autonomy_paused` at a mean interval of 3.01 s, and the final record is exactly as quoted. The comment at service.py:407-416 shows the author deliberately made skipped ticks free of LLM cost but did not make them free of ledger cost. Neither docs/architecture-audit-2026.md nor docs/architecture-review-2026-09-18.html mentions `curiosity:ticks`, so it is not in the known list (the known "ledger ~1.4 GB" item is the aggregate, not this contributor). One nuance: it is the largest stream in the cognitive core as claimed, but not the largest overall -- `metrics%3Ahistory.jsonl` is 119 MB, which is the same shape from a different subsystem and worth folding into the same fix. Severity slightly lowered: 45 MB (~8 MB/day while paused) on a laptop is a real but modest cost; the stronger point is the audit-noise argument and that a bigger sibling exists.

### evidence

- simorgh/curiosity/service.py:389,397,402,405,417,422 -- six `await self._record_tick(skipped_reason=...)` early-returns in `_run_tick`/`_run_tick_locked`; :402 is the `autonomy_paused` branch
- simorgh/curiosity/service.py:567-583 -- `_record_tick` builds payload and unconditionally `await self._append(_TICKS_STREAM, "tick", payload)`; `_TICKS_STREAM = "curiosity:ticks"` at :49; no comparison with `_last_tick_record`
- simorgh/curiosity/service.py:364-365 -- `_on_tick_idle` calls `_run_tick` on every SYSTEM_TICK_IDLE
- simorgh/kernel/scheduler.py:304-307 -- idle tick published when `(now - self._last_idle_tick) >= self._idle_tick_cooldown_s`; simorgh/kernel/api.py:40 `idle_tick_cooldown_s: float = 3.0`
- simorgh/ledger/compaction.py:36 `DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"}`; :60-66 `window_for` returns None (forever) when no prefix matches; `grep retention ~/.simorgh/simorgh.toml` -> no output
- `ls -la ~/.simorgh/ledger/streams | grep curiosity` -> `45068994 Sep 18 17:14 curiosity%3Aticks.jsonl`; `wc -l` -> 161096; cognition%3Acalls.jsonl 2482677, memory%3Aepisodic.jsonl 1799262
- tail -20000 of the stream parsed: `Counter({'autonomy_paused': 20000})`, `mean interval last 20000 3.0139 s`; last line: `{..."payload":{"backlog":0,"picked":[],"proposed":[],"skipped_reason":"autonomy_paused","ts":1789776857.49778},"seq":161096,"stream":"curiosity:ticks",...}`
- `ls -S ~/.simorgh/ledger/streams | head -2` -> metrics%3Ahistory.jsonl 119099341 bytes, curiosity%3Aticks.jsonl 45068994 bytes -- second largest overall, largest among cognition/memory/curiosity streams
- grep for `curiosity:ticks` / `curiosity:` in docs/architecture-audit-2026.md and docs/architecture-review-2026-09-18.html -> no matches; not in the known-findings list

**severity adjustment:** lower

**corrected claim:** `_record_tick` appends an event on every skipped idle tick (service.py:389-422, 567-583), the Kernel fires idle ticks every 3 s (scheduler.py:304, api.py:40), and no retention covers `curiosity:` (compaction.py:36,66), so a paused Curiosity has written 161,096 events / 45 MB of `autonomy_paused` -- the largest stream in the cognitive core and the second largest in the whole ledger, behind `metrics:history` (119 MB), which has the same unbounded-heartbeat shape and should be fixed together.

