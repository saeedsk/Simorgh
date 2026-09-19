# refute:correctness:The floor provider is an in-band success

*Workflow: review · Phase: Refute · Agent id: `a1aa0ca40e684d143` · Tool calls: 8*

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
    "title": "The floor provider is an in-band success that 41 sites must special-case, and the purposes/budget table is largely fiction",
    "kind": "over-engineering",
    "severity": "medium",
    "claim": "A 'provider' that always answers with canned text has produced 0 of 9,379 real replies but forced floor-handling into 18 files outside cognition and once cascaded a budget outage into a Guardian lockdown; meanwhile 9 purposes are configured, 4 account for 99.97% of calls, the primary provider overrides `max_tokens_out` to 4,000 while the pre-call cost estimate still uses the configured 512-1,000, and `Budget.require_real` from the purposes table is never read.",
    "evidence": [
      "ledger: `floor calls: 0` of 9,379; `grep -rln '\"floor\"\\|floor=' simorgh --include='*.py' | grep -v cognition | wc -l` -> 18 files, 41 sites",
      "simorgh/guardian/service.py `_on_health_finding` comment: 'a floor-reply-pinned valence locked the whole session for hours over what was really a budget problem'",
      "ledger purposes: chat 4,651 + draft 2,443 + review 2,101 + consolidate 182 of 9,379; plan 1, decompose 1, research/reground/ensemble 0",
      "simorgh/cognition/providers/together.py:217-222 `_room_to_answer` -> `max(max_tokens, MIN_REASONING_MAX_TOKENS=4_000)` vs config.py:22-30 (chat 1,000; review 1,000; reground 512) and router.py:131 `estimate_cost(prompt_tokens, budget.max_tokens_out)`",
      "simorgh/cognition/service.py:282 `require_real=payload.get(\"require_real_provider\", False)` -- the purpose's own `require_real` (config.py:30 ensemble=True) is never consulted"
    ],
    "why_it_matters": "For one laptop the honest answer to 'no model' is an error the caller already handles (`no_real_provider` exists and orchestration/session.py:919-924 turns it into a clean outcome). Making it a successful reply pushes the outage into data that Persona, Reflection, Guardian, Memory and Curiosity each had to learn to recognise -- the module boundaries you built are being paid for by every subsystem re-deriving 'was that real?'.",
    "recommendation": "Delete FloorProvider and make every purpose `require_real`; collapse `DEFAULT_PURPOSE_BUDGETS` to chat/draft/review/consolidate and let the Together provider's 4,000-token floor be the configured number so the pre-call estimate matches what is sent.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count floor-handling sites outside cognition |  17 36 simorgh/benchmark/runner.py:500: if payload.get("floor"): simorgh/interface/httpapi.py:845: entry.update(summary=(p.get("text") or "")[:160], floor=p.get |
