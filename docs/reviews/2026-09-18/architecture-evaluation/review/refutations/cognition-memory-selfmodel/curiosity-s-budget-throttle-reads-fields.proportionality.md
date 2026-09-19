# refute:proportionality:Curiosity's budget throttle reads fields

*Workflow: review · Phase: Refute · Agent id: `a4978e621f8b36b74` · Tool calls: 6*

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
| 1 | Bash | Grep remaining_fraction and read curiosity budget handler | simorgh/curiosity/service.py:233: remaining = budget.get("remaining_fraction") --- async def _on_task_failed(self, message) -> None: task_id = message.payload[" |
| 2 | Bash | Read cognition provider-status payload, guardian derivation, and test references |  """The model this provider is configured to call, for the status broadcast. Empty when the provider does not name one.""" return self._router.model_of(provider |
| 3 | Bash | Find all provider-status publishers, free flag, tests, and contract doc | simorgh/benchmark/service.py:35: topics.COGNITION_PROVIDER_STATUS, simorgh/benchmark/service.py:92: topics.COGNITION_PROVIDER_STATUS: self._on_provider, simorgh |
| 4 | Bash | Read the contract definition, second publisher, rate usage, tests and docs |  F("tokens_after", Int), O("summary_ref", Str), ]) _COMPACT_HOOK = [F("session_id", Str), F("layer", Str)] CognitionCompactPre = define(t.COGNITION_COMPACT_PRE, |
| 5 | Bash | Check tests, blueprint contract shape, rate usage, and configured caps | ---BP13 as `memory.store{kind: semantic, tags: [news, topic]}`, emit `curiosity.interest.updated`, and offer one as a share. Denied fetches (Guardian: network s |
| 6 | Bash | Check compensating controls: posture, exhausted floor, and curiosity test coverage | ---GUARD 2:spec's full table. `budget_pressure_tighten_at` and `max_consecutive_ 102: budget_pressure_tighten_at: float = 0.9 259: async def _tighten(self, to:  |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every element of the claim checks out against the code. Curiosity's `_on_provider_status` (simorgh/curiosity/service.py:231-238) reads only `budget.remaining_fraction` and `budget.free`. The single grep hit for `remaining_fraction` across simorgh/ and tests/ is that reader line; no publisher ever writes it. Cognition's two publishers of `cognition.provider.status` send `{window_seconds, calls, max_calls, spend_usd, max_spend_usd, exhausted}` on the 30s tick (cognition/service.py:452-460) and a bare `"budget": {}` on the provider-changed path (cognition/service.py:501-505). The contract (contracts/messages/cognition.py:61-72) types `budget` as an untyped `Obj()`, so no schema check could catch the mismatch. Nothing anywhere publishes `free` inside a budget object (the only `"free"` hits are verification cost tiers and a voice capability line). Consequently `worst_remaining` is never set, `_exploration_rate` (service.py:480-488) returns 1.0 unconditionally, and `budget_backoff_below_remaining`/`budget_stop_below_remaining` (curiosity/config.py:42-43) are dead. The curiosity test file has zero references to `_on_provider_status`, `worst_remaining`, or `any_free`, so the suite cannot notice. Guardian's `_fraction_used` (guardian/service.py:665-677) derives pressure from the real fields, confirming the reader's point that the correct derivation already exists next door. The blueprint (docs/blueprint/subsystems/13-curiosity.md:228-232, 278) specified `remaining_fraction`/`free` while 04-cognition.md:68 specified the fields actually sent: two blueprint pages disagree and the code implemented each side of its own page. Classification: (c) a genuine bug in the project's "unconnected wire" shape, not an architectural error.

Skeptic lens on proportionality: it is not an architectural problem, and the recommendation is not disproportionate; the fix is roughly five lines (derive `remaining` from calls/max_calls and spend/max_spend, tolerate the empty `{}` payload, honour `exhausted`, drop `free`). Compensating controls do exist and bound the damage: Cognition's own per-provider cap still refuses/fails over when `exhausted` (the router's floor path), the `min_explore_interval_seconds` cooldown (service.py:416-418) is real and tested, and the default caps are small (max_spend_usd $2/day, cognition/config.py:84/101). So the throttle's absence means curiosity spends the last 20% of a window at full rate rather than half, then hits the hard cap, rather than unbounded spend. That argues against raising severity, but not below medium: a designed safety throttle in the one subsystem that spends money on its own initiative silently never fires, has config keys that look live, and has no test. Curiosity also ignores Guardian posture entirely (no `posture` reference in curiosity/service.py), so Guardian's 90% budget-pressure tighten (guardian/config.py:102) does not reach it either; the Curiosity-side backoff was the only designed proportional brake.

### evidence

- simorgh/curiosity/service.py:231-238 -- `remaining = budget.get("remaining_fraction")`; `free = bool(budget.get("free", False))`; `worst_remaining` set only when `remaining is not None`
- simorgh/curiosity/service.py:480-488 -- `_exploration_rate` returns 1.0 when `worst_remaining is None`; thresholds read from config
- simorgh/curiosity/config.py:42-43 -- `budget_backoff_below_remaining: float = 0.2`, `budget_stop_below_remaining: float = 0.05` (dead)
- simorgh/cognition/service.py:452-460 -- tick publisher payload `budget: {window_seconds, calls, max_calls, spend_usd, max_spend_usd, exhausted}`
- simorgh/cognition/service.py:501-505 -- second publisher (provider changed/started) sends `"budget": {}`
- simorgh/contracts/messages/cognition.py:61-72 -- `F("budget", Obj())` untyped, so the field mismatch is invisible to contract validation
- `grep -rn remaining_fraction simorgh tests` -> only simorgh/curiosity/service.py:233
- `grep -rn '"free"' simorgh` -> verification cost tiers, voice capability line, and the curiosity reader; no budget publisher sets it
- `grep -n '_on_provider_status|budget|worst_remaining|any_free' tests/simorgh/curiosity/test_service.py` -> no handler test (only a comment at line 216 about the 2026-09-07 overnight drain)
- simorgh/guardian/service.py:665-677 -- `_fraction_used` derives spend/max_spend then calls/max_calls from the real payload; guardian/config.py:102 `budget_pressure_tighten_at = 0.9`
- `grep -n 'posture|exhausted' simorgh/curiosity/service.py` -> no hits: Curiosity reads neither Guardian posture nor the `exhausted` flag
- docs/blueprint/subsystems/13-curiosity.md:228-232,278 specifies `remaining_fraction`/`free: true`; docs/blueprint/subsystems/04-cognition.md:68 specifies `{window_seconds, calls, max_calls, spend_usd, max_spend_usd, exhausted}` -- the two blueprint pages disagree
- simorgh/curiosity/service.py:416-418 -- `min_explore_interval_seconds` cooldown is live (the compensating control that does work); cognition/config.py:84,101 default `max_spend_usd` $2/day bounds the damage

**severity adjustment:** keep

