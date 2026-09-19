# refute:proportionality:Failover to the Claude Code CLI is invis

*Workflow: review · Phase: Refute · Agent id: `a39b64c2939760983` · Tool calls: 16*

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
| 4 | Bash | Show CLI provider call path, live config and env overrides |  self._runner: Runner = runner or subprocess.run def available(self) -> bool: return shutil.which(self._binary) is not None async def complete( self, messages:  |
| 5 | Bash | List ledger stream files for cognition and budget | blobs heads idem index.json LOCK snapshots streams 7 |
| 6 | Bash | Read CLI provider docstring and env handling; list cognition streams | """Claude Code CLI provider (docs/blueprint/subsystems/04-cognition.md section 11): body ported unchanged from v1 `src/cognition/claude_code_provider.py`, `comp |
| 7 | Bash | Tally budget events per provider and per day from the ledger | ['action%3A237771e4b834.jsonl', 'action%3A319eba81d6e1.jsonl', 'trace%3Ac9ba6ced-9919-408c-86b9-5acb8e085b35.jsonl', 'trace%3A3239b4b9-01b8-4342-89d9-d2a8460889 |
| 8 | Bash | Tally per-provider budget spend and per-day CLI usage; show provider-changed notice | claude_code_cli events 1034 cost 99.32 per-day: {'2026-09-10': (591, 31.41), '2026-09-11': (126, 28.42), '2026-09-12': (176, 19.75), '2026-09-13': (9, 2.58), '2 |
| 9 | Bash | Check purpose filter wiring, skipped-budget logging, and CLI subscription type | tests/simorgh/cognition/test_provider_ollama.py:128: cfg = Config.from_mapping({"providers": {"ollama": {"model": "qwen3:4b", "only_purposes": ["chat"], tests/s |
| 10 | Bash | Show how the service builds the provider order and purpose filter |  vision_model=ollama_cfg.vision_model, )) if "ollama" not in self._config.provider_order: order = [n for n in self._config.provider_order if n != "floor"] + ["o |
| 11 | Bash | Compute CLI cost per purpose and the 09-17 provider timeline and failover logs | draft n 526 avg $ 0.118 >0.05: 381 review n 287 avg $ 0.049 >0.05: 104 consolidate n 7 avg $ 0.14 >0.05: 6 chat n 214 avg $ 0.105 >0.05: 206 ('2026-09-17 00', ' |
| 12 | Bash | Check whether prior reviews already report the CLI failover cost issue | (Bash completed with no output) |
| 13 | Bash | Show CLI usage bursts by local hour against Together's rolling-window state, and find logs | 2026-09-09 23 cli 3 $ 0.15 \| together 24h calls 161 spend 0.144 2026-09-10 06 cli 145 $ 7.28 \| together 24h calls 668 spend 0.5 2026-09-10 07 cli 189 $ 10.34 \|  |
| 14 | Bash | Show purposes in the 09-16 CLI burst and any failover log lines | ('2026-09-16 17', 'claude_code_cli', 'chat') 9 ('2026-09-16 17', 'claude_code_cli', 'draft') 34 ('2026-09-16 17', 'claude_code_cli', 'review') 3 ('2026-09-16 17 |
| 15 | Bash | Check CLI subscription type and where warning logs are written | subscriptionType: None \| hasApiKey: False \| keys: ['oauthAccount'] |
| 16 | Bash | Show route and tier selection for a think request and env order override |  tool_instructions = _tool_instruction_block(payload) think_messages: list[dict] = [] if protected_text: think_messages.append({"role": "system", "content": pro |

## Structured reply

**refuted:** False

**verdict:** partly-true

**severity adjustment:** lower

**corrected claim:** The Claude Code CLI provider ships with no price and no spend cap by default, so the per-request `max_cost_usd` gate cannot refuse it (its estimate is 0.0 by design) and a budget-driven skip of the primary leaves no per-call trace on the ledger. However: (1) the "$99.32" is Claude Code's self-reported API-equivalent `total_cost_usd`, not money -- the provider deliberately strips API keys so calls bill the creator's subscription (~/.claude.json has an oauthAccount and no API key), so the real cost is 5-hour quota, which the existing `max_calls=500 / window 18,000 s` already meters in the right unit; (2) ~$79 of the $99 fell on 09-10/09-11 while Together sat at exactly its old 1,500-call cap -- the creator fixed that on 09-11 (6,000 calls / $2), and every CLI burst since has happened with Together at 200-650 calls and $0.14-0.42 in-window, i.e. failure/timeout-driven failover, which IS logged (`cognition.provider_failed`) and announced on screen with its reason; (3) `max_spend_usd` on `claude_code_cli` already works today via one TOML line because `status()` sums the CLI's reported cost. What remains is a config-default omission plus one missing log line, not a wrong design.

**reasoning:** Mechanism verified line by line: config.py:94-97 gives claude_code_cli only max_calls/window/timeout; budget.py:86-95 documents that unpriced providers estimate to 0.0 "so this never blocks them"; router.py:151-166 uses that estimate for the per-request gate and skips a can_spend=false candidate with a bare `continue` (no log); claude_code.py:147-151 reports input/output tokens 0 and cost from the CLI's total_cost_usd. Ledger tallies match the finding exactly (1,034 CLI events / $99.32; 6,991 Together / $4.56; purposes draft 526, review 287, chat 214, consolidate 7). Per-purpose CLI averages: chat $0.105 (206/214 over the $0.05 cap), draft $0.118, review $0.049.

Where the finding overreaches: (a) Cost framing. claude_code.py:20-21 and 51/161-165 strip ANTHROPIC_API_KEY/AUTH_TOKEN/OAUTH_TOKEN precisely so the call "bills the subscription, not a stray key"; ~/.claude.json shows an oauthAccount and no primaryApiKey. So $99.32 is quota-equivalent, not spend; the per-request dollar gate is the wrong instrument for a flat-rate backend, while calls-per-5h is the unit Claude's subscription actually meters. (b) Causal story. Bucketing CLI budget events by local hour against Together's rolling 24h window: 09-10 06-18h and 09-11 20-21h bursts (~$79) occurred with Together at exactly 1,500 calls (the old cap) -- budget-driven. config.py:76-84 records the fix (6,000 / $2). Every later burst (09-13, 09-15, 09-16 17-18h = 96 calls/$12.89) ran with Together at 205-635 calls and $0.14-0.42, and in the 09-16 hour Together simultaneously answered 74 chat + 50 draft + 55 review -- so those were slice-timeout/transient failovers, logged by router.py:227-230 and noticed by service.py:508-537, which names the cap when it is the reason (lines 521-531). Post-fix, budget-driven promotion has not recurred. (c) "no spend cap" is a default, not a capability gap: budget.py:64-68 sums payload cost_usd and 80-81 prefers the CLI's reported cost, so `max_spend_usd` under [cognition.providers.claude_code_cli] would bind today with zero code. ~/.simorgh/simorgh.toml sets nothing for the CLI.

Proportionality at this scale: the useful parts of the recommendation (`only_purposes`, `max_spend_usd`, one `provider_skipped_budget` log line at router.py:165) are three TOML lines and one logger call -- cheap and worth doing. The parts that go too far: adding nominal price_in/out to drive the per-request dollar gate on a subscription backend, and dropping the CLI from the default order, which would remove the only working failover (gemini has 2 calls total in the ledger, ollama is appended behind the CLI at service.py:197-201 and is chat-only). Kind is closer to "right design, default under-configured" than "wrong-design"; severity high -> medium.

### evidence

- simorgh/cognition/config.py:94-97 -- `"claude_code_cli": ProviderConfig(max_calls=int(os.environ.get("SIMORGH_CLAUDE_CODE_MAX_CALLS", "500")), window_seconds=18_000.0, timeout_seconds=180.0)` -- no price, no max_spend_usd (confirmed)
- simorgh/cognition/config.py:76-84 -- comment recording the 2026-09-11 incident and the fix: Together max_calls 1500 -> 6000, max_spend_usd $2.0
- simorgh/cognition/budget.py:86-95 -- estimate_cost docstring: unpriced providers 'estimate to 0.0, so this never blocks them'; budget.py:64-68 status() sums payload cost_usd, so max_spend_usd would bind for the CLI today; budget.py:80-81 prefers response.cost_usd
- simorgh/cognition/router.py:151-166 -- per-request gate `if est_cost > budget.max_cost_usd` and `if not await provider_budget.can_spend(est_cost): continue` with no log; router.py:227-230 logs `cognition.provider_failed` for failure-driven failover
- simorgh/cognition/providers/claude_code.py:51 `_CREDENTIAL_ENV_VARS_TO_STRIP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")`; :20-21 'a headless call bills the subscription, not a stray key'; :147-151 `input_tokens=0, output_tokens=0, cost_usd=payload.get("total_cost_usd", 0.0)`
- ~/.claude.json: `subscriptionType: None | hasApiKey: False | keys: ['oauthAccount']` -- CLI is signed in via OAuth subscription, no API key; `claude --version` = 2.1.277
- simorgh/cognition/service.py:508-537 -- `_notice_if_provider_changed` logs `cognition.provider_changed` with why='<prev> reached its cap of N calls per H h' / 'reached its $X per H h budget' and publishes a UI notice; service.py:197-201 appends ollama AFTER the CLI and gemini in provider_order
- ~/.simorgh/simorgh.toml [cognition]: only `[cognition.providers.ollama]` (only_purposes=["chat"]); nothing for claude_code_cli, no provider_order, no routes
- Ledger tally (~/.simorgh/ledger/streams/cognition%3Abudget%3A*.jsonl): `claude_code_cli events 1034 cost 99.32`; `together events 6991 cost 4.56`; `gemini events 2 cost 0.03`; `ollama events 1360 cost 0`; calls by (purpose, provider): draft/claude_code_cli 526, review/claude_code_cli 287, chat/claude_code_cli 214, consolidate/claude_code_cli 7
- CLI per-purpose averages from cognition:calls: `chat n 214 avg $0.105 >0.05: 206`, `draft n 526 avg $0.118`, `review n 287 avg $0.049`
- CLI bursts vs Together rolling-24h state (local hour): `2026-09-10 07 cli 189 $10.34 | together 24h calls 1500 spend 0.869`; `2026-09-10 18 cli 91 $22.52 | together 1500`; `2026-09-11 20 cli 144 $13.49 | together 1500 spend 0.977` (budget-driven, pre-fix); post-fix: `2026-09-16 17 cli 46 $5.91 | together 24h calls 357 spend 0.25`; `2026-09-16 18 cli 50 $6.98 | together 479 spend 0.36`; `2026-09-18 14 cli 3 | together 208 spend 0.206`
- Same hour 2026-09-16 17: together answered chat 74, draft 50, review 55 while claude_code_cli took draft 34, chat 9, review 3 -- interleaved, so failover was per-call failure/timeout, not cap exhaustion
- ~/.simorgh/interface/console.log: 11 `thinking moved from ... to ...` notices in one afternoon (e.g. line 286 `13:49:05 [warning] thinking moved from together to claude_code_cli -- slower per turn, and it counts against the Claude Code quota`), switching back within 30-60 s -- the human-visible signal fires per switch, not once
- grep of docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html, docs/architecture-third-opinion-2026-09-18.md for claude_code_cli/failover/max_spend: no hits -- not previously reported

