# refute:correctness:Failover to the Claude Code CLI is invis

*Workflow: review · Phase: Refute · Agent id: `aee82115ef898ffba` · Tool calls: 7*

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
    "title": "Failover to the Claude Code CLI is invisible to the budget model and has cost 20x the primary in total",
    "kind": "wrong-design",
    "severity": "high",
    "claim": "The second candidate in the default order has no price, no spend cap and an unknown per-call cost, so neither the per-request `max_cost_usd` gate nor the rolling spend cap can ever refuse it -- and the ledger shows 1,034 CLI calls reported at $99.32 against 6,991 Together calls at $4.56.",
    "evidence": [
      "ledger measurement: `claude_code_cli budget events: 1034 total reported cost: $99.32`; `together budget events: 6991 total cost: $4.56` (i.e. ~$0.096/call vs ~$0.00065/call); `cognition:calls` by (purpose, provider): `('draft','claude_code_cli') 526, ('review','claude_code_cli') 287, ('chat','claude_code_cli') 214`",
      "simorgh/cognition/config.py:96-99 -- `\"claude_code_cli\": ProviderConfig(max_calls=..., window_seconds=18_000.0, timeout_seconds=180.0)`: no `max_spend_usd`, no `price_in/out`",
      "simorgh/cognition/budget.py:85-92 -- `estimate_cost` docstring: providers with no configured price 'estimate to 0.0, so this never blocks them'; router.py:131-134 uses that estimate for the per-request `max_cost_usd` gate (chat's cap is $0.05, config.py:22 -- every CLI chat call exceeds it and is never refused)",
      "simorgh/cognition/router.py:139-140 -- a candidate skipped because `can_spend` is false is skipped with no log or ledger event; the only human-visible signal is the provider-changed UI notice (service.py:508-537), which fires once per switch",
      "simorgh/cognition/providers/claude_code.py:83-92,101 -- every call spawns a fresh `claude -p ... --disallowedTools \"*\"` process in a temp dir; `tools` and `max_tokens` are ignored; `input_tokens=0, output_tokens=0` reported (line 149), so the CLI's budget can only count calls"
    ],
    "why_it_matters": "The design intent ('Together is Sim's LLM now') is right for one family on one laptop; the failover undermines it. A day cap on the cheap provider silently promotes a 5x slower, 150x dearer, subscription-quota-burning backend that the budget subsystem cannot see, and 'review' -- the most frequent autonomous purpose -- goes there too. The 2026-09-11 incident in config.py:78-84 is the symptom; the structural cause is a provider with no price in a system whose only guard is price.",
    "recommendation": "Give `claude_code_cli` `only_purposes = [\"draft\"]` (or drop it from `provider_order` by default) and put a same-cost-class provider second (a second Together model via `backend = \"together\"`, or Gemini flash with a key). Give the CLI a nominal `price_in/price_out` and a `max_spend_usd` so both gates apply, and log `cognition.provider_skipped_budget` at router.py:139 so a budget-driven failover is on the ledger like a failure-driven one.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/cognition/config.py | 1 """Cognition configuration (docs/blueprint/subsystems/04-cognition.md 2 section 3.5). Every field has a working default so `[cognition]` may be 3 absent entir |
