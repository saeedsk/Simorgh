# refute:proportionality:The whole transcript is flattened into o

*Workflow: review · Phase: Refute · Agent id: `ad4f83e101de64cf5` · Tool calls: 13*

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
| 1 | Bash | Read assembler flattening code | class PromptAssembler: def __init__(self, bus: Bus, source: str, *, request_timeout: float, logger: Logger \| None = None) -> None: self._bus = bus self._source  |
| 2 | Bash | Read cognition service think_messages assembly |  max_tokens_out=req_budget.get("max_tokens", budget_cfg.max_tokens_out if budget_cfg else 1_000), max_cost_usd=req_budget.get("max_cost_usd", budget_cfg.max_cos |
| 3 | Bash | Read session tool-result append and echo shapes |  # as a turn addressed to it, which is the shape every # tool-using model is trained on. tool_name = call.get("tool") # The model's OWN words, not a synthetic ` |
| 4 | Bash | Read provider message forwarding |  self._api_key = os.environ.get("TOGETHER_API_KEY") if api_key is None else api_key self._model = model or DEFAULT_MODEL self._base_url = base_url.rstrip("/") s |
| 5 | Bash | Check whether any provider uses native tool-call API | __init__.py __pycache__ base.py claude_code.py gemini.py ollama.py together.py simorgh/cognition/providers/base.py:41: self, messages: list[dict], *, tools: lis |
| 6 | Bash | Read how tool instructions and marker parsing work | 67:def _tool_instruction_block(payload: dict) -> str \| None: 68- if payload.get("expected") != "tool_calls": 69- return None 70- tools = tuple(payload.get("tool |
| 7 | Bash | Check caching, compactor roles, and session message trimming | simorgh/cognition/providers/claude_code.py:98: with tempfile.TemporaryDirectory(prefix="simorgh-claude-code-") as workdir: simorgh/cognition/providers/ollama.py |
| 8 | Bash | Locate the compactor and its text output | simorgh/cognition/api.py:123: return "\n\n".join(b.text for b in self.blocks if b.text) simorgh/cognition/api.py:130:class CompactedContext: simorgh/cognition/a |
| 9 | Bash | Check role forwarding in ollama/gemini and use of assembled conversation block | simorgh/cognition/providers/ollama.py:141: sent = [{"role": m.get("role", "user"), "content": m.get("content", "")} simorgh/cognition/providers/ollama.py:142: f |
| 10 | Bash | Read compactor segmenting and CompactedContext.text | class Compactor: def __init__( self, config: Config, ledger: Ledger \| None = None, *, bus: Bus \| None = None, source: str = "cognition", clock: Clock \| None = N |
| 11 | Bash | Check gemini role handling and live provider config | 64: model=self._model, contents=prompt, config=config or None, 70: response = client.models.generate_content(model=self._model, contents=prompt) ---- 22:[cognit |
| 12 | Bash | Check who writes tool-role messages and how compaction layers key on them | == role tool writers == (eval):1: no matches found: --include=*.py == compaction layer1/3 == # -- layer 1: budget reduction ------------------------------------ |
| 13 | Bash | Search for any producer of tool-role messages in code and tests | (exit 0) tests/simorgh/cognition/test_service.py:364: messages = [{"role": "tool", "name": "search", "content": " ".join(f"w{i}" for i in range(500))}] tests/si |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core claim holds: the conversation is rendered into one "[role] content" string and sent as a single user message after two system messages, while the OpenAI-compatible providers (Together, Ollama) would forward roles faithfully. Session code already keeps a real assistant/user alternation and its own comments record the fabrication that the flattened stand-in taught the model, so this is a right design (structured messages end to end) undermined by the final render step, category (b). However the finding is wrong on several particulars: the flattening that reaches the provider is compaction.py:153, not assembler.py:70 (the assembler block is only used for token accounting); the recommendation to use role='tool' with call ids is inapplicable because the system uses text markers, passes tools=None to every provider, and has no call ids at all, and two of four providers (Gemini, Claude CLI) flatten on their own side anyway; the prompt-caching argument is weak because the system messages already form a stable prefix and compaction layers 1-4 rewrite older segments in place; and "compaction operates on text segments" is false, it operates on message dicts. The materially new fact is that no production code path ever writes a role='tool' message (only tests do), so compaction layers 1 and 3, which key on role=='tool', are dead in production: a concrete unconnected wire that the recommendation would fix as a side effect. At this scale (one laptop, chat on qwen3:4b at num_ctx 8192, Together for other purposes) the harm is real but bounded and already partly guarded; the fix is small (compaction.py render + service.py:339-340 + session.py result role), so 'critical' overstates it. Lower to high.

### evidence

- simorgh/cognition/compaction.py:153 `rendered = "\n\n".join(f"[{s.message.get('role', 'user')}] {s.message.get('content', '')}" for s in segments)` -- this, not assembler.py:70, is the flattening that reaches the provider
- simorgh/cognition/service.py:296-297 uses assembled.blocks only to collect protected blocks and count their tokens; the assembler's 'conversation' block is never sent
- simorgh/cognition/service.py:331-342 think_messages = [system protected_text], [system tool_instructions], [user compacted.text]
- simorgh/cognition/service.py:357-358 `self._router.complete(purpose, think_messages, tools=None, ...)` -- no provider is ever given tools
- simorgh/cognition/service.py:67-93 _tool_instruction_block: tools are invoked by writing `NAME: arg` as the first line; simorgh/orchestration/session.py:176 `_MARKER_LINE = re.compile(r"^\s*[A-Z][A-Z0-9_]{2,}:\s", re.M)` -- text markers, no call ids exist
- simorgh/orchestration/session.py:1027-1031 appends {'role':'assistant', 'content': model text}; session.py:1039-1046 appends {'role':'user', 'content': 'Result of <tool>:...'}; comment at 1018-1026 records the 2026-09-08 fabricated `[tool_call run_tests] [result message]` reply
- simorgh/orchestration/session.py:161-165 _ECHO_SHAPES catches '[tool_call ' and '[result message]'
- simorgh/cognition/providers/together.py:126-130 and ollama.py:141-142 forward {role, content} per message unchanged
- simorgh/cognition/providers/gemini.py:38 `prompt = "\n\n".join(m.get("content", "") for m in messages if m.get("content"))` and claude_code.py:78-84 -- two of four providers flatten on their own side regardless
- Command: `grep -rn '"role": "tool"' simorgh/ | grep -v compaction.py` -> no output. Only tests produce tool-role messages: tests/simorgh/cognition/test_compaction.py:34,46; tests/simorgh/cognition/test_service.py:364
- simorgh/cognition/compaction.py:168 `seg.message.get("role") == "tool" and seg.tokens > cap` (layer 1) and compaction.py:209 `if seg.protected or seg.message.get("role") != "tool": continue` (layer 3) -- both layers are dead in production because results arrive as role='user'
- simorgh/cognition/compaction.py:114-116 compactor builds _Segment per message dict, so 'compaction operates on text segments' is false
- ~/.simorgh/simorgh.toml:26-32 [cognition.providers.ollama] model = "qwen3:4b-instruct", only_purposes = ["chat"], num_ctx = 8192 -- the live chat provider is a small local model with an 8k window, where a flattened transcript costs real headroom but the harm is bounded

**severity adjustment:** lower

**corrected claim:** The session keeps a real assistant/user alternation (session.py:1027-1046), but Cognition's compactor (compaction.py:153, not assembler.py:70) renders every message into one "[role] content" string that service.py:339-340 sends as a single user turn after two system messages, so Together and Ollama, which forward roles faithfully, never see the alternation; the guards in _ECHO_SHAPES exist because of this. Separately, no production code ever writes a role='tool' message, so compaction layers 1 and 3 (compaction.py:168, 209), which target tool-role segments, never fire outside tests. The fix is small and provider-agnostic: render session.messages as alternating messages (assistant text, results as role='user' or role='tool' with no ids, since tool use is text-marker based and tools=None is passed to every provider), keep the protected blocks as the system prompt, and let Gemini and the Claude CLI providers keep their own in-provider flattening. The prompt-caching benefit is marginal because the system prefix is already stable and compaction rewrites old segments in place.

