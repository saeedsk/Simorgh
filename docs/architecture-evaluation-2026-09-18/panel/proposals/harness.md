# propose:harness

*Workflow: panel · Phase: Propose · Agent id: `a673eb5981b99ca30` · Tool calls: 28*

## Task given to the agent

```text
You are on a design panel for Simorgh, a from-scratch personal AI agent. The creator's ask, verbatim: "as a very professional top of the line AI and AI agent scientist and the most expert in this domain, look at the high level architecture of Simorgh, and suggest where we went right and how we should re-architect Sim to make sure Sim is aligned on where the AI agent future lies and be highly performing, highly sophisticated, advanced agent that we can continue investing in, adding features and make more and more intelligent -- and how we can improve its reasoning, ability to perform long tasks, better interact with environment and user, and how building blocks and modules can get improved both in terms of merging modules or adding new modules or algorithms or methods to make sure Sim is a state of the art and cutting edge AI agent and at some point it can be considered AGI."
  
  
  ESTABLISHED FACTS ABOUT SIMORGH TODAY (verified against the code at /Users/saeed/ws/Simorgh on 2026-09-18; do not re-derive, but do read the cited files to understand them):
  - ~87k lines in simorgh/, 18 subsystem packages composed by a Kernel (kernel/registry.py LAYERS), talking only through a typed async Bus (in-memory by default; sqlite and AWS SNS/SQS backends exist), 175 topic constants, 174 JSON schemas. The import rule "only contracts is shared" genuinely holds (only kernel imports other subsystems).
  - All state is an append-only Ledger of events (ledger/backends/jsonl.py, fsync per append). Live ledger: 1.4 GB, 118,215 stream files (88,356 trace:<id>, 26,737 action:<id>, 2,431 task:<id>); biggest single streams are metrics:history 114 MB, curiosity:ticks 43 MB, persona:state 17 MB.
  - Every effect is action.proposed -> Guardian (12 rules, HMAC token) -> action.approved -> Execution (re-verifies token) -> action.result. Structural, bus-enforced, proved at boot.
  - THE MODEL DOES NOT USE NATIVE TOOL CALLING. Every provider adapter (cognition/providers/together.py, claude_code.py, ollama.py, gemini.py) accepts a tools= argument and ignores it. Tool calls are parsed out of free text by a home-grown marker protocol (cognition/parser.py: one string argument per MARKER: line, plus a JSON second-line hack for multi-arg tools; orchestration/tools.py maps markers to tools). One action per step, except batches of read-only calls. Consequently orchestration/session.py (1,942 lines) carries a family of regex police for model text: invented_markers, unhonoured_marker, _transcript_echo (fabricated results), claimed_to_commit, promised_behaviour, claimed_tv_act, claimed_to_note_a_pronunciation -- each a live-caught incident turned into a heuristic.
  - Tool results reach the model bounded at 8,000 chars (session.py _MODEL_RESULT_CHARS) with an explicit "cut" note; ledger detail at 2,000 chars.
  - A CLI chat turn is a THROWAWAY Session: interface mints a fresh session_id per typed line; there is no transcript; continuity = memory recall (orchestration/context.py). Memory recall = hashed bag-of-words embeddings by default (memory/embed.py, sha256 token buckets, 256 dims; "hashing" is the configured default because sentence-transformers cost 24.9 s on first call), scoring EVERY record on every recall (memory/store.py retrieve), under a 0.25 s timeout -- so the memory block silently vanishes once the store is large or the machine is loaded.
  - Cognition: router over five providers (Together primary, Claude CLI, Gemini, Ollama, a deterministic "floor"), per-provider rolling budgets, purpose filters, compaction. Prompt assembly is split between cognition/assembler.py (persona voice + self summary as protected blocks) and orchestration/context.py (memory block + task + carried attempt notes + messages).
  - Growth layer: Learning (outcomes, competence table, self-patch pipeline that names a tool self_patch.draft that does not exist), Reflection (observer only), Curiosity (idle-tick exploration). World Model holds the Self Model; capabilities["tools"] is never written.
  - Self-modification: patch/skill tasks work in a git worktree of the named repo and land on main via rebase + whole-suite gate + fast-forward (docs/plans/worktree-landing-design.md). Boot goes through simloader.py which runs a curated core test set and rolls back to the last sim-good-N tag on failure. Guardian protects docs/SOUL.md, simorgh/{guardian,execution,contracts,kernel}/, simloader.py, sim.sh; tests/ is NOT protected.
  - Voice: 10.2k lines (vad, turns, stt/, tts/, speakers with TitaNet, session.py 1,961 lines, planner, playback, echo tracker). Measured live 2026-09-18: stt 1.8-6.8 s, llm 1.3-9.5 s, full response 4-17 s.
  - Interface: 10.7k lines (CLI/TUI, dispatch.py 2,234 lines of command dispatch, httpapi.py, dashfeeds, Telegram, WhatsApp); subscribes to 30 topics. Live config binds http to 0.0.0.0; auth only if SIM_API_TOKEN is set.
  - Execution: 21.6k lines, 98 tools at runtime across files/code/git, sandboxes, web, packages + domains knowledge/pim/security/home/energy/media. Home Assistant is NOT configured; cameras are RTSP -> local ffmpeg -> HLS on disk; workspace/ is 11 GB (voice 6.4 GB, cameras 3.8 GB).
  - v1 (src/, 16.4k lines, 39 test files) is retired but still in the tree. No pyproject.toml, no ruff/mypy config. 1,118 comments in simorgh/ are dated incident notes ("live-caught 2026-09-07 ...").
  - Test suite: 447 test files / 90k lines (larger than the code); the project's own retrospective (docs/blueprint/07-post-cutover-review.md section 4) concluded unit tests assert code shape and missed every real blocker; real bugs were found by running single watched tasks (tools/trial.py) and observer waves.
  - The creator is one person, hands-free style (delegates heavily to coding agents), runs Sim on one laptop for one family; cloud model is the primary brain, Ollama is fallback only. Stated purpose (docs/SOUL.md): a capable, trustworthy, continuously improving assistant that grows more skilled without growing less safe; corrigibility and restraint are directives.
  
  
  Rules:
  - Read to confirm, do not re-audit: docs/module-map.md, docs/blueprint/01-vision-and-principles.md, docs/blueprint/02-system-architecture.md, and the code paths named above (orchestration/session.py _run and _think, orchestration/context.py, cognition/router.py, cognition/parser.py, memory/store.py, worldmodel/selfmodel.py, guardian/rules.py, learning/service.py, reflection/service.py, curiosity/service.py, voice/session.py top). Do not modify files, do not boot the system, do not run the suite, do not call paid models.
  - Think at the level of architecture, algorithms and methods, not bug fixes. Be specific: name the module, what it becomes, what algorithm/method/data structure replaces what, and what measurable capability it unlocks.
  - Ground every claim about "where agents are going" in patterns that are well established by 2026 and that you are confident about (native structured tool use; single-loop agent harnesses with context management and compaction; sub-agent delegation with isolated contexts; skills/procedural memory; hierarchical planning with verification and critic loops; tiered memory (working/episodic/semantic/procedural) with real embeddings and retrieval indexes; MCP as the tool-integration standard; computer-use/browser agents; eval-driven development; model routing by task; long-horizon agents that checkpoint and resume). If you cite a specific paper or system, only do so when you are sure it exists; otherwise describe the pattern generically. Flag uncertainty explicitly.
  - On "AGI": be honest and precise. Say what an architecture like this can and cannot deliver, what "more general" concretely means for a household agent, and which investments compound.
  - Proportionality: one developer, one laptop, one family, cloud model as brain. Every recommendation must be achievable incrementally without a rewrite from zero, and must preserve the proposal->approval->effect safety invariant and corrigibility.
  - Your final text is data for an orchestrator, not a message to a human. Return only the structured output.
  
  
  LENS: the modern agent HARNESS. You have built and studied the best 2026 coding/computer-use agent harnesses (single agent loop, native tool use, context management and compaction, sub-agents with isolated context, skills, hooks, permission modes, resumable sessions). Re-architect Sim's loop (orchestration + cognition + the marker protocol + profiles + scaffolds) as such a harness while keeping Guardian in the path of every effect. Be concrete about the message/turn model, tool schema, parallel tool calls, streaming, compaction, delegation, and what the bus is still for.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count lines in cited files and list orchestration/cognition packages |  452 docs/module-map.md 241 docs/blueprint/01-vision-and-principles.md 494 docs/blueprint/02-system-architecture.md 1942 simorgh/orchestration/session.py 327 si |
| 2 | Bash | Read the module map | # Simorgh — Module Map and System Blocks **What this is.** One picture of every major building block, what each one owns, and how they interact — written so a s |
| 3 | Bash | Read vision and principles blueprint | # 01 — Vision and Principles > Part of the Simorgh v2 blueprint. Read `00-README.md` first for how this > set fits together. This file states *what we are build |
| 4 | Bash | Read system architecture blueprint | <persisted-output> Output too large (32.5KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 5 | Bash | Outline session.py: functions, classes, regex police locations | 40:def was_denied(detail: str) -> bool: 71:def record_side_effects(session, effects) -> None: 139:def _trim_evidence(text: str, limit: int) -> str: 168:def _tra |
| 6 | Bash | Read the marker protocol parser | """Output parsing: markers, edit blocks, non-answer detection (docs/ blueprint/subsystems/04-cognition.md section 5, "Output parsing"). Ported directly from v1  |
| 7 | Bash | Read orchestration context assembly | """ContextAssembler (16 section 5): gathers the memory block and the session transcript for one `cognition.think` call. The persona voice and the self summary a |
| 8 | Bash | Read cognition router and prompt assembler | """Provider failover and selection (docs/blueprint/subsystems/04- cognition.md section 5). Ported from v1 `CognitionRouter`'s failover shape: try each candidate |
| 9 | Bash | Read the cognitive loop section of the architecture blueprint | ## 4. Package layout and module rules ``` simorgh/ # the v2 package (v1 stays in src/ until cutover; see 06-migration) __init__.py __main__.py # `python -m simo |
| 10 | Bash | Read SessionRunner._run |  async def _run(self, session: Session, *, user_text: str = "") -> Outcome: await self._append(session, topics.TASK_STARTED, {"task_id": session.task_id, "worke |
| 11 | Bash | Read SessionRunner._think, _delegate, _reground |  async def _think(self, session: Session, user_text: str, *, last_step: bool, no_tools: bool = False) -> Message \| None: steps_left = session.budget.steps_left  |
| 12 | Bash | Read memory store retrieve and embedding | 35:def stream_for(kind: str) -> str: 51:class WorkingMemory: 77: def __init__(self, *, max_turns: int, max_chars: int) -> None: 82: def add(self, session_id: st |
| 13 | Bash | Read Self Model head and Guardian rules outline | """The Self Model. Identity is real, loaded and hashed from `docs/SOUL.md`. As of Phase 4 Wave 2 the other sections (competence, limitations, change_history, ca |
| 14 | Bash | Read learning service, reflection and curiosity heads | """`Service`: wires `OutcomeRecorder`, `CompetenceTable`, strategy suggestion, and the patch/skill pipeline runner into the real Bus/Ledger (spec section 5). Sc |
| 15 | Bash | Read voice session top | """The spoken conversation: microphone frames in, speech out, with the floor changing hands the way it does between people. frames -> FrameVad -> TurnManager -> |
| 16 | Bash | Read tools mapping, profiles and scaffolds heads | """ToolCallRouter (16 section 5): a `cognition.think` tool_call becomes an `action.proposed` payload. Guardian is the sole authority on whether it's actually ap |
| 17 | Bash | Read together provider complete, compaction head, toolargs head | 117: self, messages: list[dict], *, tools: list[dict] \| None, max_tokens: int, timeout: float \| None = None, ---- async def complete( self, messages: list[dict] |
| 18 | Bash | Find how cognition service instructs the model about markers | 35:# `{kind, markers?}` dict (04 section 5's `OutputSpec`). "tool_calls" is the 37:# doubles as the marker set `_parse_markers` scans for. 38:def _expected_spec |
| 19 | Bash | Check the execution Tool protocol for schemas and list execution package | ugrep: warning: simorgh/execution/api.py: No such file or directory ---- sed: simorgh/execution/api.py: No such file or directory ----REGISTRY---- ugrep: warnin |
| 20 | Bash | Read resume, progress-note and worker heads | """What a Session inherits from the `task:<id>` stream before it runs. Two different situations look alike from here -- a task whose last worker died mid-run, a |
| 21 | Bash | Read skills catalog and where skills live |  def _skills(self) -> list: """Every valid skill under the configured roots, read once per runner. A broken skill is not a crash and not silence: `discover_skil |
| 22 | Bash | Check MCP support and the Provider protocol | simorgh/execution/mcp.py simorgh/execution/container.py simorgh/execution/config.py simorgh/execution/external.py simorgh/execution/mcp.py simorgh/execution/ser |
| 23 | Bash | Read long-run context design, verification and planning heads | Exit code 1 # Long runs: context, delegation and model tiers The creator, 2026-09-15, after the first ten-copy benchmark wave: "what architecture changes do you |
| 24 | Bash | Read kernel layers, memory kinds, consolidation and the post-cutover test review | `LAYERS` order below is unchanged from the Phase 0 draft -- it was already the full target, kept complete on purpose so adding a subsystem was always meant to b |
| 25 | Bash | Read the marker-convention instruction text the model receives | # Live-caught (the creator, real use: Sim telling them "no MCP servers # connected... no fetch tool" turn after turn, even after `web_fetch` # and `propose_mcp_ |
| 26 | Bash | Check whether execution tools carry descriptions or argument schemas | 126:class ReadFileTool: 131: args_schema = {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}} 187:class ListDirTool: 192: args |
| 27 | Bash | Read Claude CLI provider, planning decomposer and skill card format heads | """Claude Code CLI provider (docs/blueprint/subsystems/04-cognition.md section 11): body ported unchanged from v1 `src/cognition/claude_code_provider.py`, `comp |
| 28 | Bash | Check MCP schema flattening and tool registration wire | class McpTransportError(Exception): """The server's process failed to start, crashed, sent malformed data, or returned a JSON-RPC error. Never raised past a too |

## Structured reply

**lens:** The modern agent harness (2026 coding/computer-use agent shape): one agent loop over a typed turn transcript, native structured tool use with JSON-schema tools, parallel tool calls, streaming deltas, token-pressure compaction with protected prefix, hooks (pre/post tool, stop, pre-compact, session-start), declarative agent definitions as permission modes, sub-agents with isolated context, skills as procedural memory, resumable sessions. Applied to Simorgh with one non-negotiable: Guardian stays the mandatory PreToolUse hook for every effect (action.proposed -> HMAC-approved -> Execution), and corrigibility (pause/stop/human gate) stays structural.

### what sim got right

##### 1. The action path is structural: action.proposed -> Guardian (12 ordered rules, HMAC token) -> action.approved -> Execution (re-verifies token) -> action.result, with the subscribe/publish invariants enforced by the Bus and proved at boot (contracts/topics.py SUBSCRIBE_ONLY_BY/PUBLISH_ONLY_BY, kernel/selfcheck.py).

- **decision:** The action path is structural: action.proposed -> Guardian (12 ordered rules, HMAC token) -> action.approved -> Execution (re-verifies token) -> action.result, with the subscribe/publish invariants enforced by the Bus and proved at boot (contracts/topics.py SUBSCRIBE_ONLY_BY/PUBLISH_ONLY_BY, kernel/selfcheck.py).
- **why it matters for the future:** Every 2026 harness has a permission layer; almost all implement it as convention inside the loop (a hook callback the loop may forget to call). Sim's is a bus topology no code path can bypass, and it is exactly the shape a parallel-tool-call, sub-agent, self-modifying agent needs: N tool_use blocks in one turn become N proposals, each independently gated, and a child agent cannot inherit an approval. This is the one part of the design that becomes MORE valuable as autonomy grows.
- **keep or strengthen:** Keep byte-for-byte. Make it the loop's mandatory PreToolUse hook (the harness cannot construct a ToolResult for an external tool except from an action.result). Extend Guardian's protected paths to the new agent-definition directory and the hooks package, since those now hold permission posture (principle 4.11: loosening is human-only).

##### 2. Append-only Ledger as the only truth, with projections rebuilt from it; task:<id> streams; orchestration/resume.py distinguishing a crash (continue the attempt) from a retry (new budget, carried memory of earlier attempts).

- **decision:** Append-only Ledger as the only truth, with projections rebuilt from it; task:<id> streams; orchestration/resume.py distinguishing a crash (continue the attempt) from a retry (new budget, carried memory of earlier attempts).
- **why it matters for the future:** Resumable, checkpointed long-horizon sessions are the defining property of long-task agents. Sim already has the substrate (durable step events, lease heartbeat, worker-agnostic resume); what it lacks is that the transcript itself is not on the ledger. Once the session transcript is a stream, resume, replay, audit, eval-from-traces and compaction all read the same data.
- **keep or strengthen:** Strengthen: add a session:<id> stream (typed turns) as the unit of persistence for chat, tasks and sub-agents alike; snapshot every N events. Fix the cost side separately (fsync per append and one trace stream per message are what made 118k stream files).

##### 3. Contracts-only import rule, 175 typed topics, 174 JSON schemas, one package per subsystem; only Kernel composes.

- **decision:** Contracts-only import rule, 175 typed topics, 174 JSON schemas, one package per subsystem; only Kernel composes.
- **why it matters for the future:** This is what makes the re-architecture below feasible incrementally: moving orchestration+cognition into one agent package changes no other subsystem, and replacing Memory's internals is invisible to everyone. It is also what lets coding agents work on modules in parallel (the creator's actual development style).
- **keep or strengthen:** Keep. Stop using it as the reason tool descriptions do not reach the model: tool.registered already carries description and args_schema across the bus, so the boundary was never the blocker.

##### 4. Profiles (per-kind tool allowlists, step budgets, verify flag, scaffold text) plus per-profile scaffolds rendered into a protected task_rules block; a 'chat' profile that can write files, install packages and start tasks.

- **decision:** Profiles (per-kind tool allowlists, step budgets, verify flag, scaffold text) plus per-profile scaffolds rendered into a protected task_rules block; a 'chat' profile that can write files, install packages and start tasks.
- **why it matters for the future:** This is the harness pattern of declarative agent definitions / permission modes (an agent = tools + model + budget + system prompt + isolation). Sim reached it from the other side, one live-caught incident at a time, and the content of those scaffolds is hard-won and correct.
- **keep or strengthen:** Strengthen into files: agents/<name>.md with frontmatter (tools, model_tier, max_turns, max_cost_usd, max_wall_s, max_parallel_tools, verify, isolation, compaction thresholds) and the scaffold as body; Guardian-protected; loaded by Kernel. profiles.py and scaffolds.py become the loader.

##### 5. Skills in the open Agent Skills format (SKILL.md with frontmatter; catalog of name+description in every task; body loaded only on use_skill), discovered from configured roots, per-profile allowlists.

- **decision:** Skills in the open Agent Skills format (SKILL.md with frontmatter; catalog of name+description in every task; body loaded only on use_skill), discovered from configured roots, per-profile allowlists.
- **why it matters for the future:** Procedural memory as files the model can read, the creator can diff, and Guardian can protect is the pattern that scales capability without code: a skill is cheaper, safer and more transferable than a tool or a subsystem. It is also the natural OUTPUT of a self-improvement loop.
- **keep or strengthen:** Keep. Make skills the primary artifact the growth layer produces (reflection/distillation.py already drafts them) and gate promotion on an eval delta, not on a model's opinion.

##### 6. In-process delegation (`delegate`): a child Session with fresh context, its own small budget, read-only research profile, summary-only return, depth cap, and tier escalation when a helper fails.

- **decision:** In-process delegation (`delegate`): a child Session with fresh context, its own small budget, read-only research profile, summary-only return, depth cap, and tier escalation when a helper fails.
- **why it matters for the future:** Sub-agents with isolated context are how 2026 harnesses keep the parent's context clean and parallelize exploration; running the child in-process (not through the task queue) is the right call for a one-worker deployment and avoids the self-deadlock the design doc identified.
- **keep or strengthen:** Generalize into a `Task(agent, brief, isolation, budget)` built-in tool that can spawn any agent definition (research, verify, planner, skill-writer), concurrently up to a cap, each on its own session stream.

##### 7. Progress-note re-grounding (goal / done / learned / next / open questions as a structured JSON note) replacing the transcript every N steps, forced on context_too_large, and carried across attempts.

- **decision:** Progress-note re-grounding (goal / done / learned / next / open questions as a structured JSON note) replacing the transcript every N steps, forced on context_too_large, and carried across attempts.
- **why it matters for the future:** Structured summaries with a preserved 'next' are the compaction strategy that actually works for long tasks (a free-form summary loses the plan). Sim already has the right note shape.
- **keep or strengthen:** Keep the note; change the trigger from step count to measured token pressure, precede it with cheaper tool-result aging, and apply it to chat sessions too.

##### 8. Cognition router: ordered failover with per-provider rolling budgets replayed from the ledger, shared deadline slices, cooldown circuit breaker, truncation retry, purpose filters, image-capability filter, tier escalation (strong tier on attempt N or helper failure).

- **decision:** Cognition router: ordered failover with per-provider rolling budgets replayed from the ledger, shared deadline slices, cooldown circuit breaker, truncation retry, purpose filters, image-capability filter, tier escalation (strong tier on attempt N or helper failure).
- **why it matters for the future:** Model routing by task and cost is standard; the operational details here (billable-on-failure accounting, deadline sharing so the last candidate still gets a slice) are the ones most harnesses get wrong. This is a real asset.
- **keep or strengthen:** Keep as the core of a slimmer `llm/` gateway. Add streaming, native tool dialects, prompt-cache-aware ordering and per-purpose reasoning effort.

##### 9. Verification as an independent evaluator that never runs tools itself: eleven mechanical checks cheapest-first, model checklist at LIGHT+ rigor, trajectory scoring, an explicit insufficient_evidence outcome; worktree landing = rebase + whole-suite gate + fast-forward; simloader boots through a curated core test set and rolls back to the last sim-good tag.

- **decision:** Verification as an independent evaluator that never runs tools itself: eleven mechanical checks cheapest-first, model checklist at LIGHT+ rigor, trajectory scoring, an explicit insufficient_evidence outcome; worktree landing = rebase + whole-suite gate + fast-forward; simloader boots through a curated core test set and rolls back to the last sim-good tag.
- **why it matters for the future:** Critic loops and self-modification with a mechanical floor are what make 'continuously improving without becoming less safe' more than a slogan. Few personal agents have any of this; Sim has all three.
- **keep or strengthen:** Keep. Make Verification the Stop hook of every task agent (bounded revise loop) and expose it as a `verify` sub-agent; add a trajectory check 'claimed effect has a matching tool_result' from the session stream, which replaces most regex police.

##### 10. Honesty doctrine in the wire: a floor never fabricates; non_answer is distinct from rejection; 'memory could not be consulted' is a different prompt from 'no memory matched'; failovers and denials are logged, never silent.

- **decision:** Honesty doctrine in the wire: a floor never fabricates; non_answer is distinct from rejection; 'memory could not be consulted' is a different prompt from 'no memory matched'; failovers and denials are logged, never silent.
- **why it matters for the future:** Agents fail worst when a tool result says something false. This doctrine carries straight into a native ToolResult{is_error, content} protocol and into evals.
- **keep or strengthen:** Keep as a written rule for every ToolResult and every compaction stub ('[result of read_file, 41,203 chars, ref session:x#12]' is honest; a silent cut is not).

##### 11. Measure-from-the-ledger discipline: tools/trial.py and trial_suite.py (single watched real tasks), observer waves, docs/findings/, and a benchmark unit (GAIA, BFCL, SWE-bench with per-model history).

- **decision:** Measure-from-the-ledger discipline: tools/trial.py and trial_suite.py (single watched real tasks), observer waves, docs/findings/, and a benchmark unit (GAIA, BFCL, SWE-bench with per-model history).
- **why it matters for the future:** Eval-driven development is the only way a one-person team can re-architect the loop without regressing. The project's own retrospective says the 90k-line unit suite missed every real blocker and the trial harness found them all.
- **keep or strengthen:** Make it the merge gate: every migration stage below lands only with trial-suite and benchmark deltas recorded in docs/findings/.


### where it diverges from the future

##### 1. Tool calls are parsed out of free text by a marker protocol: `NAME: argument` on its own line, one string argument, a JSON-second-line hack for multi-field tools, a hand-maintained _CODE_BEARING_MARKERS set that has been wrong every time a tool was added, and tool_hints as prose. Every provider adapter ignores tools=. Execution tools already declare JSON args_schema and descriptions; both are thrown away before the model sees them. MCP tools with more than one property cannot be called at all (mcp_single_arg_key).

- **current:** Tool calls are parsed out of free text by a marker protocol: `NAME: argument` on its own line, one string argument, a JSON-second-line hack for multi-field tools, a hand-maintained _CODE_BEARING_MARKERS set that has been wrong every time a tool was added, and tool_hints as prose. Every provider adapter ignores tools=. Execution tools already declare JSON args_schema and descriptions; both are thrown away before the model sees them. MCP tools with more than one property cannot be called at all (mcp_single_arg_key).
- **future pattern:** Native structured tool use: the model receives ToolSpec{name, description, input_schema} in the provider's dialect (OpenAI-style functions for Together/Ollama, Anthropic tools, Gemini function declarations), emits typed tool_use blocks with JSON input validated against the schema, and receives tool_result blocks keyed by the call id. The ProviderResponse.tool_calls field already exists and is never filled.
- **gap:** This single divergence is the root of the session.py regex-police family (invented_markers, unhonoured_marker, _transcript_echo, claimed_to_commit, promised_behaviour, claimed_tv_act, claimed_to_note_a_pronunciation), of the 246-tool-runs-without-a-write incident, of the first-line-argument truncations, of multi-arg tools being unreachable, and of a measurable BFCL ceiling. With schemas, an unknown tool is a schema error not a regex catch, a multi-line payload is a JSON string, and 'narrating a call' has no syntax to leak through.

##### 2. A CLI chat turn is a throwaway Session: interface mints a fresh session_id per typed line; no transcript; continuity = memory recall (two or three bus requests, 0.25 s, bag-of-words), which the code itself documents losing 'falcon/sparrow' and giving two different birthdays two turns apart.

- **current:** A CLI chat turn is a throwaway Session: interface mints a fresh session_id per typed line; no transcript; continuity = memory recall (two or three bus requests, 0.25 s, bag-of-words), which the code itself documents losing 'falcon/sparrow' and giving two different birthdays two turns apart.
- **future pattern:** One persistent, resumable session per (channel, person) with an append-only typed transcript that is compacted, not discarded; memory recall augments the transcript instead of standing in for it.
- **gap:** Multi-turn coherence, corrections, 'what did I just say', and resumption after restart all depend on this. It is also why chat cannot be compacted (nothing to compact) and why the per-turn recall must be so aggressive.

##### 3. Prompt assembly is split across two subsystems (cognition/assembler.py: constitution, persona voice, self summary, user profile, task_rules; orchestration/context.py: memory block, task, carried notes, messages), each block fetched by a bus request with a 0.25 s timeout, silently omitted on timeout, with the ordering unstable per turn.

- **current:** Prompt assembly is split across two subsystems (cognition/assembler.py: constitution, persona voice, self summary, user profile, task_rules; orchestration/context.py: memory block, task, carried notes, messages), each block fetched by a bus request with a 0.25 s timeout, silently omitted on timeout, with the ordering unstable per turn.
- **future pattern:** One ContextBuilder inside the loop with an explicit token budget per section, a stable prefix order (constitution -> persona -> self summary -> tools -> skills catalog -> transcript) for provider prompt caching, and per-turn variable material (memory recall) placed inside the latest user turn so the cached prefix survives.
- **gap:** Today the prompt silently changes shape under load (the memory block vanishing is 'the normal case, not an edge' per the code) and no prefix is cacheable, so every call pays full input price and latency.

##### 4. Memory: hashed bag-of-words embeddings (sha256 token buckets, 256 dims) because the real embedder costs 24.9 s on first call; an inverted index made hashing recall fast (21 ms at 10k), but relevance is vocabulary overlap; working memory exists and is never fed; semantic memory is free-text distillations, with contradiction handling by header prose ('later lines win').

- **current:** Memory: hashed bag-of-words embeddings (sha256 token buckets, 256 dims) because the real embedder costs 24.9 s on first call; an inverted index made hashing recall fast (21 ms at 10k), but relevance is vocabulary overlap; working memory exists and is never fed; semantic memory is free-text distillations, with contradiction handling by header prose ('later lines win').
- **future pattern:** Tiered memory: working (the transcript), episodic (turn records with real dense embeddings in a local index), semantic (a fact store with explicit supersession chains per person/subject/attribute), procedural (skills); hybrid retrieval (BM25 + dense, reciprocal-rank fusion, recency/person/confidence rerank); retrieval also exposed to the model as a tool for agentic recall.
- **gap:** Recall quality is the ceiling on 'knows the family across months'. A correction should win by data structure (superseded_by), not by asking the model to notice which line is later.

##### 5. One action per step, except a batch of read-only markers; tool results bounded at 8,000 chars by a class constant; compaction triggered by step count (reground every N) and only for non-chat; Cognition's five-layer compaction pipeline operates on flat message dicts with no turn structure.

- **current:** One action per step, except a batch of read-only markers; tool results bounded at 8,000 chars by a class constant; compaction triggered by step count (reground every N) and only for non-chat; Cognition's five-layer compaction pipeline operates on flat message dicts with no turn structure.
- **future pattern:** A step is one model turn that may contain N tool_use blocks (reads run concurrently, writes serialize in order); compaction driven by measured tokens against the model's window: first age out old tool_result content into re-fetchable stubs, then a structured summary of everything but the protected prefix and the last M turns; applies to every session kind.
- **gap:** Long tasks spend steps on things that should be one turn, and hit context_too_large before the reground fires; chat never compacts at all.

##### 6. No streaming anywhere: providers return whole completions (Together via to_thread), Voice waits 1.3-9.5 s for the full reply before planning TTS; measured full response 4-17 s.

- **current:** No streaming anywhere: providers return whole completions (Together via to_thread), Voice waits 1.3-9.5 s for the full reply before planning TTS; measured full response 4-17 s.
- **future pattern:** Provider stream() yielding text and tool_use deltas; the harness publishes deltas to surfaces; Voice's existing StreamingSynthesiser/StreamingPlayer consume sentence-sized chunks as they arrive; a tool_use start triggers a short spoken filler.
- **gap:** Time-to-first-audio is the dominant felt latency for the family, and the last stage of the voice pipeline is already built for streaming input it never receives.

##### 7. Growth is three subsystems: Learning (its PatchPipeline is unreachable: no publisher for learn.pipeline.run, and draft_candidate is not a registered tool; health reports degraded), Reflection (observer only, drafts skills to a directory), Curiosity (idle-tick exploration). Self Model is in-memory per process, capabilities['tools'] never written.

- **current:** Growth is three subsystems: Learning (its PatchPipeline is unreachable: no publisher for learn.pipeline.run, and draft_candidate is not a registered tool; health reports degraded), Reflection (observer only, drafts skills to a directory), Curiosity (idle-tick exploration). Self Model is in-memory per process, capabilities['tools'] never written.
- **future pattern:** One eval-driven improvement loop: review traces and benchmark failures -> produce skills, memory facts, and config/prompt proposals -> land them through the same gated loop (worktree + suite + evals) -> update a Self Model that is a fold of ledger streams (tool registry, benchmark history, outcomes).
- **gap:** Self-improvement currently happens only when the creator types `improve`; the designed autonomous path does not run. Merging the three into one service with one output type (a proposal through the harness) is what makes the growth layer real.

##### 8. Regex police in session.py as the honesty mechanism: each a live-caught incident turned into a heuristic, each with a once-per-session correction turn, all specific to marker-era failure modes.

- **current:** Regex police in session.py as the honesty mechanism: each a live-caught incident turned into a heuristic, each with a once-per-session correction turn, all specific to marker-era failure modes.
- **future pattern:** One generic Stop hook: 'the assistant's final text claims an effect and this turn has no tool_result from a mutating tool' -> bounce once with the list of tools that could do it; plus Verification's trajectory check for tasks.
- **gap:** The heuristics are unbounded in number and cost a correction turn each; with structured tool use most of their trigger conditions cannot occur.

##### 9. Cognition is a bus service that assembles prompts, parses markers, compacts and routes; Orchestration is a bus service that runs the loop; the loop talks to its own brain by bus request with a think timeout.

- **current:** Cognition is a bus service that assembles prompts, parses markers, compacts and routes; Orchestration is a bus service that runs the loop; the loop talks to its own brain by bus request with a think timeout.
- **future pattern:** The loop owns context, parsing and compaction (they are loop concerns); the LLM layer is a library gateway (routing, budgets, streaming, dialects, token counting) injected into the loop; the bus carries effects, events, perception and surfaces, not the loop's inner monologue.
- **gap:** Today a think is a bus round-trip carrying the whole prompt as a payload (and every message gets a trace stream); the 300 s handler timeout was once every task's wall budget. The bus is the right instrument for effects and events, the wrong one for a synchronous, streaming, large-payload call inside one process.

##### 10. interface/dispatch.py: 2,234 lines of command dispatch, a separate command language from the model's tools, bridged by a `sim_command` tool that routes model text back into CLI dispatch.

- **current:** interface/dispatch.py: 2,234 lines of command dispatch, a separate command language from the model's tools, bridged by a `sim_command` tool that routes model text back into CLI dispatch.
- **future pattern:** Slash commands are skills or tools the same loop uses; the TUI renders the session stream (the same typed turns the ledger holds); operator commands stay as a thin shell.
- **gap:** Two vocabularies drift; the model reaches operator functions through a string tunnel with no schema.

##### 11. Tests: 447 files / 90k lines, asserting code shape; the project's own review says they missed every real blocker; real signal came from watched single-task trials and observer waves.

- **current:** Tests: 447 files / 90k lines, asserting code shape; the project's own review says they missed every real blocker; real signal came from watched single-task trials and observer waves.
- **future pattern:** Eval-driven development: a small scenario suite (recorded provider fixtures for determinism, a live-gated tier for real models) plus the benchmark unit as the merge gate; unit tests only where the logic is pure.
- **gap:** The migration below cannot be done safely with the current gate; the trial suite must be promoted first.


### target architecture

**one paragraph:** Keep the substrate (Bus, Ledger, Kernel, Contracts) and the safety path (Guardian, Execution with its token verifier, Verification, worktree landing, simloader) exactly as they are. Collapse the thinking path -- orchestration (session, context, profiles, scaffolds, tools mapping, progress, resume, worker) plus cognition's assembler, parser, compaction and the marker protocol -- into one `agent/` package: a single Harness loop over a typed, ledger-persisted turn transcript, native JSON-schema tools rendered per provider dialect, parallel tool_use blocks (reads concurrent, writes serialized), streaming deltas to surfaces, token-pressure compaction with a protected prefix, hooks (PreToolUse = Guardian proposal, mandatory; PostToolUse; Stop; PreCompact; SessionStart), declarative agent definitions as permission modes, and a `Task` built-in for isolated sub-agents. Cognition shrinks to an `llm/` gateway (providers, router, budgets, tiers, streaming, tokens, cache-aware ordering) injected into the loop by the Kernel through a contracts protocol, the same way bus and ledger clients are. Memory becomes four real tiers with a dense index and a fact store with supersession. Learning, Reflection and Curiosity merge into one `improve/` service whose only output is proposals through the same harness (skills, memory facts, config/prompt PRs), scored by evals. The Bus remains the fabric for effects (action.*), tool registry, task lifecycle, perception, surfaces, growth events, system control and multi-process mode -- not for prompt-block RPC.

#### modules

###### 1. agent (the Harness)

- **name:** agent (the Harness)
- **from:** merge of orchestration/{session,context,profiles,scaffolds,tools,progress,resume,worker,claims} + cognition/{assembler,parser,compaction} + the marker protocol (kept as a fallback dialect)
- **responsibility:** Run one loop for every session kind (chat, voice-chat, task, project, sub-agent): build context, stream the model, execute tool_use blocks through Guardian, append typed turns to the session stream, compact under token pressure, delegate, stop; resume any session from its stream.
- **key algorithms or methods:**
  - Turn model: Session{id, agent, channel, person, parent_id, depth, budget{turns, tokens, cost_usd, wall_s}, state}; Turn{seq, role: system|user|assistant|tool, blocks[], ts, meta{provider, model, in_tokens, out_tokens, cost}}; Block = Text | ToolUse{id, name, input} | ToolResult{tool_use_id, content, is_error, ref, bytes_total} | Image{ref}. Persisted as ledger stream session:<id> with events session.turn.appended / session.compacted{summary, dropped_seq_range} / session.snapshot; state = fold of the stream.
  - Loop: while not stopped: check pause/cancel -> ContextBuilder.build(session) -> llm.stream(...) -> collect assistant turn -> if no tool_use: Stop hooks (claimed-effect check, Verification for task agents with bounded revise) -> done; else partition tool_use blocks: read-only set run concurrently via asyncio.gather over propose_and_await, mutating list run sequentially in block order stopping at first is_error; append ONE tool turn with N ToolResult blocks in the original order; budgets checked in turns, tokens, USD and wall-clock; last-turn and winding-down hints kept from today's assembler.
  - PreToolUse hook (mandatory, not configurable): ToolUse -> action.proposed{action_id = tool_use.id, tool, args = input (schema-validated), scope, reversibility, session_id, agent} -> await action.approved|denied|needs_human -> Execution -> action.result -> ToolResult. Denial becomes ToolResult{is_error: true, content: 'denied by <rule>: <reason>'} so the model adapts. needs_human parks the session (state = awaiting_human, event on the stream) and resumes on ui reply. Built-in tools with no external effect (Task, use_skill, memory_search, recall_result, plan/todo) bypass Guardian exactly as delegate/use_skill do today, and are the only ones that may.
  - ToolRegistryView: ToolSpec{name, description, input_schema (JSON Schema object), reversibility, network, cost_class, source: execution|mcp:<server>|builtin, tags} folded from tool.registered (replayed at boot, as service.py already does); jsonschema validation before proposing (stdlib-only validator for the subset used, or the optional jsonschema package); unknown name -> ToolResult{is_error}. Marker dialect retained only for providers whose capability flag says supports_tools = false (floor, Claude CLI wrapper, tool-less local models).
  - Agent definitions: agents/<name>.md, frontmatter {tools: allowlist with globs like 'mcp:*' and 'cam_*', model_tier, max_turns, max_cost_usd, max_wall_s, max_parallel_tools, verify, isolation: fresh|fork, compaction: {age_results_at: 0.7, summarize_at: 0.85, keep_recent_turns: 6}, channels}, body = the scaffold text. Guardian-protected directory. Replaces profiles.py + scaffolds.py; today's CHAT/PATCH/RESEARCH/SKILL/VOICE_CHAT become five files.
  - ContextBuilder: fixed prefix order for prompt caching -- constitution, persona voice, self summary, user profile, agent body, tool specs, skills catalog -- then the compacted transcript; per-turn variable material (memory recall block, environment notices, time) injected as a block at the head of the latest user turn, never in the prefix. Section token budgets, explicit; unavailable sections rendered as an honest note (kept from context.py). Reads persona/self/memory through injected read protocols (in-process in single mode), not 0.25 s bus RPCs.
  - Compactor: measure tokens (provider count when available, estimate otherwise) against the model window. Layer A (age_results_at): ToolResult content older than keep_recent_turns replaced by a stub '[result of <tool> <args-preview>, <N> chars, ref session:<id>#<seq>]' that the model can re-fetch with recall_result. Layer B (summarize_at): today's ProgressNote (goal/done/learned/next/open questions) written by a cheap purpose over everything except the protected prefix and the last M turns; chat uses a 'conversation so far' flavour with facts-about-people preserved. PreCompact hook lets the agent definition add 'preserve X'. session.compacted event; the ledger keeps everything.
  - Delegation: built-in Task{agent, brief, isolation: fresh|fork(last K turns), budget} -> child Session on its own session stream, run in-process (never via the task queue, so a one-worker deployment cannot deadlock), depth <= max_depth, concurrency <= max_children; returns final text bounded as a ToolResult; tier escalation on helper failure kept. Projects = a parent session whose plan step spawns children and awaits them; Planning's DAG scheduler orders them.
  - Hooks: SessionStart (resume from stream; carried attempt notes), UserPromptSubmit (memory recall injection; person/channel tagging), PreToolUse (Guardian; budget; pause), PostToolUse (side-effect record: uncommitted files, created paths, write-watch), Stop (claimed-effect-without-tool bounce once; Verification for verify: true agents with bounded revise), PreCompact. Implemented as an ordered list per agent definition; the Guardian hook cannot be removed.
  - Streaming: llm.stream yields Delta{text | tool_use_start{id,name} | tool_use_input_json | stop{reason}}; the harness publishes session.delta on the bus (bus-only, not ledgered) for the TUI, HTTP feed and Voice; the completed turn is what reaches the ledger. Cancellation on system.stop drops the stream and records a truncated turn honestly.
  - Budgets and resume: turn/token/USD/wall-clock per attempt from the agent definition or the task; resume.py logic kept (crash = continue, retry = new budget with carried note), now reading the session stream instead of task.step summaries.
- **interfaces:** Consumes: task.available (claim), percept.text.received / voice turns (open or continue a session), action.approved|denied|needs_human|result (by action_id), tool.registered, system.pause|stop|resume, ui.reply. Produces: action.proposed, task.started|step|progress|completed|failed|blocked, turn.completed, session.delta (bus-only), memory.store. Injected protocols from Kernel: Llm (stream/complete/count_tokens/tiers), MemoryReader, SelfModelReader, PersonaReader, Ledger, Bus. Unlocks: BFCL and BFCL-parallel as a direct measure; steps per task down; correction turns per 100 turns to ~0; resume after kill -9 mid-task; TTFT visible in the TUI.

###### 2. llm (provider gateway)

- **name:** llm (provider gateway)
- **from:** cognition minus assembler/parser/compaction: providers/, router.py, budget.py, tokens.py, api.py
- **responsibility:** Turn (system, messages, tools, budget, purpose, tier) into a streamed model response in the right provider dialect, with routing, failover, budgets and cost accounting; no prompt assembly, no parsing of prose.
- **key algorithms or methods:**
  - Provider protocol: capabilities{supports_tools, supports_streaming, supports_images, context_window, cache_prefix} + stream(system, messages, tools, max_tokens, timeout, reasoning_effort) -> AsyncIterator[Delta]; complete() derived from stream.
  - Dialect adapters: Together (OpenAI-compatible chat completions with tools/tool_choice and streaming; confident the API supports it, per-model support must be measured -- flag: the current low-cost model's tool-calling quality is unknown until benchmarked), Ollama (chat API tools for tool-capable models), Gemini (function declarations), a direct Anthropic Messages API adapter when a key is configured (tool_use/tool_result blocks, streaming, prompt caching); the Claude Code CLI wrapper stays text-only and is marked supports_tools = false.
  - Router kept: ordered failover, shared deadline slices, cooldown, truncation retry, billable-on-failure, purpose filters; add tier selection by task class (chat/default, code/strong, verdict/cheap) with escalation rules already present; per-purpose reasoning_effort.
  - Token counting per provider where offered, estimate otherwise; cache-aware: report cached_input_tokens (field exists) and expose prefix-stability hints to the ContextBuilder.
  - Floor provider kept as the deterministic last resort, now answering with an honest text-only turn and never a tool_use.
- **interfaces:** A library injected into agent/ and improve/ via contracts.protocols.Llm; also still answers cognition.think on the bus for other subsystems (Planning decomposer, Memory consolidation, Verification checklist) until they are moved to the injected protocol. Produces cognition.provider.status, budget metrics. Unlocks: tokens/$ per purpose with cache hits; TTFT.

###### 3. memory

- **name:** memory
- **from:** keep package; rebuild store internals (store.py, recall.py, embed.py, consolidation.py)
- **responsibility:** Four tiers -- working (the session transcript, owned by agent/), episodic (turn records), semantic (facts with supersession), procedural (skills) -- with hybrid retrieval and a model-callable search tool.
- **key algorithms or methods:**
  - Embeddings: a small sentence-embedding model (MiniLM-class, ~384 dims) loaded in a background thread at boot; hashing remains the floor until it is warm and forever when the optional dependency is absent; every record stores which embedder produced its vector (already the convention).
  - Index: a numpy matrix per kind with brute-force cosine (sub-10 ms to ~100k records); an ANN library only if the store passes ~200k; BM25 over a stdlib inverted index; hybrid via reciprocal rank fusion; rerank by recency half-life, person tag, confidence, contradiction penalty (all existing signals); optional cheap-model rerank of the top 20 for chat.
  - Fact store (semantic tier): Fact{id, person, subject, attribute, value, ts, source_ref (session:<id>#<seq>), confidence, superseded_by}; extraction at turn end by a cheap purpose ('extract durable facts about people, places, devices, preferences'); supersession by key (person, subject, attribute); recall renders 'X (was Y until <date>)' so a correction wins by structure.
  - Consolidation on system.tick.sleep kept: episodic -> facts + skill candidates; the live-caught 'answered instead of summarised' guard kept.
  - Agentic recall: memory_search{query, kinds, person, since} exposed as a built-in tool so the model can look again when the injected block is not enough.
- **interfaces:** Consumes turn.completed, memory.store/forget; answers MemoryReader (in-process) and memory.retrieve (bus). Produces memory.stored/consolidated/contradiction.flagged. Unlocks: recall@k on a scripted 30-turn household eval; the 'falcon/sparrow' and 'birthday correction' cases pass by construction.

###### 4. guardian

- **name:** guardian
- **from:** keep
- **responsibility:** Sole approver of every effect; posture; charter; human gate.
- **key algorithms or methods:**
  - Rules now read typed args (input validated against the tool's schema) instead of a raw 'argument' string: ProtectedRule and ScopeRule get exact paths, DenylistRule gets exact code fields.
  - Permission posture per agent definition (plan/read-only, guarded, auto) folded into ModeRule; loosening remains a human config change.
  - Protected subjects extended: agents/ definitions, agent/hooks/, evals/ gate config.
- **interfaces:** Unchanged topics. Unlocks: denial precision (fewer false denials on multi-field tools).

###### 5. execution

- **name:** execution
- **from:** keep
- **responsibility:** The hands: tools, sandboxes, worktrees, MCP, domains.
- **key algorithms or methods:**
  - tool.registered carries the full ToolSpec (description, input_schema, reversibility, network, cost_class) -- the fields already exist on each Tool class.
  - MCP proxies pass input_schema through unflattened; servers configured via propose_mcp_server remain Guardian-gated; MCP is the integration standard for new external capability, preferred over hand-written tools.
  - Browser/computer-use: browse_page grows into a snapshot-act loop (accessibility-tree snapshot, act by element id) used by a `browser` sub-agent definition; Home Assistant connection when configured.
- **interfaces:** Unchanged topics; ToolSpec richer. Unlocks: MCP tools callable 100%; per-tool success rate as the module's handle.

###### 6. verification

- **name:** verification
- **from:** keep
- **responsibility:** Independent critic: mechanical checks, checklist, trajectory; plan review.
- **key algorithms or methods:**
  - Invoked as the Stop hook of verify: true agents with a bounded revise loop (feedback -> one more turn, max_revisions).
  - New trajectory check over the session stream: every claimed effect in the final text has a matching successful ToolResult from a mutating tool; replaces claimed_to_commit / claimed_tv_act / promised_behaviour.
  - Also runnable as a `verify` sub-agent with fresh context for high-rigor tasks.
- **interfaces:** Unchanged topics. Unlocks: false-completion rate on the trial suite.

###### 7. planning

- **name:** planning
- **from:** keep, slimmed
- **responsibility:** Goals -> projects -> task DAG; plan mode; re-grounding; rollups; leases.
- **key algorithms or methods:**
  - Decomposition by a `planner` sub-agent that returns a typed Plan artifact (JSON: steps with subject, acceptance criteria, depends_on, agent) validated by schema, replacing the numbered-list regex parse.
  - Project sessions wait on children (parent_id/depends_on honoured in intake; DAG scheduler orders children; rollup on completion).
  - Re-grounding kept as the same purpose, now reading the parent session's progress note.
- **interfaces:** Unchanged topics plus plan artifact schema. Unlocks: decomposition depth > 0 actually producing children that run.

###### 8. improve (growth loop)

- **name:** improve (growth loop)
- **from:** merge of learning + reflection + curiosity
- **responsibility:** Turn evidence (traces, outcomes, benchmark runs, denials, drift) into proposals through the harness: skills, memory facts, config/prompt changes, exploration tasks; maintain competence.
- **key algorithms or methods:**
  - Nightly loop on system.tick.sleep: run the eval suite and benchmarks (budget-capped), mine failed traces (reflection's pattern/denial miners kept), draft skills with a `skill-writer` sub-agent (distillation.py kept), extract facts, propose config/prompt tweaks as PRs via the worktree path.
  - Promotion rule: a skill or prompt change is kept only if the relevant eval improves and none regress (A/B on the trial suite); otherwise it is filed as a candidate with its evidence.
  - Curiosity's drive-weighted sampler over the capability map becomes the scheduler for idle-time improvement tasks (diversity by construction kept); competence table now fed by benchmark deltas and task outcomes together.
  - Delete PatchPipeline and the unreachable learn.pipeline.run path; `improve <path> <desc>` already runs through the agent loop.
- **interfaces:** Consumes task.*, action.*, verify.result, benchmark.*, system.tick.sleep; produces action.proposed (through the harness as tasks), learn.competence.updated, reflect.*, curiosity.candidate, memory.store. Unlocks: benchmark trend per week; skills-that-helped ratio.

###### 9. worldmodel (Self Model)

- **name:** worldmodel (Self Model)
- **from:** keep; make it a fold
- **responsibility:** Environment facets and the Self Model as a projection of ledger streams.
- **key algorithms or methods:**
  - Self Model = fold of tool.registered (capabilities.tools finally written), skills catalog, learn.competence.updated, benchmark history, learn.self_patch.*, system.started; replayed on boot; rendered summary cached and re-rendered on change, served to ContextBuilder in-process.
  - Open questions wired from reflection's critique output (the one-line contracts addition the README names).
- **interfaces:** Unchanged. Unlocks: 'what can you do' answered from data; staleness per facet.

###### 10. interface

- **name:** interface
- **from:** keep; slim dispatch
- **responsibility:** CLI/TUI/HTTP/chat channels rendering the session stream.
- **key algorithms or methods:**
  - TUI renders session.delta and session turns (tool_use -> tree line, tool_result -> collapsed block) -- the same objects the ledger holds; no per-line session minting.
  - Operator commands that the model should reach become skills or tools with schemas; sim_command shrinks to the operator-only set (restart, pause, mode).
- **interfaces:** Consumes session.delta, turn.completed, ui.*; produces percept.text.received, ui.reply. Unlocks: dispatch.py line count down; the model reaches every operator function through a schema.

###### 11. voice

- **name:** voice
- **from:** keep
- **responsibility:** Mic -> words -> session turn; assistant deltas -> speech.
- **key algorithms or methods:**
  - Consume session.delta text: sentence chunker feeding the existing StreamingSynthesiser/StreamingPlayer; on tool_use_start of a slow-class tool, speak a short filler; barge-in cancels the stream.
  - Per-turn facts stay on the turn record (the 2026-09-18 lesson).
- **interfaces:** Unchanged plus session.delta. Unlocks: first_audio measured from speech_end drops toward STT + TTFT.

###### 12. substrate: bus, ledger, kernel, contracts

- **name:** substrate: bus, ledger, kernel, contracts
- **from:** keep
- **responsibility:** Fabric, truth, composition, agreements.
- **key algorithms or methods:**
  - Contracts gain: Turn/Block/ToolSpec/Plan/Fact schemas; protocols Llm, MemoryReader, SelfModelReader, PersonaReader.
  - Kernel injects those protocol implementations into agent/ (single mode: in-process objects; local-multi/aws: bus-backed adapters with real timeouts) exactly as it injects bus/ledger clients -- the boundary test stays green.
  - Ledger: session streams append per turn (not per block); trace streams per session not per message; batched fsync.
- **interfaces:** Unchanged. Unlocks: stream count and disk growth as the ledger's handle.


#### merges

- orchestration + cognition/{assembler,parser,compaction} + profiles + scaffolds + context.py -> agent/ (one loop, one ContextBuilder, one Compactor, one hook list)
- learning + reflection + curiosity -> improve/ (one growth loop whose only output type is a proposal through the harness)
- profiles.py + scaffolds.py -> agents/<name>.md definitions (loader stays in agent/)
- the five session.py regex police + Verification's claim checks -> one Stop hook + one trajectory check
- interface dispatch commands that the model needs -> skills/tools with schemas (sim_command shrinks to operator-only)

#### additions

- Native tool protocol: ToolSpec across the bus, per-provider dialect rendering, JSON-schema validation, tool_use/tool_result turns, parallel blocks
- session:<id> ledger stream with typed turns; persistent sessions per (channel, person); resume from stream
- Streaming provider interface and session.delta surface feed; Voice sentence chunker on deltas
- Direct Anthropic Messages API adapter (when a key exists) as a second native-tool provider; capability flags per provider
- Hooks list per agent definition (Guardian PreToolUse mandatory)
- Built-in tools: Task, memory_search, recall_result, plan/todo
- Memory: dense embedder at boot in a thread, numpy index, BM25, RRF, Fact store with supersession
- Eval suite (evals/): recorded-fixture scenario evals (household 30-turn recall, tool use, long task resume) + benchmark unit as the merge gate
- Planner sub-agent with a typed Plan artifact schema
- pyproject.toml + ruff (cheap, and the migration moves many files)

#### deletions or freezes

- Marker protocol: frozen as a fallback dialect for supports_tools = false providers; no new markers, no new _CODE_BEARING entries
- session.py regex police family: deleted after Stage 5, replaced by the Stop hook and trajectory check
- Learning PatchPipeline / learn.pipeline.run / draft_candidate references: deleted (unreachable today)
- Per-line throwaway chat sessions: deleted
- Double prompt assembly (cognition/assembler.py + orchestration/context.py): one ContextBuilder
- Bus RPC for prompt blocks at 0.25 s timeouts: replaced by injected read protocols in single-process mode
- src/ (v1): deleted from the tree, kept in git history and a tag
- Step-count-triggered reground: replaced by token-pressure compaction


### capability programs

##### 1. Reasoning

- **capability:** Reasoning
- **current state:** One think per step at low reasoning effort on the cheapest Together model; tool calls parsed from prose (a parse tax on every step); no plan/act/critique separation inside a task except Verification at the end; tier escalation only on attempt N or helper failure; BFCL/GAIA/SWE-bench scored but not gating anything.
- **method:** (1) Native structured tool use removes the parse tax and the correction turns. (2) Router picks tier and reasoning effort by task class at the first call (chat: default/low; code/patch: strong or extended reasoning; verdicts: cheap), with today's escalation kept. (3) Plan-then-act for task agents: a `planner` sub-agent writes a typed plan with acceptance criteria; the executing agent keeps a plan/todo block in the protected prefix and updates it with the built-in plan tool. (4) Critic loop: Verification as the Stop hook with max_revisions bounded revise; for high-rigor tasks a fresh-context `verify` sub-agent reviews the diff and trajectory. (5) Self-consistency only for verdict purposes (3 cheap samples, majority), never for drafts.
- **how to measure:** BFCL and BFCL-parallel (tool use), GAIA L1/L2 (multi-step reasoning), SWE-bench Verified subset resolved rate; per-tool success rate; correction turns per 100 turns; cost per resolved case.
- **first increment:** Ship ToolSpec (description + input_schema) to the model and native function calling on Together behind a provider capability flag; run BFCL and the trial suite before/after on the same model; record in docs/findings/.

##### 2. Long tasks

- **capability:** Long tasks
- **current state:** Budget = steps per attempt (cap 200), retries carry a mechanical note of at most 6,000 chars, reground every N steps for non-chat only, tool results cut at 8,000 chars by constant, no wall-clock budget, context_too_large reported as 'no real provider' until recently, projects mark themselves complete when children are created and never wait; resume distinguishes crash vs retry (good); worktree landing works.
- **method:** Session transcript as a ledger stream (checkpoint = every turn, resume = fold); budgets in turns + tokens + USD + wall-clock; compaction by measured token pressure (age tool results into re-fetchable stubs at 70% of the window, structured progress note at 85%, protected prefix never touched); projects as parent sessions that spawn child sub-agents per plan step and await them (DAG order), each child fresh-context; long runs report through notify and park on needs_human without losing state; lease heartbeat kept.
- **how to measure:** SWE-bench Verified resolved rate at >= 50 turns; fraction of tasks finished within one attempt; resume-after-kill success (kill -9 mid-task, must continue without redoing steps); context tokens per turn over a 100-turn run (should plateau); projects that produce and complete children (today: zero).
- **first increment:** Persistent sessions with a session:<id> stream for chat and tasks (interface stops minting per-line ids), then switch reground to token pressure with tool-result aging; verify with a scripted 60-turn task under tools/trial.py.

##### 3. Environment interaction

- **capability:** Environment interaction
- **current state:** 98 tools with real JSON schemas that the model never sees; MCP client works but flattens schemas to one property or leaves the tool uncallable; browse_page exists; cameras via RTSP->ffmpeg->HLS; Cast/Android TV; Home Assistant not configured; perception is text only (camera and TV events exist on the bus but never enter a session).
- **method:** ToolSpec passthrough with schema validation; MCP as the default way to add capability (full schemas, Guardian-gated like everything else); a `browser` sub-agent definition over a snapshot-act browse loop (accessibility tree snapshot, act by element id, bounded steps); Home Assistant connection when the creator configures it; environment events (camera.event, tv.state, calendar, reminders) delivered into the relevant session as user-role environment turns so the agent can act on them under the same gate.
- **how to measure:** Per-tool success rate and p95 latency (module handle); MCP tools callable %; BFCL-parallel; a scripted household eval (lights, TV, reminders, mail lookup, camera snapshot) end-to-end completion rate; browser task suite (login-free sites) completion.
- **first increment:** Publish full ToolSpec on tool.registered and render it to the model; pass MCP schemas through unflattened; measure how many of the 98 + MCP tools are callable with correct arguments on the first try (today: every multi-field tool depends on a hand-written hint).

##### 4. User interaction

- **capability:** User interaction
- **current state:** Throwaway chat sessions; continuity by bag-of-words recall with silent failure under load; no streaming (voice response 4-17 s); persona and self summary fetched by RPC every think; correction turns from regex police; person-scoped memory only on voice turns.
- **method:** One persistent session per (channel, person) with compaction; streaming deltas to the TUI and to Voice's sentence chunker (first audio after the first sentence, spoken filler on slow tool_use); UserPromptSubmit hook injects hybrid memory recall inside the latest user turn (prefix stays cached); memory_search tool for agentic recall; Fact store with supersession so corrections win by structure; persona/self summary read in-process and cached; proactive shares and notifications appended to the same session as assistant turns so they have context.
- **how to measure:** Time-to-first-token and first_audio (Voice already logs these); a 30-turn scripted recall eval from the observer's real cases (machine names, birthday correction, per-person secrets) with recall@k and correction-wins rate; correction turns per 100 turns (police triggers -> Stop-hook bounces); user-visible latency p50/p95 per channel.
- **first increment:** Streaming think reply (Together streaming + session.delta) and Voice consuming sentence chunks; measure first_audio before/after on the same turns.

##### 5. Self-improvement

- **capability:** Self-improvement
- **current state:** Self-patch via worktree landing + gate + simloader rollback works when the creator asks; Learning's autonomous PatchPipeline is unreachable; Reflection drafts skills to a directory nobody promotes; Curiosity explores on idle ticks; Self Model is in-memory and never records tools; benchmarks exist with history but gate nothing.
- **method:** One eval-driven improve loop: nightly (budget-capped) run the eval suite and benchmarks, mine failed traces and denials, draft skills (SKILL.md) with a skill-writer sub-agent, extract durable facts, propose prompt/config/tool changes as PRs through the worktree path; promote a change only when its target eval improves and none regress (A/B on the trial suite); competence table fed by benchmark deltas and outcomes; Self Model as a fold of the ledger; Guardian protects the harness, agent definitions, hooks and eval gate so the loop can never loosen its own gate.
- **how to measure:** Benchmark trend per week per model; skills promoted vs drafted, and skills that measurably helped; self-patch land rate and rollback count from simloader; Self Model staleness (tools listed vs tools registered).
- **first increment:** Wire reflection's distillation output into simorgh_skills with an A/B on the trial suite (skill on vs off) and promote only on improvement; delete PatchPipeline; write capabilities.tools from tool.registered.


### migration path

##### 1. 0. Promote the gate

- **stage:** 0. Promote the gate
- **weeks:** 1
- **does:** Make tools/trial_suite.py + the benchmark unit + a recorded-fixture scenario eval (household 30-turn recall, one tool-use scenario, one long-task resume) the merge gate for every stage below; add pyproject.toml + ruff; delete src/ (tag it).
- **unlocks:** A gate that catches loop breakage; a clean tree for many file moves.
- **risk:** Low. Fixture recording needs one real provider run per scenario (cost cents).

##### 2. 1. Schemas to the model

- **stage:** 1. Schemas to the model
- **weeks:** 1
- **does:** tool.registered carries full ToolSpec (fields already exist on each Tool); orchestration renders name + description + argument shape into the prompt; MCP schemas unflattened in the registry view. No protocol change yet.
- **unlocks:** Immediate first-try argument accuracy on multi-field tools; BFCL baseline on the current marker protocol.
- **risk:** Prompt grows (98 tools); mitigate by per-agent allowlists (already exist) and a short-form rendering.

##### 3. 2. Native tool use behind a capability flag

- **stage:** 2. Native tool use behind a capability flag
- **weeks:** 2
- **does:** Provider protocol gains capabilities + tool dialects; Together (OpenAI-compatible functions) fills ProviderResponse.tool_calls; session loop consumes tool_calls with JSON-schema validation and returns tool_result turns keyed by id; markers remain for supports_tools = false providers; Guardian path unchanged (action_id = tool_use id). Add the direct Anthropic API adapter if a key is configured.
- **unlocks:** BFCL/trial-suite delta; the regex police become mostly unreachable; multi-field and MCP tools callable.
- **risk:** The cheap Together model's tool-calling quality is unmeasured; some models emit malformed JSON. Keep the marker fallback per provider and compare per model on BFCL before flipping the default.

##### 4. 3. Session stream and persistent sessions

- **stage:** 3. Session stream and persistent sessions
- **weeks:** 2
- **does:** contracts: Turn/Block schemas; session:<id> ledger stream; agent loop appends turns; interface keeps one session per (channel, person); resume.py reads the stream; memory recall stays injected.
- **unlocks:** Multi-turn continuity, resume after restart, evals from real transcripts, compaction has something to compact in chat.
- **risk:** Ledger growth per turn; mitigate with per-turn (not per-block) appends, snapshots, and trace streams per session.

##### 5. 4. agent/ and llm/ packages

- **stage:** 4. agent/ and llm/ packages
- **weeks:** 2
- **does:** Pure moves with shims: orchestration + cognition/{assembler,parser,compaction} + profiles/scaffolds -> agent/; providers/router/budget/tokens -> llm/; one ContextBuilder with fixed prefix order; Kernel injects Llm/MemoryReader/SelfModelReader/PersonaReader protocols; agents/<name>.md definitions loaded, Guardian-protected.
- **unlocks:** One place to reason about the loop; prompt-cache hits; no silent block loss.
- **risk:** The largest diff of the plan under a one-person team. Land as file moves first, behaviour changes second; trial suite after each.

##### 6. 5. Streaming, parallel tool calls, hooks

- **stage:** 5. Streaming, parallel tool calls, hooks
- **weeks:** 2
- **does:** llm.stream + session.delta; Voice sentence chunker; N tool_use blocks per turn (reads concurrent, writes serialized) each proposed to Guardian; hooks list formalized; regex police replaced by one Stop hook + Verification trajectory check.
- **unlocks:** TTFT/first_audio; steps per task down; the session.py file shrinks by the police and batching special cases.
- **risk:** Streaming with tool calls has provider quirks (partial JSON); buffer tool_use input until stop; keep non-streaming path as fallback.

##### 7. 6. Token-pressure compaction and sub-agents

- **stage:** 6. Token-pressure compaction and sub-agents
- **weeks:** 2
- **does:** Compactor (result aging with recall_result stubs, then progress note) driven by measured tokens, applied to all session kinds; Task built-in over agent definitions; projects wait on in-process children via Planning's DAG; planner sub-agent with typed Plan artifact.
- **unlocks:** 100+ turn tasks without context_too_large; projects that actually produce and finish children.
- **risk:** Over-aggressive aging loses needed detail; keep_recent_turns per agent definition and the re-fetch tool bound the damage.

##### 8. 7. Memory rebuild

- **stage:** 7. Memory rebuild
- **weeks:** 3
- **does:** Dense embedder loaded in a boot thread (hashing floor), numpy index, BM25, RRF, Fact store with supersession, memory_search tool, consolidation producing facts; recall injected via UserPromptSubmit hook inside the latest user turn.
- **unlocks:** Recall eval passes by construction; person-scoped memory on every channel.
- **risk:** Optional dependency and model download on the laptop; strictly optional with the hashing floor and an explicit 'memory degraded' note.

##### 9. 8. improve/ merge and eval-driven growth

- **stage:** 8. improve/ merge and eval-driven growth
- **weeks:** 3
- **does:** Merge learning + reflection + curiosity; delete PatchPipeline; nightly capped eval/benchmark run; skill distillation with A/B promotion; Self Model as a ledger fold including tools and benchmark history; competence from deltas.
- **unlocks:** Autonomous, measured improvement that lands through the same gate as everything else.
- **risk:** Cost of nightly evals; cap by budget and run the cheap tier; never let the loop touch Guardian, agents/, hooks or the gate (protected).

##### 10. 9. Environment breadth (ongoing)

- **stage:** 9. Environment breadth (ongoing)
- **weeks:** 3
- **does:** MCP-first for new capability; browser sub-agent over a snapshot-act loop; Home Assistant when configured; environment events into sessions as environment turns; household end-to-end eval.
- **unlocks:** 'More general' measured as household task coverage.
- **risk:** Each integration is its own long tail; keep every one behind a tool with a schema and Guardian's reversibility class.


**agi honesty:** An architecture like this -- a frontier model called through a harness with tools, tiered memory, sub-agents, skills and a gated self-improvement loop -- does not become AGI by architecture. Its general intelligence is the model's; the harness decides how much of it reaches the world, how reliably, for how long, and how safely. Nothing here learns weights, and no amount of loop design gives Sim competence the model it calls does not have. What this architecture CAN deliver, and what 'more general' concretely means for a household agent: (1) coverage -- a rising fraction of the family's real goals completable end-to-end (files, web, calendar, mail, home devices, TV, cameras, code) without the creator stepping in, measured by a scripted household eval; (2) horizon -- tasks that span hours, restarts and human interruptions with the same safety profile, measured by resume and long-task evals; (3) transfer -- a skill or fact learned in one task helping on a held-out one, measured by A/B on the trial suite; (4) continuity -- knowing the family across months with corrections that stick; (5) breadth of environment -- new capability arriving as MCP servers and skills rather than subsystems. What compounds: the eval suite, the memory substrate, the skills library, the ledger of transcripts (every future eval and distillation reads it), and the model upgrades that a clean native-tool gateway makes free. What does not compound: more regex police, more bespoke command dispatch, more subsystems, and any growth mechanism not scored by an eval. The honest framing the blueprint already adopts is the right one: generality is a queryable number in the Ledger, and the Self Model should report it, including what Sim still cannot do. Two limits to state plainly: the loop cannot verify its own honesty without external checks (Verification, evals, the creator), and corrigibility must stay outside anything the improve loop can touch -- which this proposal keeps by Guardian-protecting agent definitions, hooks and the eval gate.

**biggest risk of this proposal:** That it becomes a second rewrite. One developer, ~87k lines, a 90k-line test suite that asserts shape and missed every real blocker, and a plan that moves the loop, the brain gateway and the protocol. If Stage 4 (the package consolidation) is attempted before Stage 0 (a gate that catches loop breakage) or alongside Stage 2 (protocol change), weeks of green tests can hide a broken agent, and the live checkout is what boots the family's assistant. Mitigation is procedural and non-negotiable: one stage in flight at a time, each landed through the worktree path with trial-suite and benchmark deltas recorded in docs/findings/, file moves separated from behaviour changes, and the marker protocol kept as a per-provider fallback until native tool use beats it on BFCL for the model actually in use. The secondary risk is specific: the low-cost Together model's native tool-calling quality is unmeasured and may be worse than markers; measure per model before flipping the default, and configure a second native-tool provider so the harness is not judged by one model's quirks.

