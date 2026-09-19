# refute:proportionality:No stable prompt prefix and no prompt ca

*Workflow: review · Phase: Refute · Agent id: `a3d4ff5eb39a15e1a` · Tool calls: 11*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "agent-loop-orchestration". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "No stable prompt prefix and no prompt caching: the clock-to-the-minute is the first line of the system prompt",
    "kind": "right-design-undermined",
    "severity": "high",
    "claim": "task_rules is a protected block placed in the system message, and scaffolds.render puts 'Right now it is <weekday> <date>, HH:MM.' ahead of everything in it, so the system prompt changes every minute; the budget hint changes every step; persona/self/user_profile blocks are re-fetched per call; and no provider sends any cache directive, so every step re-pays the full ~6k-token prefix.",
    "evidence": [
      "simorgh/orchestration/scaffolds.py:638 `return f\"Right now it is {when:%A %-d %B %Y}, {when:%H:%M}.\"`; :690-692 `stamp = when_line(now)` ... `body = f\"{stamp}\\n\\n{body}\"` ('Ahead of everything, including the task')",
      "Measured: `first line of CHAT task_rules: 'Right now it is Friday 18 September 2026, 18:47.'`",
      "simorgh/cognition/assembler.py:56-88: constitution, voice, self_summary, user_profile, task_rules, conversation, then budget_hint 'You have {steps_left} tool call(s) left' as protected",
      "grep -rn 'cache_control|prompt_cach|cache_read|cache_creation' simorgh/cognition/ -> no matches (together.py:_to_response only reads cached tokens back if the provider happens to return them)",
      "Measured system-prompt size per THINK (scaffolds.render + _tool_instruction_block): CHAT/cli tools=72 ~5,778 tokens; VOICE_CHAT tools=58 ~5,841 tokens; PATCH tools=25 ~2,841 tokens; plus constitution/voice/self summary (~300) /user profile"
    ],
    "why_it_matters": "On a 20-step chat or patch session the same ~6k tokens are re-sent uncached 20 times; with Together's cached-token pricing and Anthropic's cache_control this is the single largest avoidable cost and latency term in the loop, and the timestamp guarantees a miss even if caching were enabled.",
    "recommendation": "Order the system prompt static-to-dynamic (constitution, persona, tool schemas/notes, scaffold body, then task, then memory), move the date to day granularity and the time into the user turn, keep budget/last-step hints in the user turn, and enable provider caching (cache_control on the static system block for Anthropic; Together caches automatically on a stable prefix). Fetch persona.voice/self.summary once per session, not per THINK.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read the cited scaffolds and assembler code |  wrong, because the prose had never been told. Local time, because the family lives in one. An absent clock yields "" rather than a wrong date -- saying nothing |
