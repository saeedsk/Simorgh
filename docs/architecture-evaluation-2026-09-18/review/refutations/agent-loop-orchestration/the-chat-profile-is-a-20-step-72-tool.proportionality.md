# refute:proportionality:The chat profile is a 20-step, 72-tool,

*Workflow: review · Phase: Refute · Agent id: `ae645ddf4ac78f455` · Tool calls: 12*

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
    "title": "The chat profile is a 20-step, 72-tool, 16k-output task without task semantics, on a 12k-token input budget",
    "kind": "wrong-design",
    "severity": "high",
    "claim": "A typed chat turn is given the same step budget and output budget as a patch task and more tools than any task profile, yet it has no verification, no worktree, no resume and a synchronous 420s wait, while its Cognition input budget is 12,000 tokens of which ~5.8k are the fixed prompt, leaving roughly 5k for memory plus a transcript whose tool results can each be ~2k tokens.",
    "evidence": [
      "simorgh/orchestration/profiles.py:77 `read_only=False, max_steps=20, max_revisions=0, scaffold=\"chat\", verify=False,` and :90 `max_output_tokens=16_000` (comment: 'Matched to the patch profile, which is what a chat turn now IS')",
      "Measured: `CHAT/cli tools= 72 task_rules= 13013 chars ~3254 tok | tool_instructions= 10095 chars ~2524 tok | total ~5778 tok`",
      "simorgh/cognition/config.py:22 `\"chat\": Budget(12_000, 1_000, 0.05, max_seconds=90.0)`; cognition/service.py:307 elastic_limit = max_tokens_in - protected_tokens; context.py:31 memory block up to 4,000 chars",
      "simorgh/interface/config.py:88 `chat_reply_timeout_s: float = 420.0`; interface/service.py:917-1000 blocks the REPL on the future",
      "scaffolds.py _CHAT already says 'Judge the SIZE first ... anything that will take many edits ... goes to start_task', and tools.py:_MARKER_ARG_HINT['start_task'] says the same; the profile numbers contradict the instruction",
      "~/.simorgh/simorgh.toml: [cognition.providers.ollama] only_purposes=['chat'], num_ctx=8192 -- the chat fallback model's context is smaller than the chat purpose's own input budget"
    ],
    "why_it_matters": "The two modes converge into one that is bad at both: a chat turn that reads two files is already being snipped by compaction, a 20-step chat can outlive the REPL's wait, and a build started 'in chat' gets none of the worktree/verify/resume protections. The design already contains the right split (start_task hands builds to a task with a worktree); the profile undoes it.",
    "recommendation": "CHAT: 6-8 steps, ~15-20 tools (read-only + house/TV/camera acts + remind + start_task/list_tasks/cancel_task), output ~2-4k tokens, writes limited to workspace/; every source edit and every multi-file build goes through start_task. Raise the chat purpose input budget to what the primary model actually supports (and set Ollama num_ctx to match or drop it from chat), and cut the tool-notes block once native tool schemas carry the descriptions.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read the profiles module | """Per-kind Profiles (16 section 5). v1 kept its own per-agent step ceilings (`DEFAULT_MAX_TOOL_STEPS` in `self_patch.py`/`research_task.py`); these are the sam |
