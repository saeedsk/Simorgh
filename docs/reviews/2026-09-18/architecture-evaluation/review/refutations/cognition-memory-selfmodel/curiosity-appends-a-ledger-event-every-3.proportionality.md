# refute:proportionality:Curiosity appends a ledger event every 3

*Workflow: review · Phase: Refute · Agent id: `ae3be8eba47627f4e` · Tool calls: 7*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "cognition-memory-selfmodel". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Read curiosity tick logic around cited lines |  }) return 0 # async: the count arrives later via action.result -> curiosity.interest.updated # -- ticks ------------------------------------------------------- |
| 2 | Bash | Check idle tick cooldown and compaction retention table | /Users/saeed/ws/Simorgh/simorgh/bus/config.py:47: # every `idle_tick_cooldown_s` (3s) and `cognition.provider.status` is /Users/saeed/ws/Simorgh/simorgh/curiosi |
| 3 | Bash | Measure curiosity ticks stream size, reasons and interval | -rw-r--r--@ 1 saeed staff 119099341 Sep 18 17:14 metrics%3Ahistory.jsonl -rw-r--r--@ 1 saeed staff 45068994 Sep 18 17:14 curiosity%3Aticks.jsonl -rw-r--r--@ 1 s |
| 4 | Bash | Inspect record_tick, compaction wiring, retention config, and stream totals | 389: await self._record_tick(skipped_reason="already_running") 397: await self._record_tick(skipped_reason="paused") 402: await self._record_tick(skipped_reason |
| 5 | Bash | Check compaction wiring, toml retention/autonomy config, and who reads ticks stream | simorgh/ledger/service.py:46: self.policy = RetentionPolicy.parse(config.retention, keep_tail=config.keep_tail) simorgh/cognition/service.py:308: compacted = aw |
| 6 | Bash | Check where ledger retention policy is applied and who reads ticks |  self.client = client self._config_from_caller = config self._adopt(config or Config()) self._ctx: Context \| None = None self._subscription = None self._first_c |
| 7 | Bash | Check readers of ticks stream and its share of ledger growth | 49:_TICKS_STREAM = "curiosity:ticks" 175: await self._append(_TICKS_STREAM, "tick", {"ts": self._now(), "skipped_reason": "shutdown"}) 584: await self._append(_ |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every element of the claim checks out against the code and the live ledger. (1) simorgh/curiosity/service.py:396-402 `_run_tick_locked` awaits `_record_tick(skipped_reason="autonomy_paused")` unconditionally on every idle tick when `_autonomy_paused` is set, and `_record_tick` (service.py:567-584) has no edge-trigger or throttle: it always `_append`s to `curiosity:ticks`. (2) The idle heartbeat is 3 s: simorgh/kernel/api.py:40 `idle_tick_cooldown_s: float = 3.0`, enforced in kernel/scheduler.py:304; measured mean interval of the last 2000 records is 3.026 s. (3) simorgh/ledger/compaction.py:36 `DEFAULT_RETENTION` has only `trace:`, `dead:`, `activity`; `window_for` (compaction.py:66-72) returns None (forever) for `curiosity:ticks`; ~/.simorgh/simorgh.toml has no `retention` override. (4) The file is 45,068,994 bytes / 161,096 lines; 159,330 of all records (98.9%) carry `skipped_reason: autonomy_paused`, the last 20,000 are 100% that reason.

Skeptic lens on scale: the stream is a pure write-only audit log. grep finds no reader of `curiosity:ticks` anywhere in simorgh/ or tools/ except the writer and a comment; Curiosity does not replay it on boot (it keeps `_last_tick_record` in memory only). So the cost is disk, not boot time or correctness, and it is one file, not the 192k-file count problem the finding likens it to. Measured growth is ~5.1 MB/day, 11.6% of the 390 MB streams directory. On a one-laptop system that is a nuisance, not a hazard, and the recommendation (edge-triggered skip records + a `curiosity:ticks` retention entry) is genuinely small and proportionate. But the finding is a specific instance of a broader shape the reader did not name: `metrics:history` is 119 MB (the largest stream, 2.6x ticks) and `persona:state` 17.8 MB, both also heartbeat-driven and also without retention. Fixing ticks alone addresses ~12% of the growth; the real fix is a default retention window for every periodic-heartbeat stream. Severity 'high' overstates a disk leak nobody reads and that does not slow the system; 'medium' is right, with the recommendation broadened.

### evidence

- simorgh/curiosity/service.py:396-403 -- `if not force and self._autonomy_paused: await self._record_tick(skipped_reason="autonomy_paused"); return []` runs on every idle tick
- simorgh/curiosity/service.py:567-584 -- `_record_tick` builds the payload and unconditionally `await self._append(_TICKS_STREAM, "tick", payload)`; no comparison with the previous record
- simorgh/kernel/api.py:40 `idle_tick_cooldown_s: float = 3.0`; simorgh/kernel/scheduler.py:304 gates idle ticks on that cooldown
- simorgh/ledger/compaction.py:36 `DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"}`; compaction.py:66-72 `window_for` returns None (forever) when no prefix matches; `grep retention ~/.simorgh/simorgh.toml` -> no override
- `ls -la ~/.simorgh/ledger/streams/curiosity%3Aticks.jsonl` -> 45068994 bytes; `wc -l` -> 161096
- python count over all 161,096 records: skipped_reason Counter = autonomy_paused 159330, backlog_nonempty 1754, already_running 6, None 6; last 20,000 records all autonomy_paused; mean interval of last 2000 = 3.026 s
- Span of the stream 8.82 days -> ~5.1 MB/day; ticks are 11.6% of the 390 MB streams directory
- `grep -rn 'curiosity:ticks\|_TICKS_STREAM\|_last_tick_record' simorgh tools` -> only the writer (service.py:49,175,583,584), a docstring (sampler.py:86) and a scanner comment; no reader, no boot replay
- Same shape elsewhere, larger: `ls -la streams | sort -k5 -nr` -> metrics%3Ahistory.jsonl 119,099,341 bytes (50,677 records), persona%3Astate.jsonl 17,819,390 bytes; neither has a retention entry

**severity adjustment:** lower

**corrected claim:** A paused Curiosity appends an `autonomy_paused` tick record to `curiosity:ticks` every 3 s with no edge-trigger and no retention window, producing a 45 MB / 161k-event write-only stream (~5 MB/day, 11.6% of the streams directory) that nothing reads. It is a genuine bug but a disk-only one: one file, not replayed at boot, so it does not slow the system the way the 192k trace files did. It is also the second-largest instance of a broader gap: `metrics:history` (119 MB) and `persona:state` (18 MB) are heartbeat-driven streams with the same missing retention. Fix: edge-trigger skipped-tick records and give every periodic-heartbeat stream a default retention window, not just `curiosity:ticks`.