| 2 | Bash | Trace render callers, caching directives and system-role placement | simorgh/orchestration/api.py:97: # was handed the path to (see `scaffolds.render`). simorgh/orchestration/progress.py:111: return [{"role": "user", "content": f |
| 3 | Bash | Read render call site, system-message placement and provider caching |  "purpose": "chat" if is_chat else "draft", "messages": messages, "tools": list(offered), # `Profile.scaffold` reached `assemble()` and was dropped; # Cognition |
| 4 | Bash | Read config, provider pricing/caching and tool-instruction placement | [voice] barge_in = false keep_audio = true vad_sensitivity = "high" barge_in_calibrate_ms = 1200 barge_in_speech_ms = 350 barge_in_ratio = 2.8 min_confidence =  |
| 5 | Bash | Inspect state directory, ledger layout, and prefix block sources | total 3808 drwxr-xr-x@ 26 saeed staff 832 Sep 18 15:04 . drwxr-x---+ 100 saeed staff 3200 Sep 18 18:46 .. drwxr-xr-x@ 2 saeed staff 64 Sep 9 21:27 benchmark drw |
| 6 | Bash | List ledger streams, provider order and constitution prefix size | total 1425296 drwxr-xr-x@ 65535 saeed staff 3782944 Sep 18 17:14 . drwxr-xr-x@ 9 saeed staff 288 Sep 18 17:14 .. -rw-r--r-- 1 saeed staff 839 Sep 14 05:40 actio |
| 7 | Bash | Find the cognition/budget ledger streams | benchmark%3Aruns.jsonl capabilities.jsonl cognition%3Abudget%3Aclaude_code_cli.jsonl cognition%3Abudget%3Agemini.jsonl cognition%3Abudget%3Aollama.jsonl cogniti |
| 8 | Bash | Inspect Together budget stream shape | ens":7126,"output_tokens":95},"seq":6985,"stream":"cognition:budget:together","trace_id":"","ts":1789766252.099115,"type":"spend.recorded"} {"causation_id":null |
| 9 | Bash | Compute Together spend per day and check whether cached tokens were ever observed | together lifetime: calls 6991 cost $4.56 input tokens 24374065 avg in/call 3486 2026-09-09 calls 266 cost $0.248 in_tok 1203283 2026-09-10 calls 1374 cost $0.73 |
| 10 | Bash | Check whether Together ever billed cached tokens and compute maximum possible saving | together calls billed at full input rate (cached=0): 5627 calls billed below full (cached>0): 1364 theoretical max saving if 100% of input were cached over 10 d |
| 11 | Bash | Determine whether Together actually served cached tokens and how many | cost ABOVE uncached arithmetic (=> cached tokens billed at 0.03): 1364 BELOW: 0 implied cached tokens per such call: median 5632 max 26688 total 9671616 by day  |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The mechanism is real and I verified it in code: scaffolds.py:690-692 prepends `when_line(now)` (minute-granular, :638) to the task_rules body, ahead of the task and the ~5k tokens of per-tool notes; session.py:1243-1250 passes `now=_epoch(self._clock)` on every THINK; assembler.py:56-68 makes task_rules a protected block; service.py:331-333 sends all protected blocks as one `role: system` message; no provider sends a cache directive (grep confirms). But three things the finding gets wrong or overstates, and one lens issue, keep it from being a high-severity architectural problem at this scale. (1) The title is inaccurate: the stamp is the first line of task_rules, not of the system prompt -- constitution (32 estimated tokens), persona voice, self_summary (<=300) and user_profile precede it. That prefix is small, so the practical effect is close to what was claimed, but 'first line of the system prompt' is not what the code does. (2) 'every step re-pays the full prefix' and 'no provider ... only reads cached tokens back if the provider happens to return them' is contradicted by the ledger: Together's automatic prefix caching IS firing today. Recomputing each spend row against the uncached price shows 1,364 of 6,991 Together calls (19.5%) were billed with cached tokens at $0.03/1M (median ~5.6k cached tokens per such call, ~9.7M cached vs 24.4M uncached input tokens lifetime, i.e. ~28% of all input tokens already hit the cache). Steps within the same minute share a stamp and hit; only minute boundaries miss. Sim already reads and bills cached tokens (together.py:188-224, budget.py:100-104). (3) Scale: lifetime Together spend is $4.56 over 10 days (avg $0.45/day, peak day $1.33). If 100% of the 24.4M uncached input tokens had been cached the saving would be $2.92 over ten days; a realistic 80% is ~$0.23/day. 'Single largest avoidable cost' may be literally true but the absolute number is trivial for one laptop and one family, and prefill latency for a ~7k-token prompt on a Flash-class model is sub-second next to MIN_REASONING_MAX_TOKENS=4000 of output. The one place it could matter more is the Claude Code CLI failover (1,034 calls, $99.32 nominal via the CLI's own total_cost_usd, ~$0.10/call, where `--system-prompt` is a full replacement so the CLI's usual system-prompt cache is entirely Sim's changing text) -- but that provider bills a flat subscription (claude_code.py:13-18), so this costs rate-limit headroom, not dollars. (4) The recommendation is partly wrong for this codebase: moving the time into the user turn puts it back in the elastic conversation, which is exactly the live-caught bug the code documents (scaffolds.py:683-686: a date pushed out by a long tool result was re-invented by the model). Re-fetching persona.voice/self.summary per THINK is an in-process bus request, not a paid call, and restructuring that is more work than it saves. The proportionate fix is a two-line move: place `stamp` at the END of the task_rules body (after the tool notes) instead of the head at scaffolds.py:691-692, optionally day-granular; the assembler already puts budget_hint last. Classification: (b) right design (protected, never-compacted facts) with a small ordering mistake in the implementation, not an architectural error; severity should be lowered from high to low.

### evidence