| 2 | Bash | Inspect profiles, budgets, context, and REPL wait | CHAT 72 20 16000 False False PATCH 25 20 16000 True False RESEARCH 31 14 2000 True False --- """Cognition configuration (docs/blueprint/subsystems/04-cognition. |
| 3 | Bash | Read the live config for cognition, ollama, interface | === toml cognition === 22:[cognition] 23- 24:[cognition.providers] 25- 26:[cognition.providers.ollama] 27-model = "qwen3:4b-instruct" 28-only_purposes = ["chat" |
| 4 | Bash | Trace chat run path, transcript bounding, scaffold and hint text | === who calls cognition with purpose chat / req_budget === simorgh/orchestration/session.py:1235: "purpose": "chat" if is_chat else "draft", simorgh/cognition/s |
| 5 | Bash | Check session purpose, worktree kinds, result bounds, REPL caller, prompt builders | === session.py 1215-1250 === if not text or reply.payload.get("tool_calls") or _marker_shaped(text): return "" # a marker on its own line is a tool request, not |
| 6 | Bash | Measure CHAT prompt size, check worktree kinds, provider, write scopes, budget history | === WORKTREE_KINDS === 59:WORKTREE_KINDS = frozenset({"patch", "skill"}) 60-CANCELLED_REASON = "the task was cancelled" 61- 62-# `workspace/` is the one directo |
| 7 | Bash | Locate think class, tool-notes builder, chat write scope, GLM context notes | === class with _think === 488:class _EventWaiter: 603:class SessionRunner: 1219: async def _think(self, session: Session, user_text: str, *, last_step: bool, no |
| 8 | Bash | Measure prompt tokens, list protected blocks, check chat write confinement and resume | === measure prompt === offered 72 \| task_rules 12991 chars ~ 3247 tok \| tool_instructions 10095 chars ~ 2523 tok \| total ~ 5771 tok PATCH offered 25 task_rules  |
| 9 | Bash | Check budget accounting, Guardian path rules, context doc, start_task registration, prior reviews | === service.py 300-345 === return # The compactor sees the caller's *raw* messages (role, name, # load_bearing intact) -- not the assembler's already-flattened  |
| 10 | Bash | Check start_task registration, patch path policy, protected blocks, GLM context, audit overlap, ledger | Exit code 1 === start_task registered where === simorgh/interface/live_status.py simorgh/contracts/toolargs.py simorgh/execution/tools.py simorgh/orchestration/ |
| 11 | Bash | Check ledger streams for chat compaction, and whether chat patches land on live checkout | === ledger streams === trace%3A4ac9ccd3-3db5-4579-b715-e18b9c9b1c6c.jsonl system.jsonl trace%3Abffae277-2f6a-44c6-b68d-5502f9ed7a36.jsonl trace%3A1091ef2d-c5af- |
| 12 | Bash | Scan newest ledger streams for context errors and chat token counts | streams: 118215 newest 40 traces with context_too_large: 0 newest 40 traces with snip/compaction events: 1 system.jsonl context_too_large: 0 system.jsonl chat p |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** Every number in the claim checks out against the code and the live config: CHAT offers 72 tools, max_steps=20, max_output_tokens=16_000, verify=False, no worktree (WORKTREE_KINDS = {patch, skill}), no resume (the scaffold itself says so), a 420s synchronous wait, a 12k-token chat input budget with no toml override, and the Ollama chat fallback at num_ctx=8192. I reproduced the prompt measurement exactly (task_rules ~3,247 tok + tool notes ~2,523 tok = ~5,771 tok; PATCH's rules are ~1,393 tok for comparison). The primary model has a 1M context per the project's own design doc, so the 12k budget is an unexamined Phase-1A default, not a fit to anything.

However, three things pull it down from a clean 'confirmed' at 'high'. (1) Two of its six legs are already reported in docs/architecture-third-opinion-2026-09-18.md: the 72-tool chat surface (lines 22, 160, 212, 222) and the 420s REPL block (line 144). (2) The 'already being snipped by compaction' consequence is arithmetic, not observed: the newest 40 trace streams contain zero context_too_large and one compaction event, and system.jsonl has none. (3) The mechanism is slightly wrong: cognition/service.py:334-338 appends tool_instructions OUTSIDE the budget check ('not counted ... a short fixed-shape string'), so the elastic room is ~12k minus task_rules minus constitution/voice/self_summary/user_profile, not 12k minus 5.8k; the uncounted ~2.5k tool-notes block is a small genuine bug (its comment is false for CHAT) and it makes the Ollama 8192 overflow worse, not better.

On the skeptic lens: the 20-step/16k numbers are not accidental, they are each a fix for a live-caught failure (12 steps failed 'build me a game' three times; 2,000 output tokens shredded a 147-line file to 54). The recommendation's 6-8 steps and 2-4k output would reinstate both failures unless start_task becomes the reliable build path first, so as written it is disproportionate for one developer. But the core design point survives and is materially strengthened by one thing the finding did not cite: because chat has no worktree, tool_root() (execution/tools.py:120-123) resolves a chat turn's apply_source_patch to config.repo_root, i.e. the LIVE checkout that sim.sh boots from, guarded only by ProtectedRule's prefix list. That is a design that is right (worktree isolation exists) undermined by the profile.

Net: wrong-design with a partly already-known surface and an overreaching recommendation; the cheap, high-value fixes are the input budget (12k vs 1M) and the uncounted tool-notes block, plus routing source edits out of chat.

### evidence

- simorgh/orchestration/profiles.py:77 `read_only=False, max_steps=20, max_revisions=0, scaffold="chat", verify=False,` and :90 `max_output_tokens=16_000`; comments at :70-76 and :79-89 record that 12 steps and 2,000 output tokens each failed live before being raised
- python -c import: `CHAT 72 20 16000 False False | PATCH 25 20 16000 True False | RESEARCH 31 14 2000 True False` (tools, max_steps, max_output_tokens, verify, read_only)
- Measured with scaffolds.render + _tool_instruction_block on CHAT: `offered 72 | task_rules 12991 chars ~3247 tok | tool_instructions 10095 chars ~2523 tok | total ~5771 tok`; PATCH task_rules ~1393 tok
- simorgh/cognition/config.py:22 `"chat": Budget(12_000, 1_000, 0.05, max_seconds=90.0)`; git log -L shows the 12_000 dates from commit 1f77116 (Phase 1A) and was never revisited except to add max_seconds
- ~/.simorgh/simorgh.toml:22-32: `[cognition]` has no purpose-budget override; `[cognition.providers.ollama] only_purposes = ["chat"]`, `num_ctx = 8192`
- docs/plans/long-run-context-design.md:216 `zai-org/GLM-5.3-Flash (today) ... 1M context`; simorgh/cognition/providers/together.py:49 `DEFAULT_MODEL = "zai-org/GLM-5.3-Flash"`; config.py:73 provider_order = ("together", "claude_code_cli", "gemini", "floor")
- simorgh/cognition/service.py:297-307 protected_tokens summed and elastic_limit = max_tokens_in - protected_tokens; :334-338 tool_instructions appended with comment 'Not counted in protected_tokens's budget check above -- a short fixed-shape string' -- for CHAT that string is ~2.5k tokens
- simorgh/orchestration/session.py:59 `WORKTREE_KINDS = frozenset({"patch", "skill"})`; :753-755 _uses_worktree returns False for any other kind
- simorgh/execution/tools.py:120-123 tool_root(): `root = getattr(ctx, "root", None) ...; if root is None or (path and is_scratch(path)): return config.repo_root` -- a chat turn's apply_source_patch on a non-workspace path edits the live checkout
- simorgh/orchestration/scaffolds.py:375-380 `Judge the SIZE first. A reply here gets one step budget and does not resume ... goes to start_task instead`; tools.py:369-373 start_task hint says the same
- simorgh/interface/config.py:88 `chat_reply_timeout_s: float = 420.0`; interface/service.py:720 `asyncio.run_coroutine_threadsafe(self._handle_line(line), self._loop).result()` and :974 `await asyncio.wait_for(fut, timeout=self.config.chat_reply_timeout_s)`
- Already known: docs/architecture-third-opinion-2026-09-18.md:22 'A tool surface of 72 tools per chat turn', :144 '_repl_main blocks synchronously for the entire turn duration (up to 420 seconds)', :222 'Reduce the CHAT tool surface from 72 to ~12-15'
- Ledger (118,215 streams): newest 40 trace streams -> `context_too_large: 0`, `snip/compaction events: 1`; system.jsonl -> `context_too_large: 0` -- the compaction squeeze is not observed in recent runs
- simorgh/cognition/config.py:114 `tool_result_max_tokens: int = 2_000`; session.py:1596 `_MODEL_RESULT_CHARS = 8000` -- per-result 2k-token bound confirmed

**severity adjustment:** lower

**corrected claim:** The CHAT profile has been deliberately grown into a patch-shaped profile (20 steps, 16k output, 72 tools, writes/install/run) in response to live-caught failures, but without any of the patch profile's protections: no verify, no worktree (WORKTREE_KINDS is patch/skill only, so a chat apply_source_patch to a source path lands on the live checkout via tool_root()), no resume, and a 420s blocking REPL wait. Its Cognition input budget is a never-revisited 12k default against a primary model with a 1M context, and the ~2.5k-token tool-notes block is sent uncounted on top of that budget (service.py:335's 'short fixed-shape string' comment is false for CHAT), which also means a chat prompt routinely exceeds the Ollama fallback's num_ctx=8192. The 72-tool surface and the 420s block are already reported in the third-opinion review; the compaction squeeze is arithmetic and not observed in the newest ledger traces. Proportionate fixes: raise the chat input budget to match the primary model (and drop Ollama from chat or match num_ctx), count tool_instructions in the budget or drop the notes once native tool schemas carry them, and route source-tree edits out of chat into start_task -- rather than cutting chat back to 6-8 steps / 2-4k output, which would reinstate the two live failures those numbers were raised to fix.

