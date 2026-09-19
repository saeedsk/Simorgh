# refute:correctness:No stable prompt prefix and no prompt ca

*Workflow: review · Phase: Refute · Agent id: `a5f866fd9c161902c` · Tool calls: 6*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "agent-loop-orchestration". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Read the cited scaffold and assembler lines |  wrong, because the prose had never been told. Local time, because the family lives in one. An absent clock yields "" rather than a wrong date -- saying nothing |
| 2 | Bash | Grep for cache directives, now= plumbing, and assemble callers | == cache grep whole repo == (eval):1: no matches found: --include=*.py == now= passed to render == simorgh/orchestration/scaffolds.py:641:def render(profile: Pr |
| 3 | Bash | Grep cache directives, assemble callers, and system/user block rendering | == cache grep whole repo == simorgh/cognition/providers/together.py:188: cached = self._cached_tokens(usage) simorgh/cognition/providers/together.py:236: def _c |
| 4 | Bash | Read THINK message assembly and provider request builders |  if self._paused: await self._error_reply(message, "paused", "cognition is paused", retryable=True) return try: assembled = await self._assembler.assemble( purp |
| 5 | Bash | Read CLI provider system handling, Together message build, self-summary source |  self._runner: Runner = runner or subprocess.run def available(self) -> bool: return shutil.which(self._binary) is not None async def complete( self, messages:  |
| 6 | Bash | Render task_rules for chat/patch/voice profiles and locate the timestamp | chat \| first line: 'Right now it is Friday 18 September 2026, 19:04.' \| chars before stamp: 0 \| chars after stamp: 12991 \| ~tokens total: 3247 patch \| first lin |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core of the finding is true of the code today. simorgh/orchestration/scaffolds.py:638 returns "Right now it is {weekday} {date}, {HH:MM}." and :690-692 prefixes it to the task_rules body ahead of the task text and the whole per-tool notes table (the comment says 'Ahead of everything, including the task'); simorgh/orchestration/session.py:1243-1250 renders that with now=_epoch(self._clock) on every THINK; simorgh/cognition/assembler.py:52-68 re-requests PERSONA_VOICE, SELF_SUMMARY and (for chat) the user profile on every assemble(), and assemble() is called per THINK from cognition/service.py:290; service.py:296-333 joins every protected block (constitution, voice, self_summary, user_profile, task_rules, budget_hint/final_turn_hint) into a single role:system message; a repo-wide grep for cache_control|prompt_cach|cache_read|cache_creation|ephemeral finds nothing except together.py reading cached_tokens back from responses. Rendering the real profiles confirms the stamp is at char 0 of task_rules for chat, patch and voice, with ~5.5k-13k chars (~1.4k-3.2k tokens before the tool_instruction_block and skills catalog) following it. So a minute-granularity string sits ahead of the bulk of the prefix and defeats any prefix cache. Three parts of the claim are inaccurate or overstated: (1) the title's 'first line of the system prompt' is wrong -- constitution (~31 tokens), voice, self_summary and user_profile precede task_rules in the system message; the stamp is the first line of the task_rules block, so a few hundred tokens ahead of it are in principle cacheable while the thousands after it are not. (2) 'the budget hint changes every step' is only true inside the winding-down window (assembler.py:81 `steps_left <= _WINDING_DOWN_STEPS`); otherwise no budget block is emitted. (3) The recommendation 'cache_control on the static system block for Anthropic' has no target: simorgh/cognition/providers/ contains only claude_code.py (spawns the `claude` CLI per call with --system-prompt, :92-96), gemini.py, ollama.py and together.py -- there is no Anthropic Messages API client, so Simorgh cannot set cache_control; the actionable fix is stabilising the prefix (which is entirely under Simorgh's control) and, if desired, Gemini context caching. The finding is not in the known list (nothing there concerns prompt ordering or caching). On severity: the design defect is genuine and cheap to fix, but at this system's scale (one laptop, one family, ~1.4k-6k tokens per step, Together pricing in cents per million) the dollar and prefill-latency impact per session is modest, so 'high' overstates it; medium fits.

**corrected claim:** The per-minute timestamp is the first line of the protected task_rules block (not of the whole system message; constitution, persona voice, self summary and user profile precede it), and that block plus the tool notes that follow it -- the bulk of the ~1.4k-6k-token system prompt -- is regenerated on every THINK, with persona voice / self summary / user profile re-requested over the bus each call. No provider in simorgh/cognition/providers/ sends a cache directive, and there is no Anthropic API provider to send cache_control through (the Claude route is a fresh `claude` CLI subprocess per call with --system-prompt); the budget hint appears only in the winding-down window, not every step. The fix is to order the system prompt static-to-dynamic, move the clock to day granularity in the system block and the minute into the user turn, and fetch persona/self/user-profile once per session, so that Together's server-side prefix caching (and the CLI's own) can hit.

### evidence

- simorgh/orchestration/scaffolds.py:638 `return f"Right now it is {when:%A %-d %B %Y}, {when:%H:%M}."`
- simorgh/orchestration/scaffolds.py:686-692 comment 'Ahead of everything, including the task' then `stamp = when_line(now)` / `body = f"{stamp}\n\n{body}"`
- simorgh/orchestration/session.py:1243-1250 `"task_rules": scaffolds.render(session.profile, ... now=_epoch(self._clock))` built inside the per-turn COGNITION_THINK request
- simorgh/cognition/assembler.py:52-68 blocks order: constitution, voice (PERSONA_VOICE request), self_summary (SELF_SUMMARY request), user_profile (WORLD_ENV_QUERY), task_rules -- all requested inside assemble()
- simorgh/cognition/assembler.py:81 `elif steps_left is not None and steps_left <= _WINDING_DOWN_STEPS:` -- budget_hint only in the winding-down window
- simorgh/cognition/service.py:290-296 assemble() called per THINK; :330-338 all protected blocks joined into one `{"role": "system"}` message
- Command: `grep -rniE 'cache_control|prompt_cach|cached_tokens|cache_read|cache_creation|ephemeral' simorgh/` -> only together.py:188-244 (_cached_tokens reads usage back) and an unrelated 'ephemeral' in worker.py:392
- Command: `ls simorgh/cognition/providers/` -> base.py claude_code.py gemini.py ollama.py together.py (no Anthropic API provider)
- simorgh/cognition/providers/claude_code.py:92-96 `argv += ["--system-prompt", system_prompt]` -- fresh CLI subprocess per call
- simorgh/cognition/providers/together.py:127-131 body = {model, messages:[...]} with no cache field
- Command (python3 -c rendering real profiles with now=time.time()): chat | first line: 'Right now it is Friday 18 September 2026, 19:04.' | chars before stamp: 0 | chars after stamp: 12991 | ~tokens 3247; patch | chars after stamp: 5483 | ~tokens 1370; voice | chars after stamp: 10522 | ~tokens 2630; CONSTITUTION_SUMMARY ~31 tokens precedes task_rules

**severity adjustment:** lower