- simorgh/orchestration/scaffolds.py:638 `return f"Right now it is {when:%A %-d %B %Y}, {when:%H:%M}."` -- minute-granular stamp (verified).
- simorgh/orchestration/scaffolds.py:690-692 `stamp = when_line(now)` / `body = f"{stamp}\n\n{body}"` prepends it ahead of the task and the tool-note lines built at :696+ (verified); :683-686 comment documents WHY it lives in the protected block: 'a date that a long tool result can push out of the prompt is a date Sim will invent again'.
- simorgh/orchestration/session.py:1243-1250 `scaffolds.render(... now=_epoch(self._clock))` is called on every THINK request (verified).
- simorgh/cognition/assembler.py:56-68: order is constitution (protected), voice, self_summary, user_profile, THEN task_rules -- so the stamp is not the first line of the system prompt; `python3 -c` estimate_tokens(CONSTITUTION_SUMMARY) == 32, so the stable prefix before the stamp is small.
- simorgh/cognition/service.py:331-338: protected blocks joined into one `{"role": "system"}` message, tool instructions a second system message, compacted conversation a single user message (verified).
- grep -rn 'cache_control|prompt_cach|cache_read|cache_creation' simorgh/cognition/ -> no directive sent by any provider (verified); simorgh/cognition/providers/together.py:188-224 reads `cached_tokens` back and bills at PRICE_CACHED_IN=0.03 (together.py:76).
- Ledger ~/.simorgh/ledger/streams/cognition%3Abudget%3Atogether.jsonl, 6,991 spend.recorded rows: lifetime cost $4.56, 24,374,065 uncached input tokens, avg 3,486 in/call; per day: 09-09 $0.25, 09-10 $0.74, 09-11 $1.33 (peak, 2,128 calls), 09-12 $0.28, 09-13 $0.76, 09-14 $0.12, 09-15 $0.28, 09-16 $0.53, 09-17 $0.27, 09-18 $0.01.
- Recomputed cost_usd vs input*0.15+output*0.5 per row: 1,364 calls billed ABOVE the uncached arithmetic (cached tokens at $0.03), 0 below -> Together prefix caching already hits on ~19.5% of calls, median ~5,632 cached tokens per hit, ~9.67M cached tokens lifetime (~28% of all input). 'Every step re-pays the full prefix' is false within a minute.
- Theoretical maximum saving if 100% of the 24.4M uncached input tokens had been cached: 24.4M/1M x (0.15-0.03) = $2.92 over ten days.
- ~/.simorgh/ledger/streams/cognition%3Abudget%3Aclaude_code_cli.jsonl: 1,034 calls, $99.32 nominal (CLI total_cost_usd); simorgh/cognition/providers/claude_code.py:13-18 and :94-97: bills the subscription, `--system-prompt` is a full replacement.
- simorgh/cognition/config.py:73 `provider_order = ("together", "claude_code_cli", "gemini", "floor")`; ~/.simorgh/simorgh.toml only configures ollama (`only_purposes = ["chat"]`), so Together/GLM-5.3-Flash (together.py:49) is the paid primary.
- cognition:calls stream (9,379 rows) payload keys: compaction, cost_usd, floor, provider, purpose, tokens -- no cached field is recorded there, so the reader's grep could not have seen cache hits; the budget stream's cost arithmetic is the only trace, and it shows hits.

**severity adjustment:** lower

**corrected claim:** The minute-granular clock line is prepended to the task_rules block (scaffolds.py:690-692), which sits after four small protected blocks (constitution ~32 tokens, voice, self summary, user profile) and ahead of the ~5k tokens of tool notes, so Together's automatic prefix cache is invalidated at every minute boundary; no provider sends an explicit cache directive. However, caching is not absent: the ledger shows Together already served cached tokens on 1,364 of 6,991 calls (~28% of all input tokens, steps within the same minute), and Sim already bills them at the cached rate. At this system's scale the whole Together bill is $4.56 over ten days (~$0.45/day), so the maximum possible saving is under $3 over that period (~$0.25/day realistic); the Claude CLI failover is subscription-billed, so its ~$0.10/call nominal cost is rate-limit headroom, not money. This is a small implementation ordering slip in an otherwise sound protected-block design, fixed by moving the stamp to the end of the task_rules body (optionally day-granular), not by moving the time into the compactable user turn (which reintroduces the live-caught 'invented date' bug documented at scaffolds.py:683-686) or by restructuring per-THINK persona/self fetches, which are free in-process bus requests.