| 2 | Read | /Users/saeed/ws/Simorgh/simorgh/cognition/budget.py | 1 """Per-provider rolling-window spend/call accounting, durable via the 2 Ledger stream `cognition:budget:<provider>` (docs/blueprint/subsystems/ 3 04-cognition |
| 3 | Read | /Users/saeed/ws/Simorgh/simorgh/cognition/router.py | 1 """Provider failover and selection (docs/blueprint/subsystems/04- 2 cognition.md section 5). Ported from v1 `CognitionRouter`'s failover 3 shape: try each can |
| 4 | Bash | Read Claude CLI provider, service notice and grep for budget skip logging |  self._runner: Runner = runner or subprocess.run def available(self) -> bool: return shutil.which(self._binary) is not None async def complete( self, messages:  |
| 5 | Bash | Locate ledger cognition streams and live cognition config | blobs heads idem index.json LOCK snapshots streams cognition%3Abudget%3Aclaude_code_cli.jsonl cognition%3Abudget%3Agemini.jsonl cognition%3Abudget%3Aollama.json |
| 6 | Bash | Measure ledger budget streams per provider and call counts; check live config and prior reviews | cast_device = "Family Room TV" [cognition] [cognition.providers] [cognition.providers.ollama] model = "qwen3:4b-instruct" only_purposes = ["chat"] keep_alive =  |
| 7 | Bash | Break CLI and Together budget events down by day; check logging around failover | 2026-09-09 3 $0.15 2026-09-10 679 $53.78 2026-09-11 210 $25.53 2026-09-12 1 $0.12 2026-09-13 24 $5.08 2026-09-15 16 $1.18 2026-09-16 96 $12.89 2026-09-17 1 $0.1 |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line matches the code today and the ledger numbers reproduce exactly. (1) simorgh/cognition/config.py:73 default provider_order is ("together", "claude_code_cli", "gemini", "floor"); config.py:94-97 gives claude_code_cli only max_calls/window/timeout -- no price_in/price_out, no max_spend_usd, no only_purposes. ~/.simorgh/simorgh.toml overrides neither provider_order nor claude_code_cli (only [cognition.providers.ollama] is set), so the default order is live. (2) budget.py:86-95 docstring says unpriced providers 'estimate to 0.0, so this never blocks them'; router.py:153-154 compares that 0.0 estimate against budget.max_cost_usd (chat = $0.05 at config.py:22), so the per-request gate is a no-op for the CLI; budget.py:45 and :66-68 show the spend cap is only applied when max_spend_usd is not None, which it is for the CLI. (3) router.py:165-166 `if not await provider_budget.can_spend(est_cost): continue` -- no logger call, no ledger event; the only logging in the failover path is provider_failed (:229) and no_time_for_candidate (:175); the human-visible signal is service.py:508-537 provider_changed/UI_NOTICE which fires once per switch. (4) claude_code.py:75-79 accepts tools and max_tokens and _complete_sync (:86) drops both; argv at :91 spawns `claude -p ... --disallowedTools "*"` in a TemporaryDirectory (:96); the response at :149 reports input_tokens=0, output_tokens=0. (5) Ledger measurement reproduced: claude_code_cli 1034 events / $99.32; together 6991 / $4.56; cognition:calls by (purpose, provider): draft/claude_code_cli 526, review/claude_code_cli 287, chat/claude_code_cli 214. This is not history: CLI traffic continues after the 2026-09-11 cap change (96 calls / $12.89 reported on 2026-09-16, 4 on 2026-09-18), so the config.py:78-84 mitigation (raising Together's call cap) reduced but did not close the structural hole. Classification as 'wrong-design' is fair: it is a design (a failover that the only guard, price, cannot see) rather than a one-line bug. Two precisions: the $99.32 is the CLI's own reported total_cost_usd, which under a subscription login (claude_code.py:13-18) is notional quota consumption, not cash billed; and ~80% of the reported CLI cost ($79) landed on 2026-09-10/11 before the cap was raised, with a smaller ongoing tail since. Neither changes the verdict or the severity.

### evidence

- simorgh/cognition/config.py:73 -- provider_order default ('together', 'claude_code_cli', 'gemini', 'floor'); ~/.simorgh/simorgh.toml sets no provider_order and no [cognition.providers.claude_code_cli] table (only ollama), so this is the live order
- simorgh/cognition/config.py:94-97 -- claude_code_cli ProviderConfig has max_calls, window_seconds, timeout_seconds only; price_in/price_out default 0.0 (:44-45), max_spend_usd default None (:38)
- simorgh/cognition/budget.py:45,66-68 -- both spend gates are conditioned on `max_spend_usd is not None`; budget.py:86-95 docstring: unpriced providers 'estimate to 0.0, so this never blocks them'
- simorgh/cognition/router.py:153-154 -- `est_cost > budget.max_cost_usd` uses that 0.0 estimate; config.py:22 chat max_cost_usd=0.05, config.py:25 review=0.05
- simorgh/cognition/router.py:165-166 -- budget-refused candidate is `continue`d with no logger call and no ledger event; grep for provider_skipped/budget_exhausted in simorgh/cognition/ finds nothing; only provider_failed (:229) and no_time_for_candidate (:175) are logged
- simorgh/cognition/service.py:508-537 -- _notice_if_provider_changed fires only when previous != provider (once per switch)
- simorgh/cognition/providers/claude_code.py:75-79,86,91,96,149 -- complete() accepts tools/max_tokens and _complete_sync ignores them; argv `claude -p ... --output-format json --disallowedTools *` in a TemporaryDirectory per call; ProviderResponse(input_tokens=0, output_tokens=0, cost_usd=total_cost_usd)
- command: python3 over ~/.simorgh/ledger/streams/cognition%3Abudget%3A*.jsonl -> `claude_code_cli events: 1034 cost: $99.32`, `together events: 6991 cost: $4.56`, `gemini events: 2 cost: $0.03`, `ollama events: 1360 cost: $0.00`
- command: python3 over cognition%3Acalls.jsonl -> ('draft','claude_code_cli') 526, ('review','claude_code_cli') 287, ('chat','claude_code_cli') 214, ('consolidate','claude_code_cli') 7
- command: CLI budget events by day -> 2026-09-10: 679 ($53.78), 2026-09-11: 210 ($25.53), 2026-09-13: 24 ($5.08), 2026-09-16: 96 ($12.89), 2026-09-18: 4 ($0.48) -- ongoing after the 2026-09-11 cap change at config.py:78-84
- simorgh/cognition/providers/claude_code.py:13-18 -- headless call 'bills the subscription, not a stray key': the $99.32 is reported/notional subscription cost, not cash
- grep claude_code_cli docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html -> no matches; not in the known-findings list

**severity adjustment:** keep

**corrected claim:** The second candidate in the default order (claude_code_cli, config.py:73,94-97) has no price and no max_spend_usd, so the per-request max_cost_usd gate (router.py:153-154, estimate 0.0 per budget.py:86-95) and the rolling spend cap (budget.py:45,66-68) can never refuse it; a budget-driven skip of the primary is not logged or ledgered (router.py:165-166). The ledger shows 1,034 CLI calls with $99.32 of CLI-reported total_cost_usd (notional subscription quota, not cash) against 6,991 Together calls at $4.56; ~80% of it landed on 2026-09-10/11 before Together's call cap was raised, but the leak continues (96 calls / $12.89 on 2026-09-16).

