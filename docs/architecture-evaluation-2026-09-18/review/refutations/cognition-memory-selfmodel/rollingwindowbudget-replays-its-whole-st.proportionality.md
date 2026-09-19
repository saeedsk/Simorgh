# refute:proportionality:RollingWindowBudget replays its whole st

*Workflow: review · Phase: Refute · Agent id: `a4f4280a703812c3a` · Tool calls: 6*

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
| 2 | Bash | Locate budget callers, retention table, budget stream size | simorgh/cognition/router.py:63: self._budgets = budgets simorgh/cognition/router.py:151: provider_budget = self._budgets.get(name) simorgh/cognition/router.py:1 |
| 3 | Bash | Read call sites, ledger read impl, stream line counts, retention/rebuild |  if images: blind = tuple(n for n in names if not getattr(self._by_name.get(n), "supports_images", False)) names = tuple(n for n in names if n not in blind) for |
| 4 | Bash | Read ledger read() implementation and from_seq support | simorgh/ledger/client.py:189: async def read(self, stream: str, *, from_seq: int = 0, limit: int \| None = None) -> list[Event]: simorgh/ledger/client.py-190- re |
| 5 | Bash | Measure budget stream span, growth rate, and parse time | {"causation_id":null,"idempotency_key":null,"payload":{"cost_usd":0.0001381,"input_tokens":794,"output_tokens":38},"seq":1,"stream":"cognition:budget:together", |
| 6 | Bash | Check whether ledger read blocks the event loop and current retention config | 2: with open(path, "r", encoding="utf-8") as fh: ---retention keys in toml: |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every element of the claim checks out against the code and the live ledger. `RollingWindowBudget.status()` (simorgh/cognition/budget.py:60-73) calls `self._ledger.read(stream_for(self._provider))` with no `from_seq`, then filters in Python by `ts >= cutoff`; `can_spend()` (budget.py:41-47) calls `status()` unconditionally. `Router.complete` calls `provider_budget.can_spend(est_cost)` inside the per-candidate loop (router.py:151-165), the 30 s tick does `[await b.status() for b in self._budgets.values()]` (service.py:448), and provider-change paths call it again (service.py:492, 523). `DEFAULT_RETENTION` in simorgh/ledger/compaction.py:36 is `{"trace:": "2d", "dead:": "30d", "activity": "90d"}` with no `cognition:` prefix, and ~/.simorgh/simorgh.toml sets no retention override, so the budget streams are kept forever. The JSONL backend's `read()` (simorgh/ledger/backends/jsonl.py:479-509) opens and parses the file synchronously inside the coroutine (plain `with open(path)`, no `to_thread`), so the replay also blocks the event loop; it does have a byte-offset seek for `from_seq > 1`, which the budget never uses. Measured on the live stream: `cognition%3Abudget%3Atogether.jsonl` is 1,608,128 bytes / 6,991 lines, parse-only replay 12.0 ms, and only 100 of those 6,991 events fall inside the last 24 h window -- 98.6% of the work is discarded. Growth is ~793 events/day over the 8.8-day span (2026-09-09 to 2026-09-18); at that rate the file reaches ~290k events / ~66 MB in a year and a replay of roughly half a second, paid once per candidate per think and blocking the loop. On the skeptic's lens (is it disproportionate for one laptop?): today it costs about 12-50 ms per think, invisible next to a multi-second LLM call, which is why 'low' is the right severity now. But the growth is unbounded and linear, the cost lands on the hot path of every think and of the voice loop, and the recommendation is a one-line retention entry (or a `from_seq` read the backend already indexes), so the fix costs far less than the problem it prevents. This is a right design (durable window in the ledger) undermined by a replay-instead-of-fold implementation, not an over-built design; it is not a bug today, but a time bomb with a trivial defuse.

### evidence

- simorgh/cognition/budget.py:60-63 -- `events = await self._ledger.read(stream_for(self._provider))` (no from_seq), then `recent = [e for e in events if e.ts >= cutoff]`
- simorgh/cognition/budget.py:41-42 -- `can_spend()` always calls `await self.status()`
- simorgh/cognition/router.py:151-165 -- `can_spend(est_cost)` inside the per-candidate `for name in names:` loop of `complete`
- simorgh/cognition/service.py:446-448 -- `_on_tick` runs `[await b.status() for b in self._budgets.values()]` every 30 ticks; also service.py:492 and :523
- simorgh/ledger/compaction.py:36 -- `DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"}`; `grep retention ~/.simorgh/simorgh.toml` returns nothing, so cognition:budget:* streams are never truncated
- simorgh/ledger/backends/jsonl.py:479-509 -- `read()` parses the whole file with a synchronous `with open(path, ...)` inside the coroutine; the byte-offset seek only engages when `from_seq > 1`, which the budget never passes
- `wc -l ~/.simorgh/ledger/streams/cognition%3Abudget%3A*.jsonl` -> together 6991, ollama 1360, claude_code_cli 1034, gemini 2 (9387 total); together file is 1,608,128 bytes
- python3 measurement on the live together stream: `parse only: 6991 events in 12.0 ms`; span 8.8 days (2026-09-09 21:27 to 2026-09-18 17:09); `events/day 793`; `events in last 24h: 100` -- 98.6% of every replay is outside the window
- simorgh/ledger/api.py:78-84 -- backend already offers `write_snapshot/read_snapshot/truncate_below`, so a bounded read needs no new infrastructure

**severity adjustment:** keep

