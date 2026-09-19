# refute:correctness:Curiosity's budget throttle reads fields

*Workflow: review · Phase: Refute · Agent id: `a2eccdbd1674fbfae` · Tool calls: 5*

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
    "title": "Curiosity's budget throttle reads fields Cognition never sends",
    "kind": "bug",
    "severity": "medium",
    "claim": "`_on_provider_status` reads `budget.remaining_fraction` and `budget.free`, but the provider-status payload carries `calls/max_calls/spend_usd/max_spend_usd/exhausted`, so `worst_remaining` stays None, `_exploration_rate()` is always 1.0, and `budget_backoff_below_remaining`/`budget_stop_below_remaining` are dead config.",
    "evidence": [
      "simorgh/curiosity/service.py:231-238 -- `remaining = budget.get(\"remaining_fraction\")`, `free = bool(budget.get(\"free\", False))`",
      "simorgh/cognition/service.py:456-460 publishes `\"budget\": {\"window_seconds\", \"calls\", \"max_calls\", \"spend_usd\", \"max_spend_usd\", \"exhausted\"}`; `grep -rn 'remaining_fraction' simorgh` finds only the Curiosity reader",
      "simorgh/curiosity/service.py:480-488 `_exploration_rate` returns 1.0 when `remaining is None`",
      "guardian/service.py `_on_provider_status` computes `_fraction_used(p.get(\"budget\"))` from the real fields -- the derivation Curiosity should share"
    ],
    "why_it_matters": "The 2026-09-07 'unattended night drained the daily budget' incident was answered with `min_explore_interval_seconds` (which works) while the budget-proportional backoff designed for it has silently never fired. It is a fresh instance of the project's dominant bug shape, in the subsystem that spends money on its own initiative.",
    "recommendation": "Compute `remaining = 1 - max(calls/max_calls, spend/max_spend)` from the fields actually sent (or lift Guardian's `_fraction_used` into contracts) and delete the `free` flag, which nothing sets.",
    "confidence": 0.95
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Grep for budget fields and read curiosity service | simorgh/curiosity/service.py:233: remaining = budget.get("remaining_fraction") --- simorgh/verification/service.py:43:_ORDER = {"free": 0, "cheap": 1, "expensiv |
| 2 | Bash | Check cognition publisher, guardian derivation, config usage, tests and known-findings docs | simorgh/benchmark/service.py:35: topics.COGNITION_PROVIDER_STATUS, simorgh/benchmark/service.py:92: topics.COGNITION_PROVIDER_STATUS: self._on_provider, simorgh |
| 3 | Bash | Check second publisher, contract schema, blueprint, tests and config |  # It used to send only the name, so the self model had no # "Thinking with:" line until the first 30-second tick -- exactly # the window in which a human asks  |
| 4 | Bash | Check curiosity tests, README, BudgetStatus shape, known docs, and ledger for real payload | tests/simorgh/curiosity/test_service.py:216: exploration tick each, draining the day's LLM budget overnight. --- ## Known simplifications against the spec (see  |
| 5 | Bash | Confirm BudgetStatus fields and curiosity tests for the budget path | simorgh/cognition/config.py:37: window_seconds: float = 18_000.0 simorgh/cognition/config.py:83: window_seconds=86_400.0, simorgh/cognition/config.py:96: window |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line checks out against the code as it is today. Curiosity's `_on_provider_status` (simorgh/curiosity/service.py:231-238) reads `budget.get("remaining_fraction")` and `budget.get("free")`. Cognition is the only publisher of COGNITION_PROVIDER_STATUS and sends two payload shapes: the 30-second tick (cognition/service.py:452-460) with `window_seconds/calls/max_calls/spend_usd/max_spend_usd/exhausted`, and the provider-selected notice (cognition/service.py:500-505) with `"budget": {}`. Neither carries `remaining_fraction` or `free`; the `BudgetStatus` dataclass they are built from (cognition/api.py:100-107) has no such fields, and the contract (contracts/messages/cognition.py:61-71) types `budget` as an untyped `Obj()`, so nothing validates the mismatch. `grep -rn remaining_fraction simorgh tests` returns exactly one hit: the Curiosity reader. Hence `_BudgetState.worst_remaining` stays None, `_exploration_rate()` (curiosity/service.py:480-488) returns 1.0 unconditionally, and `budget_backoff_below_remaining`/`budget_stop_below_remaining` (curiosity/config.py:42-43) are read only inside that dead branch. `any_free` (service.py:59, 421, 446) is likewise never set. Guardian's `_fraction_used` (guardian/service.py:665-677) derives pressure from the real fields, confirming the fields Curiosity should be consuming. No test under tests/simorgh/curiosity/ publishes a provider status or exercises `_exploration_rate`, so the suite cannot catch it; the only budget-related test (test_service.py:215-228) covers `min_explore_interval_seconds`, which is the mitigation the finding describes. The field names Curiosity expects come from the blueprint (docs/blueprint/subsystems/13-curiosity.md:230,278), i.e. spec-level names that Cognition's implementation never adopted -- a genuine unconnected-wire bug, and not on the known-findings list (grep of the three review docs for curiosity+budget finds nothing). Severity 'medium' is right: money-spending autonomy has lost its proportional throttle, but the interval cap bounds the damage.

### evidence

- simorgh/curiosity/service.py:231-238 -- `remaining = budget.get("remaining_fraction")`; `free = bool(budget.get("free", False))`; worst_remaining only set when remaining is not None
- simorgh/cognition/service.py:452-460 -- tick publish: `"budget": {"window_seconds", "calls", "max_calls", "spend_usd", "max_spend_usd", "exhausted"}`
- simorgh/cognition/service.py:500-505 -- selection publish: `"budget": {}`
- simorgh/cognition/api.py:100-107 -- BudgetStatus fields: provider, calls_in_window, max_calls, spend_usd, max_spend_usd, window_seconds, exhausted (no remaining_fraction, no free)
- simorgh/contracts/messages/cognition.py:61-71 -- `F("budget", Obj())` untyped, so the schema cannot catch the mismatch
- `grep -rn 'remaining_fraction' simorgh tests` -> only simorgh/curiosity/service.py:233
- `grep -rn 'PROVIDER_STATUS' simorgh | grep publish`-equivalent: cognition/service.py:452 and :501 are the sole publishers
- simorgh/curiosity/service.py:480-488 -- `_exploration_rate` returns 1.0 when `remaining is None`
- simorgh/curiosity/config.py:42-43 -- budget_backoff_below_remaining=0.2, budget_stop_below_remaining=0.05, referenced only in the dead branch (grep)
- simorgh/guardian/service.py:665-677 -- `_fraction_used` derives from spend_usd/max_spend_usd then calls/max_calls, with exhausted -> 1.0
- docs/blueprint/subsystems/13-curiosity.md:230,278 -- the spec names `remaining_fraction`; Curiosity implemented the spec, Cognition did not
- `grep -rn 'provider_status\|_exploration_rate\|any_free\|worst_remaining' tests/simorgh/curiosity/` -> no hits; tests/simorgh/curiosity/test_service.py:215-228 covers only min_explore_interval_seconds
- grep of docs/architecture-review-2026-09-18.html, docs/architecture-audit-2026.md, docs/architecture-third-opinion-2026-09-18.md for curiosity+budget -> no match; not previously reported

**severity adjustment:** keep

