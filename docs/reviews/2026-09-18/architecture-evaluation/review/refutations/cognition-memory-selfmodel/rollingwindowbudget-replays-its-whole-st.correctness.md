# refute:correctness:RollingWindowBudget replays its whole st

*Workflow: review · Phase: Refute · Agent id: `a3ff581d61a80af51` · Tool calls: 4*

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
    "title": "RollingWindowBudget replays its whole stream on every candidate check and the stream is never truncated",
    "kind": "right-design-undermined",
    "severity": "low",
    "claim": "`status()` reads the full `cognition:budget:<provider>` stream on every `can_spend` (once per candidate per think), four times every 30 s, and on each provider change; the 24 h window is computed over a file kept forever, currently 6,991 events / 1.6 MB / 13 ms per replay and growing linearly.",
    "evidence": [
      "simorgh/cognition/budget.py:55-60 `events = await self._ledger.read(stream_for(self._provider))` with no `from_seq`; callers router.py:139 (`can_spend`), service.py:448 (`[await b.status() for b in self._budgets.values()]` on the 30 s tick), service.py:492, :524",
      "measurement: `budget:together replay: 6991 events in 13.1 ms`; `ls -la streams/cognition%3Abudget%3Atogether.jsonl` -> 1,608,128 bytes",
      "simorgh/ledger/compaction.py:36 DEFAULT_RETENTION has no `cognition:` entry (forever); the Ledger already offers projections with snapshots (`ledger.rebuild`, used at learning/service.py:74)"
    ],
    "why_it_matters": "The durable-window design is right; replaying instead of folding is the part that will turn into 'Sim got slow' after a few months of voice use, at exactly the call site on every think.",
    "recommendation": "Keep a per-provider deque of (ts, cost) folded once at start (from the last 24 h only, via `read(from_seq=...)` or a snapshot) and appended in `record()`, or simply add `\"cognition:budget:\": \"2d\"` to retention so the replay stays bounded.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/cognition/budget.py | 1 """Per-provider rolling-window spend/call accounting, durable via the 2 Ledger stream `cognition:budget:<provider>` (docs/blueprint/subsystems/ 3 04-cognition |
| 2 | Bash | Locate budget callers, retention table, budget stream sizes | simorgh/cognition/router.py:63: self._budgets = budgets simorgh/cognition/router.py:151: provider_budget = self._budgets.get(name) simorgh/cognition/router.py:1 |
| 3 | Bash | Read callers, tick interval, ledger read signature, config, stream size |  # A call carrying pictures may only go to a provider that can see # one. Handing images to a text model does not fail -- it answers, # fluently, about an image |
| 4 | Bash | Check JSONL read path, prior reviews, retention config, replay timing | 479: async def read(self, stream: str, *, from_seq: int, limit: int \| None) -> list[Event]: 480- """Every event of `stream` from `from_seq` on. 481- 482- `from_ |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** The claim holds against the code as it is today. `RollingWindowBudget.status()` (simorgh/cognition/budget.py:60-73) calls `await self._ledger.read(stream_for(self._provider))` with no `from_seq` and no `limit`, then filters in Python by `e.ts >= cutoff`; `can_spend()` (budget.py:41-47) is just `await self.status()` plus a comparison. The JSONL backend's `read` (simorgh/ledger/backends/jsonl.py:479-505) only seeks when `from_seq > 1`, so a call with the default `from_seq=0` parses the entire file every time. Callers verified: Router iterates candidates and calls `provider_budget.can_spend(est_cost)` per candidate (router.py:151-165); CognitionService `_on_tick` calls `status()` for every budget every 30 ticks (service.py:444-448), `_emit_status` at start (service.py:490-492), and `_notice_if_provider_changed` on each provider switch (service.py:520-523). There are four budget streams on disk (claude_code_cli, gemini, ollama, together), matching "four times every 30 s". `DEFAULT_RETENTION` (simorgh/ledger/compaction.py:36) is `{"trace:": "2d", "dead:": "30d", "activity": "90d"}` with no `cognition:` prefix, and no retention override was found in ~/.simorgh, so the stream is kept forever. I reproduced the measurement: the together stream is 1,608,128 bytes, 6,991 lines, and a pure json.loads pass takes 11.2 ms (the finding's 13.1 ms included Event construction). Only the finding's line numbers are slightly off (budget.py:55-60 should be 60-62; router.py:139 should be 165; service.py:524 should be 523) — the substance is exact. This is not in the known-findings list: the known "Ledger default backend is JSONL and ~1.4 GB" is about the ledger as a whole, not this replay-on-every-candidate-check hot path. Classification as "right design undermined by implementation" is fair: durable accounting via the ledger is the project's stated principle, but folding once and appending would preserve it at O(1) per check, and the retention table already offers the one-line fix. Severity "low" is right today (~11-13 ms per replay, a handful per think) and the growth is genuinely linear and unbounded.

### evidence

- simorgh/cognition/budget.py:60-63 — `async def status(self)`: `events = await self._ledger.read(stream_for(self._provider))` (no from_seq/limit), then `recent = [e for e in events if e.ts >= cutoff]`
- simorgh/cognition/budget.py:41-42 — `can_spend` begins with `status = await self.status()`
- simorgh/cognition/router.py:143-165 — per-candidate loop `for name in names:` ... `if not await provider_budget.can_spend(est_cost): continue`
- simorgh/cognition/service.py:444-448 — `_on_tick`: `if self._tick_seconds % 30 != 0: return` then `statuses = [await b.status() for b in self._budgets.values()]`
- simorgh/cognition/service.py:490-492 (`_emit_status`) and :520-523 (`_notice_if_provider_changed`) also call `budget.status()`
- simorgh/ledger/backends/jsonl.py:479-505 — `read` only takes the seek path `if from_seq > 1:`; default from_seq=0 (ledger/client.py:189) parses every line
- simorgh/ledger/compaction.py:36 — `DEFAULT_RETENTION: dict[str, str] = {"trace:": "2d", "dead:": "30d", "activity": "90d"}` (no cognition: entry); `grep -rn retention ~/.simorgh/*.toml` -> nothing
- `ls -la ~/.simorgh/ledger/streams/ | grep budget` -> four streams: claude_code_cli 239,439 B; gemini 457 B; ollama 294,276 B; together 1,608,128 B
- `wc -l cognition%3Abudget%3Atogether.jsonl` -> 6991; json.loads pass over the file: `6991 events parsed in 11.2 ms`
- simorgh/learning/service.py:74 — `await ctx.ledger.rebuild(self._competence, "learn:outcomes")` shows the snapshot/projection facility already exists
- docs/architecture-audit-2026.md and docs/architecture-third-opinion-2026-09-18.md: grep for 'budget' hits only conversation-token budgets/compaction, not RollingWindowBudget replay — not previously reported

**severity adjustment:** keep

**corrected claim:** Same claim; cited lines should read budget.py:60-63 (status), router.py:165 (can_spend call inside the per-candidate loop at 143-165), service.py:448, :492, :523.

