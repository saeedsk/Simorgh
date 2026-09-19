# refute:correctness:The whole transcript is flattened into o

*Workflow: review · Phase: Refute · Agent id: `a4b35a627b43c0e15` · Tool calls: 8*

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
    "title": "The whole transcript is flattened into one user message; tool results are never tool-role messages",
    "kind": "wrong-design",
    "severity": "critical",
    "claim": "Cognition joins every message of session.messages into a single '[role] content' string and sends it as one user turn after two system messages, so the model never sees an assistant/tool alternation and is asked to continue a conversation whose last turn it cannot distinguish from its own.",
    "evidence": [
      "simorgh/cognition/assembler.py:70 `conversation = \"\\n\\n\".join(f\"[{m.get('role', 'user')}] {m.get('content', '')}\" for m in messages)`",
      "simorgh/cognition/service.py:329-340: think_messages = [system: protected_text], [system: tool_instructions], [user: compacted.text]",
      "simorgh/orchestration/session.py:1029-1050: tool results are appended as {'role':'user','content':'Result of read_file:\\n...'} and the code comment says it was changed from an assistant message because the model 'lost the thread'; the fix never reached the provider because the assembler re-flattens it",
      "simorgh/cognition/providers/together.py:126-130 forwards messages role-for-role, so the flattening is purely self-inflicted upstream",
      "session.py:161-175 _ECHO_SHAPES exists to catch the model reproducing '[tool_call X]' / '[result message]' text, which is exactly the shape the flattened transcript teaches it"
    ],
    "why_it_matters": "Models are trained on real tool-use turns; a flattened blob defeats that training (hence the fabricated results the guards catch), removes any stable prefix for prompt caching, and makes compaction operate on text segments rather than on tool-result messages that could be dropped or summarised individually.",
    "recommendation": "Send session.messages as real messages (assistant text/tool_calls, tool results as role='tool' with the call id) and keep only the protected blocks as the system prompt. The compactor already works on the raw message list (service.py:300-306), so this is a change in assembler.py and service.py:329-341 only; the Claude CLI provider (claude_code.py:78-84) would keep its own flattening as the one place that needs it.",
    "confidence": 0.95
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/cognition/assembler.py | 1 """Prompt assembly (docs/blueprint/subsystems/04-cognition.md section 5, 2 "Prompt assembly order"): ordered blocks, each `protected` (never 3 compacted -- pr |
| 2 | Read | /Users/saeed/ws/Simorgh/simorgh/cognition/service.py (from line 280) | 280 max_tokens_out=req_budget.get("max_tokens", budget_cfg.max_tokens_out if budget_cfg else 1_000), 281 max_cost_usd=req_budget.get("max_cost_usd", budget_cfg. |
| 3 | Bash | Read cited session, provider, and tool-role code |  return text cut = text[:limit] last_space = cut.rfind(" ") if last_space > limit * 0.5: cut = cut[:last_space] return cut + " ...[cut]" # Shapes a reply takes  |
| 4 | Bash | Check compactor output shape, session context, and known-findings docs | ugrep: warning: simorgh/cognition/compactor.py: No such file or directory ---- step = Step(step_no, "act", detail, tool=call.get("tool"), ok=ok, denied=was_deni |
| 5 | Bash | Find compactor and verify its output shape | __init__.py __pycache__ api.py assembler.py budget.py compaction.py config.py parser.py providers router.py service.py tokens.py ---- simorgh/cognition/compacti |
| 6 | Bash | Inspect compaction output shape and provider list | 29:or with `role: "system"` is a *segment-level* protection recognized by 87: return bool(message.get("protected")) or message.get("role") == "system" 91:class  |
| 7 | Bash | Check whether anything writes tool-role messages that compaction expects | (eval):1: no matches found: --include=*.py --- writers of role tool above (excluding compaction) --- # -- layer 1: budget reduction ---------------------------- |
| 8 | Bash | Confirm no writer of tool-role messages and check remaining details | --- (end writers of role=tool) --- simorgh/cognition/config.py:114: tool_result_max_tokens: int = 2_000 simorgh/cognition/config.py:167: "tool_result_max_tokens |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** The claim holds against the code as of today, with one correction to the evidence trail and one material addition. Correction: the assembler's flattened "conversation" block (assembler.py:70) is computed but never sent -- service.py:296 keeps only protected blocks, and the text that actually reaches the provider is the Compactor's own re-flattening at compaction.py:153 (`rendered = "\n\n".join(f"[{role}] {content}" ...)`) and :325, which uses the identical `[role] content` shape. So the flattening is real, it just happens in compaction.py, not assembler.py; assembler.py:70 is dead work. service.py:329-342 then sends exactly [system protected][system tool instructions][user compacted.text]. Both live API providers forward roles faithfully (together.py:126-130, ollama.py:141-142), so the loss is self-inflicted upstream, as claimed. session.py:998-1043 confirms the creator deliberately split tool results into an assistant turn + a user turn "which is the shape every tool-using model is trained on" -- an intent the single-user-message packaging defeats. _ECHO_SHAPES at session.py:161-165 confirms the fabricated-transcript symptom. Material addition not in the finding or the known list: compaction layers 1 and 2 (truncate oversized tool results to tool_result_max_tokens=2000 and blob them to the Ledger; dedupe identical tool results) fire only on segments with role == "tool" (compaction.py:168, :209), but nothing in simorgh/ ever writes a role "tool" message -- tool results are appended as role "user" (session.py:1043). Those two layers are therefore dead code: an "unconnected wire" instance the finding strengthens rather than repeats. One caveat on the recommendation: Simorgh uses a text-marker tool protocol (`READ_FILE: ...`, service.py:67-80; providers are called with tools=None at service.py:358), so there is no native call id to attach; the achievable fix today is sending session.messages as real alternating assistant/user (or tool) messages and tagging tool results with role "tool" so the compactor's existing layers wake up. Not already known: the audit's line 47 concerns 34 tools in CHAT; the known "no sliding dialogue buffer" item is about orchestration/context.py, a different thing. Severity: the system demonstrably completes tasks with the flattened transcript (SWE-bench level-1 resolutions), so this degrades quality, caching and compaction rather than breaking the core loop; "high" is more honest than "critical".

### evidence

- simorgh/cognition/compaction.py:153 `rendered = "\n\n".join(f"[{s.message.get('role', 'user')}] {s.message.get('content', '')}" for s in segments)` -- this, not assembler.py:70, is the string that reaches the provider
- simorgh/cognition/service.py:296 `protected = [b for b in assembled.blocks if b.protected]` -- the assembler's elastic 'conversation' block is discarded; only compacted.text is sent
- simorgh/cognition/service.py:329-342 builds think_messages as [system protected_text], [system tool_instructions], [user compacted.text]
- simorgh/cognition/service.py:358 `self._router.complete(purpose, think_messages, tools=None, ...)` -- no native tool calling; tools are a text-marker protocol (service.py:67-80 `_tool_instruction_block`)
- simorgh/cognition/providers/together.py:126-130 and ollama.py:141-142 forward `{role, content}` per message, so role structure would survive if it were sent
- simorgh/orchestration/session.py:998-1043: comment explains the split into assistant turn + user 'Result of <tool>:' turn 'which is the shape every tool-using model is trained on'; result appended with 'role': 'user' at :1043
- simorgh/orchestration/session.py:161-165 `_ECHO_SHAPES` catches '[tool_call ' and '[result message]' shapes in replies
- simorgh/cognition/compaction.py:168 and :209: layers 1 and 2 act only on `seg.message.get("role") == "tool"`; `grep -rn "role.: .tool" simorgh --include='*.py' | grep -v compaction.py` returns nothing -- no writer exists, so tool_result_max_tokens (config.py:114, default 2000) never applies
- docs/architecture-audit-2026.md:47 is the only prior mention of 'flatten' and concerns 34 tools in CHAT, not transcript shape -- finding is not already known

**severity adjustment:** lower

**corrected claim:** Cognition sends the whole transcript as one user message: the Compactor (compaction.py:153, not the assembler -- assembler.py:70's conversation block is computed and discarded) joins every session message into a single '[role] content' string, which service.py:339-340 sends as one user turn after two system messages. The providers forward roles faithfully, so the loss is upstream. Because tool results are appended as role 'user' (session.py:1043) and nothing ever writes role 'tool', the compactor's tool-result truncation and dedupe layers (compaction.py:168, :209) are dead code, and the assistant/user split the session code deliberately makes (session.py:998-1043) never reaches the model as real turns.

