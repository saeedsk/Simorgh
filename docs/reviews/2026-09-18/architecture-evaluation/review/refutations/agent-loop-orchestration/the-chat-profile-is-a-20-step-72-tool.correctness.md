# refute:correctness:The chat profile is a 20-step, 72-tool,

*Workflow: review · Phase: Refute · Agent id: `a1e105896802a4466` · Tool calls: 9*

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
| 1 | Bash | Read orchestration profiles | """Per-kind Profiles (16 section 5). v1 kept its own per-agent step ceilings (`DEFAULT_MAX_TOOL_STEPS` in `self_patch.py`/`research_task.py`); these are the sam |
| 2 | Bash | Read cognition budgets, context, interface timeout, and toml | --- cognition/config.py --- """Cognition configuration (docs/blueprint/subsystems/04-cognition.md section 3.5). Every field has a working default so `[cognition |
| 3 | Bash | Count chat tools and check budget overrides | --- tool count --- CHAT tools 72 steps 20 out 16000 verify False ro False PATCH tools 25 steps 20 out 16000 verify True --- toml [cognition] --- cast_device = " |
| 4 | Bash | Read REPL wait, scaffold size guidance, start_task hint | --- service.py 905-1010 --- split, "Seem" made "Sim" -- shown as `↳ read as:` when anything changed, so the person sees what was understood.""" if not self.conf |
| 5 | Bash | Check scaffold text, worktree/resume by kind, result caps, and prior reviews | --- scaffold 370-385 --- do is CHOOSE to file something away on demand: there is no remember tool, so a fact only survives if it is in the answer you give. If s |
| 6 | Bash | Find prompt block construction, result cap, worktree gate, and provider config | --- task_rules / tool_instructions construction --- 614: # Agent Skills: the catalog rides in `task_rules` and `use_skill` returns 1235: "purpose": "chat" if is |
| 7 | Bash | Read the think request construction and protected-block assembly | --- session.py 1225-1270 --- and session.profile.scaffold in ("patch", "research") and "delegate" not in offered): offered = tuple(offered) + ("delegate",) cata |
| 8 | Bash | Reproduce the measured prompt sizes for the chat profile | tools 72 task_rules chars 12941 tok 3236 tool_instructions chars 10095 tok 2524 sum tok 5760 start_task hint: first line: what the task should achieve, in a sen |
| 9 | Bash | Check prior reviews' coverage, Ollama context handling, assembler blocks, and chat continuation | --- review html 126-146 --- "The 65+ tool monolith" — the CHAT profile has 34 tools The central number in its cognitive-overload argument is roughly double the  |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core of the claim is true of the code today and I reproduced its measurement. simorgh/orchestration/profiles.py:77 sets CHAT to `read_only=False, max_steps=20, max_revisions=0, scaffold="chat", verify=False` and :90 `max_output_tokens=16_000`; `python -c` on the live module gives CHAT 72 tools vs PATCH 25 (both 20 steps, 16k out; PATCH verify=True). Chat gets no worktree: session.py:59 `WORKTREE_KINDS = frozenset({"patch","skill"})` and `_uses_worktree` (:753-754) refuses every other kind. Chat does not resume: the scaffold itself says so (scaffolds.py:375-376 "A reply here gets one step budget and does not resume") and `_continues` (session.py:827-837) only applies to Planning-re-offered tasks. The REPL wait is real: interface/config.py:88 `chat_reply_timeout_s: float = 420.0`, service.py:976 `await asyncio.wait_for(fut, timeout=...)`; the comment three lines above it (:85) still says "a chat turn is up to max_steps=6", which is stale drift supporting the reader's point. Budget: cognition/config.py:22 `"chat": Budget(12_000, 1_000, 0.05, max_seconds=90.0)`, ~/.simorgh/simorgh.toml has an empty `[cognition]` so the default applies; service.py:307 `elastic_limit = budget.max_tokens_in - protected_tokens`; assembler.py:68 puts task_rules in the protected set; compaction cap `tool_result_max_tokens: int = 2_000` (cognition/config.py:114) and session.py:1597 `_MODEL_RESULT_CHARS = 8000` (~2k tok) confirm the per-result size. Ollama fallback: toml lines 26-30 `only_purposes = ["chat"]`, `num_ctx = 8192`, and providers/ollama.py:138 passes it as `options={"num_ctx": ...}` — so the chat fallback's window is below the chat purpose's own 12k input budget. Reproduced measurement: task_rules 12,941 chars / 3,236 tok, tool_instructions 10,095 chars / 2,524 tok, total 5,760 tok (reader said 13,013 / 5,778 — same within noise).

Where the claim overstates: the "leaving roughly 5k for memory plus transcript" arithmetic double-deducts. service.py:325-327 explicitly does NOT count the tool_instructions block in `protected_tokens`, so the elastic room actually enforced is 12,000 minus (constitution 32 + voice + self_summary <=300 + user_profile + task_rules 3,236) — roughly 8k minus the voice/profile blocks, not ~5k. The flip side is that the bytes actually sent can reach ~14.5k tokens (12k budget + 2.5k uncounted instructions), which makes the Ollama num_ctx=8192 mismatch worse than stated, not better.

Overlap with prior reviews: the 72-tool surface and its prompt cost are already the P1 finding in docs/architecture-third-opinion-2026-09-18.md:22,160-166,222 (the known-list's "34 tools" is that doc's corrected predecessor); the 420s synchronous REPL block is its §4.7 (line 144); max_steps=20 and 16k output are stated as correct facts in docs/architecture-review-2026-09-18.html:139-140. None of the prior reviews makes the materially new point here: that a profile which writes source files with 20 steps and 16k output has verify=False, no worktree and no resume, in direct contradiction to the scaffold and start_task hint (tools.py marker_hint("start_task") text) that tell the model builds belong in a task, and that the chat input budget is half consumed by fixed prompt with a fallback provider whose context is smaller than the budget. That novel portion is a genuine design contradiction (kind b: a right split undermined by the profile numbers), so severity stays high.

### evidence

- simorgh/orchestration/profiles.py:77 `read_only=False, max_steps=20, max_revisions=0, scaffold="chat", verify=False,` and :90 `max_output_tokens=16_000` (comment: 'Matched to the patch profile, which is what a chat turn now IS')
- python3 -c import: `CHAT tools 72 steps 20 out 16000 verify False ro False` / `PATCH tools 25 steps 20 out 16000 verify True`
- Reproduced: `task_rules chars 12941 tok 3236 | tool_instructions chars 10095 tok 2524 | sum tok 5760` via scaffolds.render(CHAT,...) + cognition.service._tool_instruction_block
- simorgh/orchestration/session.py:59 `WORKTREE_KINDS = frozenset({"patch", "skill"})`; :753-754 `_uses_worktree` returns False for any other kind
- simorgh/orchestration/scaffolds.py:375-376 'A reply here gets one step budget and does not resume: if it runs out, the next message starts again from nothing.'
- simorgh/cognition/config.py:22 `"chat": Budget(12_000, 1_000, 0.05, max_seconds=90.0)`; ~/.simorgh/simorgh.toml `[cognition]` section is empty (no override)
- simorgh/cognition/service.py:307 `elastic_limit = budget.max_tokens_in - protected_tokens`; :325-327 tool_instructions 'Not counted in protected_tokens's budget check' — so the reader's ~5k residual is ~8k minus voice/self/profile blocks
- simorgh/cognition/assembler.py:68 task_rules is a protected block; :52-65 constitution (32 tok), voice, self_summary (budget 300), user_profile also protected
- simorgh/cognition/config.py:114 `tool_result_max_tokens: int = 2_000`; simorgh/orchestration/session.py:1597 `_MODEL_RESULT_CHARS = 8000`
- simorgh/interface/config.py:88 `chat_reply_timeout_s: float = 420.0` (and :85 stale comment 'a chat turn is up to max_steps=6'); simorgh/interface/service.py:976 `reply_text = await asyncio.wait_for(fut, timeout=self.config.chat_reply_timeout_s)`
- ~/.simorgh/simorgh.toml:26-30 `[cognition.providers.ollama] model = "qwen3:4b-instruct" only_purposes = ["chat"] num_ctx = 8192`; simorgh/cognition/providers/ollama.py:138 `options: dict = {"num_ctx": self._num_ctx}`
- Already known: docs/architecture-third-opinion-2026-09-18.md:22,160-166,222 (72 tools, P1 tool routing) and :144 (420s synchronous REPL block); docs/architecture-review-2026-09-18.html:139-140 (max_steps=20, 16k stated as correct)

**corrected claim:** A typed chat turn gets the patch profile's step budget (20) and output budget (16k) and 72 tools (vs 25 for PATCH), yet verify=False, no worktree (WORKTREE_KINDS excludes chat), no resume, and a synchronous 420s REPL wait; its fixed prompt (task_rules ~3.2k tok protected + tool-instruction block ~2.5k tok, the latter sent but not counted against the budget) sits inside a 12k-token chat input budget, leaving roughly 8k minus voice/self-summary/user-profile blocks for memory (<=4k chars) plus a transcript whose tool results are each capped at ~2k tokens; the total actually sent can reach ~14.5k tokens while the Ollama chat fallback is configured with num_ctx=8192. The 72-tool surface and the 420s block were already reported by prior reviews; the task-without-task-semantics contradiction and the budget/fallback mismatch are new.

**severity adjustment:** keep

