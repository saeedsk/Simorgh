# refute:proportionality:The floor provider is an in-band success

*Workflow: review · Phase: Refute · Agent id: `ae796967e20dd2a05` · Tool calls: 13*

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
| 1 | Bash | Count floor-handling sites outside cognition |  17 --- 36 --- simorgh/benchmark/runner.py:500: if payload.get("floor"): simorgh/interface/httpapi.py:845: entry.update(summary=(p.get("text") or "")[:160], flo |
| 2 | Bash | Read cited cognition config, provider, router and service lines | """Cognition configuration (docs/blueprint/subsystems/04-cognition.md section 3.5). Every field has a working default so `[cognition]` may be absent entirely -- |
| 3 | Bash | Read provider, router, service and Budget definitions | ==== TOGETHER # # Live-caught, 2026-09-08: this HTTP call already happened and # Together already billed `usage.prompt_tokens`/ # `completion_tokens` (reasoning |
| 4 | Bash | Read router floor fallback, floor provider, Guardian health handler, session no_real_provider handling | ==== router 225-275 # skipped). Visible even when this is the last candidate # and the exception is about to surface as `last_error`. if self._logger is not Non |
| 5 | Bash | Locate floor provider, ledger streams, and the live cognition config | ==== floor refs in cognition simorgh/cognition/service.py:25:from .providers.base import FloorProvider simorgh/cognition/service.py:145: self._floor = FloorProv |
| 6 | Bash | Read live config, FloorProvider, ledger record shape, and locate the cognition calls stream | ==== full toml (cognition + providers) [voice] barge_in = false keep_audio = true vad_sensitivity = "high" barge_in_calibrate_ms = 1200 barge_in_speech_ms = 350 |
| 7 | Bash | Count cognition calls by provider and purpose in the ledger; check Together reasoning_effort default | total 9379 floor 0 providers [('together', 6983), ('ollama', 1360), ('claude_code_cli', 1034), ('gemini', 2)] purposes [('chat', 4651), ('draft', 2443), ('revie |
| 8 | Bash | Check Together defaults, reply shape for floor, dial retry, and persona handling | ==== config 68-105 class Config: # The creator, 2026-09-07: Together is Sim's LLM now, GLM-5.3-Flash the # default model. It leads the order, so it is what answ |
| 9 | Bash | Check whether reasoning_effort is on by default, which purposes are wired, ledger span, and persona floor handling | ==== together ctor ) -> None: # A second instance -- a stronger model or more effort for escalated # work -- is a separate provider to the Router, with its own  |
| 10 | Bash | Read the think path around floor, the max_tokens use, critical-finding publishers, and session error handling | ==== service 340-400 think_messages.append({"role": "user", "content": compacted.text}) if not think_messages: think_messages.append({"role": "user", "content": |
| 11 | Bash | Confirm Together reasoning default, cost estimate arithmetic, purpose loader, and Guardian default | ==== ctor default check reasoning_effort default: 'low' -> _room_to_answer(1000) = 4000 _room_to_answer(512) = 4000 ==== together signature 76-88 PRICE_CACHED_I |
| 12 | Bash | Compute whether the 4,000-token estimate mismatch can ever flip a budget decision, and actual per-call costs from the ledger | simorgh/cognition/budget.py:86: def estimate_cost(self, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> float: simorgh/cognition/budget. |
| 13 | Bash | Break ledger per-call max cost down by provider and date the ledger window; read the session think-error path | window: 2026-09-09 21:27:39.463947 -> 2026-09-18 17:13:42.350340 max cost per call by (provider,purpose): {'claude_code_cli/chat': 0.4117, 'claude_code_cli/cons |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** Every factual number in the finding checks out against the code and the ledger, but the architectural conclusion and the recommendation do not survive scrutiny at this system's scale.

Confirmed: the ledger's cognition:calls stream (2026-09-09 21:27 to 2026-09-18 17:13) holds 9,379 think.completed events, 0 with floor=true; purposes are chat 4,651 / draft 2,443 / review 2,101 / consolidate 182 / plan 1 / decompose 1. `simorgh/cognition/service.py:282` builds the per-request Budget with `require_real=payload.get("require_real_provider", False)` and never reads `budget_cfg.require_real`, so `config.py:24-30`'s require_real values (and any set via `[cognition.purposes]`, which `config.py` loads with `Budget(**v)`) are dead -- a genuine unconnected wire. `together.py:85` defaults `reasoning_effort=DEFAULT_REASONING_EFFORT="low"`, `service.py:165` only overrides it when configured, the live `~/.simorgh/simorgh.toml` does not, so `python -c` confirms `_room_to_answer(1000) == 4000` on the primary provider while `router.py:150` estimates with the configured `budget.max_tokens_out`.

Where the finding overreaches:
1. The estimate/actual mismatch cannot change any decision. Worst-case pre-call estimate for chat with 4,000 output tokens is $0.0038 against a $0.05 `max_cost_usd`; for every purpose the 'flips?' test is False, and Together's largest real per-call cost in the ledger is $0.0059. It is a cosmetic inconsistency, not a budget hole. The real cap breaches (325 calls over the purpose cap, up to $0.74/call) all come from claude_code_cli, which `budget.py:92-95` deliberately prices at 0 pre-call -- a different finding the reader did not make.
2. The '41 sites in 18 files' count is inflated: my grep gives 17 files / 36 sites, and several are unrelated meanings of the word (`ledger/backends/jsonl.py:241 floor=known.head`; `learning/service.py:173,179` and `contracts/messages/learn.py:18` use 'floor' as a learn outcome for a pipeline cap; `httpapi.py:1130-1144` marks 'no response in time'). Only ~7 sites read `floor` off a cognition think reply (memory/consolidation:150, planning/bridge:48, verification/service:292-293, curiosity/service:597, contracts/tidy:203, session.py:928/1212/1543, reflection via critique).
3. Deleting FloorProvider would not remove the special-casing. `orchestration/session.py:919-921` already emits `Outcome("completed", result_summary="", floor=True)` for a chat turn when think_reply is None -- i.e. on the *error* path, with no FloorProvider involved. The `floor` flag on `task.result`/Outcome (contracts/messages/task.py:102,108, worker.py:471,538, benchmark/runner.py:500) stays regardless, and the think-reply sites already check `ok`/`error` alongside `floor`, so the change saves one `and not floor` clause each.
4. 'Make every purpose require_real' breaks `_summarize_for_compaction` (service.py:410-421), which relies on the floor precisely so a compaction pass never raises; that would need a new try/except -- more work than it removes.
5. 'Collapse the purposes table to four' is pointless: reground is wired (session.py:1533, triggered on context_too_large), plan/decompose are wired and were called; unused dict entries cost nothing. 'Largely fiction' is overstated -- they are rarely-hit, not fake.
6. The Guardian cascade is real but historical and already mitigated: `guardian/service.py:330-332` records the incident and `guardian/config.py:100` defaults `health_critical_tightens_to="guarded"`, not locked. Ollama (`only_purposes=["chat"]`, service.py:189-200) sits before the floor and absorbed 1,360 chat calls; the floor is reachable only for non-chat purposes with three cloud providers all down, which did not happen in nine days.

Net: the floor provider is an idle ~50-line class plus one router branch, not a tax every subsystem pays; the dead `require_real` field is a small genuine bug; the token mismatch is harmless at current prices. This is a (c) minor bug plus a (b) cosmetic inconsistency, not an (a) over-built design.

### evidence

- ledger cognition:calls (python count): total 9379, floor 0; providers together 6983 / ollama 1360 / claude_code_cli 1034 / gemini 2; purposes chat 4651, draft 2443, review 2101, consolidate 182, plan 1, decompose 1; window 2026-09-09 21:27 -> 2026-09-18 17:13
- grep -rln '"floor"\|floor=' simorgh --include='*.py' | grep -v cognition | wc -l -> 17 files; site count 36 (not 18/41); unrelated hits: simorgh/ledger/backends/jsonl.py:241 `floor=known.head`, simorgh/learning/service.py:173,179 outcome 'floor' (pipeline cap), simorgh/interface/httpapi.py:1130,1144 'no response in time'
- simorgh/cognition/service.py:282 `require_real=payload.get("require_real_provider", False)`; simorgh/cognition/config.py:24-30 set require_real on plan/review/reground/ensemble; grep 'require_real' shows no reader of budget_cfg.require_real -> dead config field (confirmed)
- python -c: TogetherProvider(api_key='')._reasoning_effort == 'low'; _room_to_answer(1000) == 4000, _room_to_answer(512) == 4000 (simorgh/cognition/providers/together.py:51,85,228-233); simorgh/cognition/service.py:165 passes reasoning_effort only when configured; ~/.simorgh/simorgh.toml [cognition.providers] configures only ollama
- simorgh/cognition/router.py:150 `est_cost = provider_budget.estimate_cost(prompt_tokens, budget.max_tokens_out)`; arithmetic at PRICE_IN 0.15 / PRICE_OUT 0.50 per 1M: chat worst-case estimate $0.0023 (cfg) vs $0.0038 (4000 out) against cap $0.05 -- 'flips? False' for all nine purposes; ledger max Together cost per call: chat $0.0030, draft $0.0059, review $0.0022
- ledger: calls whose real cost exceeded the purpose max_cost_usd: claude_code_cli/chat 206, /review 104, /draft 11, /consolidate 4 (max $0.7362 per call); simorgh/cognition/budget.py:92-95 prices unknown-cost providers at 0.0 pre-call
- simorgh/orchestration/session.py:919-921: `if think_reply is None: if session.profile.name == "chat": return Outcome("completed", result_summary="", floor=True)` -- the floor flag is produced on the error path without FloorProvider
- simorgh/cognition/service.py:410-421 `_summarize_for_compaction` docstring: 'if every provider is down, the floor's fixed template still returns something, which is safer than raising out of a compaction pass'
- simorgh/orchestration/session.py:1533 `"purpose": "reground"` -- the reground purpose is wired; simorgh/cognition/service.py:189-200 places ollama before floor in the order
- simorgh/guardian/service.py:330-332 comment confirms the historical floor-pinned lockdown; simorgh/guardian/config.py:100 `health_critical_tightens_to: str = "guarded"` -- already mitigated
- simorgh/cognition/providers/base.py:30-48 FloorProvider is ~20 lines plus a TEMPLATES dict; router.py:268 is its single call site

**severity adjustment:** lower

**corrected claim:** The purpose table's `require_real` field is dead: `cognition/service.py:282` takes require_real only from the request payload, so `config.py:24-30`'s per-purpose values (and any set in `[cognition.purposes]`) are never consulted -- one more unconnected wire, but small, since callers set `require_real_provider` explicitly and verification carries its own `review_require_real_provider`. The Together provider's default `reasoning_effort="low"` raises every call's max_tokens to 4,000 while the router's pre-call estimate uses the configured 512-1,000; at current prices this can never flip a per-call budget decision (worst-case estimate $0.0038 vs a $0.05 cap), so it is a cosmetic inconsistency -- the real purpose-cap breaches are 325 unpriced claude_code_cli calls, up to $0.74 each. The FloorProvider itself is an idle ~50-line last resort (0 of 9,379 calls in nine days, Ollama sits in front of it for chat) and the `floor` flag on task outcomes is produced on the error path too (session.py:921), so deleting the provider would not remove the downstream checks and would require new error handling in compaction; the nine-purpose table costs nothing and five of its entries are wired code paths that are rarely hit, not fiction.