| 2 | Bash | Check guardian comment, together token floor, config budgets, router estimate, require_real usage | 331: # a floor-reply-pinned valence locked the whole session for 332: # hours over what was really a budget problem. --- # spend on the floor because the Router |
| 3 | Bash | Read service.py budget assembly, router candidate loop and floor fallthrough, FloorProvider, ledger and toml |  # `max_tokens` is how much the caller wants *back*. It used to set # the input ceiling as well, so asking for a 2000-token answer also # said "and you may only |
| 4 | Bash | Read purpose budget lookup, FloorProvider, Together usage, Guardian comment, ledger streams |  await sub.unsubscribe() async def health(self) -> Health: if self._no_real_provider_since is not None: elapsed = self._ctx.clock.now() - self._no_real_provider |
| 5 | Bash | Read Together reasoning-floor condition and list non-action ledger streams | DEFAULT_BASE_URL = "https://api.together.ai/v1" DEFAULT_REASONING_EFFORT = "low" #: The smallest `max_tokens` worth sending to a reasoning model. #: #: Thinking |
| 6 | Bash | Count cognition calls by provider and purpose in the ledger; find floor text checks | {"causation_id":null,"idempotency_key":null,"payload":{"compaction":[],"cost_usd":0.0001381,"floor":false,"provider":"together","purpose":"draft","tokens":832}, |
| 7 | Bash | Check provider order defaults, reasoning effort default, toml config, and whether prior reviews already cover floor/purposes | simorgh/cognition/config.py:48: # "together"` with a different `model` or `reasoning_effort` (a simorgh/cognition/config.py:51: reasoning_effort: str = "" simor |
| 8 | Bash | Check how Together provider is constructed and whether reasoning_effort default reaches it | 161: real_providers.append(TogetherProvider( 162- api_key=ctx.secrets.get("TOGETHER_API_KEY"), 163- model=together_cfg.model or together_default_model, 164- tim |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The substantive claims hold against the code and the ledger today; two numbers are inflated and one line reference is off. (1) Floor never used: ~/.simorgh/ledger/streams/cognition:calls.jsonl parsed with python: 9,379 think.completed records, floor=0, providers together 6,983 / ollama 1,360 / claude_code_cli 1,034 / gemini 2; purposes chat 4,651 / draft 2,443 / review 2,101 / consolidate 182 / plan 1 / decompose 1 -- exactly as claimed. FloorProvider exists (providers/base.py:30-52, always available(), returns canned TEMPLATES) and is in the default provider_order (config.py:73). (2) Spread of floor handling: the cited grep gives 17 files / 36 sites, not 18 / 41, and at least three of those are not provider-floor handling at all (ledger/backends/jsonl.py:241 `floor=known.head` is an unrelated kwarg; learning/service.py:173,179 and contracts/messages/learn.py:18 use "floor" as a pipeline-skipped outcome enum; httpapi.py:1130,1144 use floor=True as an error marker). Even discounting those, floor is re-derived in orchestration/session.py (9 sites), worker.py, verification/service.py, memory/consolidation.py, curiosity/service.py, reflection/critique.py+service.py, planning/bridge.py, benchmark/runner.py, contracts/tidy.py -- the boundary-tax point stands. (3) Guardian cascade: guardian/service.py:331-332 comment confirms it as a live-caught historical event, now mitigated by health_critical_tightens_to defaulting to "guarded" -- history, correctly framed as "once". (4) Token mismatch: together.py:67 MIN_REASONING_MAX_TOKENS=4_000, :133 `body["max_tokens"] = self._room_to_answer(int(max_tokens))`, :231-233 applies max() whenever reasoning_effort is set; service.py:161-166 constructs the primary Together provider without overriding reasoning_effort so the constructor default "low" (together.py:85, DEFAULT_REASONING_EFFORT="low") applies, i.e. the 4,000 floor is active by default. router.py:153 (not :131) `est_cost = provider_budget.estimate_cost(prompt_tokens, budget.max_tokens_out)` with chat/review=1,000 and reground=512 from config.py:22-29. Confirmed mismatch, though note the estimate is a pre-call ceiling only; real spend is recorded from the actual response (router.py ~:250 `provider_budget.record(response)`), so the consequence is an under-estimated gate, not wrong billing. (5) require_real: service.py:282 `require_real=payload.get("require_real_provider", False)`; grep over simorgh/ shows no read of `budget_cfg.require_real` or any purposes-table require_real anywhere -- config.py:24,25,28,30 set it for plan/review/reground/ensemble and it is dead. Confirmed: a classic unconnected wire. Not in the known-findings list: none of docs/architecture-review-2026-09-18.html, architecture-audit-2026.md, architecture-third-opinion-2026-09-18.md mention FloorProvider, require_real, MIN_REASONING_MAX_TOKENS or the purposes table. Classification: the dead require_real and estimate/send mismatch are (b) right design undermined by implementation; the in-band floor success and 9-purpose table are (a) over-built for the scale; no (c) bug beyond the dead field. One caveat on the ledger count: the ledger was cleaned on 2026-09-07 so 9,379 is a post-cleanup window, and zero floor use also reflects that providers have been up, which is what a last resort looks like when it is not needed -- the finding's cost/benefit argument survives but "produced 0 replies" is weaker evidence than it reads.

### evidence

- python parse of ~/.simorgh/ledger/streams/cognition%3Acalls.jsonl -> calls 9379 floor 0; providers [('together', 6983), ('ollama', 1360), ('claude_code_cli', 1034), ('gemini', 2)]; purposes [('chat', 4651), ('draft', 2443), ('review', 2101), ('consolidate', 182), ('plan', 1), ('decompose', 1)]
- grep -rln '"floor"\|floor=' simorgh --include='*.py' | grep -v cognition | wc -l -> 17 (not 18); grep -rn ... | wc -l -> 36 (not 41); false positives: simorgh/ledger/backends/jsonl.py:241 `floor=known.head` (unrelated), simorgh/learning/service.py:173,179 + contracts/messages/learn.py:18 (outcome enum 'floor'), simorgh/interface/httpapi.py:1130,1144 (floor as error marker)
- simorgh/cognition/providers/base.py:30-52 class FloorProvider: name='floor', available() -> True, complete() returns respond_for_purpose(Purpose.CHAT) canned text; simorgh/cognition/config.py:73 provider_order default ('together','claude_code_cli','gemini','floor')
- simorgh/guardian/service.py:329-333 _on_health_finding comment: 'live-caught, a floor-reply-pinned valence locked the whole session for hours over what was really a budget problem' -- now tightens to config health_critical_tightens_to (default guarded)
- simorgh/cognition/providers/together.py:67 MIN_REASONING_MAX_TOKENS = 4_000; :133 body['max_tokens'] = self._room_to_answer(int(max_tokens)); :231-233 returns max(max_tokens, 4_000) when self._reasoning_effort truthy; :85 reasoning_effort default DEFAULT_REASONING_EFFORT='low'; simorgh/cognition/service.py:161-166 primary Together constructed without reasoning_effort override so 'low' applies
- simorgh/cognition/router.py:153 est_cost = provider_budget.estimate_cost(prompt_tokens, budget.max_tokens_out) (finding cited :131); simorgh/cognition/config.py:22-30 chat Budget(12_000, 1_000,...), review (12_000, 1_000), reground (8_000, 512), ensemble require_real=True
- simorgh/cognition/service.py:258 budget_cfg = self._config.purposes.get(purpose.value); :277-283 Budget(... require_real=payload.get('require_real_provider', False)) -- grep -rn require_real simorgh shows no read of budget_cfg.require_real anywhere; router.py:244 `if budget.require_real:` only sees the payload value
- simorgh/orchestration/session.py:919-924: think_reply None -> chat profile returns Outcome('completed', result_summary='', floor=True), else Outcome('blocked', reason='no real provider'); service.py:362 emits error code no_real_provider
- grep -n -i 'floorprovider|floor provider|require_real|MIN_REASONING|purposes table' over docs/architecture-review-2026-09-18.html, docs/architecture-audit-2026.md, docs/architecture-third-opinion-2026-09-18.md -> no matches (not previously reported)

**severity adjustment:** keep

**corrected claim:** A FloorProvider that always 'succeeds' with canned text is in the default provider order (config.py:73) but has produced 0 of the 9,379 replies in the current (post-2026-09-07-cleanup) ledger; floor-awareness is nonetheless re-derived in roughly 14 files / ~30 sites outside cognition (17 files / 36 grep hits, of which ledger/jsonl.py, learning's outcome enum and httpapi's error marker are unrelated uses of the word), and once (guardian/service.py:331-332, since mitigated) escalated a budget outage into a Guardian lockdown. Of 9 configured purposes, 4 account for 99.97% of calls (plan 1, decompose 1, research/reground/ensemble 0). The primary Together provider runs with reasoning_effort='low' by default and therefore raises every max_tokens to at least 4,000 (together.py:67,133,231-233) while router.py:153 pre-estimates cost with the configured 512-1,000; actual spend is still recorded from the real response, so this under-estimates the per-call gate rather than mis-bills. The purposes table's `require_real` field (config.py:24-30) is never read: service.py:282 takes it only from the request payload.

