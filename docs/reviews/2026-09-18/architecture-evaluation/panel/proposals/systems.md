# propose:systems

*Workflow: panel · Phase: Propose · Agent id: `a2b4da49c83f23022` · Tool calls: 42*

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
  
  
  LENS: PRODUCTION SYSTEMS and evaluation. You build reliable long-running agent systems. Evaluate the substrate choices (bus + event-sourced ledger + per-message trace streams + fsync per append + 18 packages in one process) against the actual load and the actual need (one process, one laptop, resume after crash, auditability). Propose the substrate a 2026 expert would run: what stays event-sourced, what becomes a relational/sqlite state store with projections, how tracing should work (OpenTelemetry-style spans per turn, not a file per message), how latency budgets are enforced end to end for the voice path, how evals (task suites, replayable traces, regression benchmarks per capability) replace shape-testing, and how model routing (frontier vs. fast vs. local) should be decided per step. Include the safety tiers.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count lines of cited docs and modules |  452 docs/module-map.md 241 docs/blueprint/01-vision-and-principles.md 494 docs/blueprint/02-system-architecture.md 1942 simorgh/orchestration/session.py 327 si |
| 2 | Bash | Read the module map document | # Simorgh — Module Map and System Blocks **What this is.** One picture of every major building block, what each one owns, and how they interact — written so a s |
| 3 | Bash | Read the vision and principles blueprint | # 01 — Vision and Principles > Part of the Simorgh v2 blueprint. Read `00-README.md` first for how this > set fits together. This file states *what we are build |
| 4 | Bash | Read the system architecture blueprint | <persisted-output> Output too large (32.5KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 5 | Bash | Read middle of system architecture blueprint | \| 09 \| Guardian \| `simorgh/guardian/` \| 2 \| Constitution enforcement, permission modes, deny-first policy, denylist + adaptive immunity + classifier, protected  |
| 6 | Bash | Read end of system architecture blueprint | ``` A `system.stop` never waits on a model call: an in-flight cognition request is abandoned (its result is discarded on arrival) and the task resumes from its  |
| 7 | Bash | Locate key functions in session.py | 4:step and awaited before the next THINK (section 7: "simpler resume and 119:# inherits (`resume.py` carries uncommitted edits forward). On the last 168:def _tr |
| 8 | Bash | Read kernel registry LAYERS | """The one place subsystems are named (docs/blueprint/subsystems/03-kernel.md sections 3.4/5). `02-system-architecture.md` section 4 rule 4 permits exactly this |
| 9 | Bash | Read session.py _run loop |  async def _run(self, session: Session, *, user_text: str = "") -> Outcome: await self._append(session, topics.TASK_STARTED, {"task_id": session.task_id, "worke |
| 10 | Bash | Read session.py _think |  async def _think(self, session: Session, user_text: str, *, last_step: bool, no_tools: bool = False) -> Message \| None: steps_left = session.budget.steps_left  |
| 11 | Bash | Read orchestration context assembly | """ContextAssembler (16 section 5): gathers the memory block and the session transcript for one `cognition.think` call. The persona voice and the self summary a |
| 12 | Bash | Read cognition router | """Provider failover and selection (docs/blueprint/subsystems/04- cognition.md section 5). Ported from v1 `CognitionRouter`'s failover shape: try each candidate |
| 13 | Bash | Read cognition parser head | """Output parsing: markers, edit blocks, non-answer detection (docs/ blueprint/subsystems/04-cognition.md section 5, "Output parsing"). Ported directly from v1  |
| 14 | Bash | Locate memory store retrieval logic | 2:episodic/semantic/procedural records as one-event-per-item Ledger streams 4:lexical+embedding similarity times confidence plus a recency term, 26:from .embed  |
| 15 | Bash | Read memory retrieve body |  async def retrieve(self, *, query: str, kinds: list[str], k: int, filters: dict \| None) -> tuple[list[MemoryItem], bool]: """Rank what is remembered against `q |
| 16 | Bash | Read self model top and capability references | """The Self Model. Identity is real, loaded and hashed from `docs/SOUL.md`. As of Phase 4 Wave 2 the other sections (competence, limitations, change_history, ca |
| 17 | Bash | Read guardian rules header and pipeline structure | """The pipeline's rules, in the fixed order 09-guardian.md section 5.1 specifies. Each rule returns `Decision(kind=allow\|deny\|escalate\|abstain, ...)`; `abstain` |
| 18 | Bash | Read learning service | """`Service`: wires `OutcomeRecorder`, `CompetenceTable`, strategy suggestion, and the patch/skill pipeline runner into the real Bus/Ledger (spec section 5). Sc |
| 19 | Bash | Read reflection service top and handlers | """Reflection as a `Subsystem` (Layer 3, registry.py). Observer only -- never emits `action.proposed`, never writes `self:model` directly (only `self.observatio |
| 20 | Bash | Read curiosity service top and handlers | """`Service`: wires drives, sampling, idea/project proposal, interests, and sharing into the real `Subsystem` protocol (spec section 5). One exploration tick at |
| 21 | Bash | Read voice session top | """The spoken conversation: microphone frames in, speech out, with the floor changing hands the way it does between people. frames -> FrameVad -> TurnManager -> |
| 22 | Bash | Read ledger jsonl backend and bus tracing | """The default backend: one append-only JSONL file per stream, fsync'd per append, with v1's own durability discipline carried over verbatim from `src/memory/lo |
| 23 | Bash | Read ledger sqlite backend, projection, compaction and config | """SQLite backend (02-ledger section 4.3): one WAL-mode database, the recommended engine for `local-multi` mode -- several processes on one host append through  |
| 24 | Bash | Read reversibility rule and pipeline order, and where reversibility is assigned | class BudgetRule: name = "budget" layer = "budget" # Tools whose args plausibly cause a model call (drafting); anything # else never checks the budget table at  |
| 25 | Bash | Locate latency budgets and timeouts in the voice path | 137: tts_stall_timeout_s: float = 20.0 213: # Just above `[cognition] purposes.chat.max_seconds` (90s), so the model 216: reply_timeout_s: float = 95.0 279: # c |
| 26 | Bash | Survey benchmark package, trial harness, tools and findings | __init__.py __pycache__ api.py config.py datasets.py README.md runner.py scoring.py service.py store.py swebench.py # benchmark Measures this system against sta |
| 27 | Bash | Read post-cutover review section 4 on testing | 310:## 4. The testing-strategy change (the real lesson) ## 4. The testing-strategy change (the real lesson) Three gaps let every finding above through a 2,200-t |
| 28 | Bash | Read resume path, tools= handling in provider, and tier/purpose routing | """What a Session inherits from the `task:<id>` stream before it runs. Two different situations look alike from here -- a task whose last worker died mid-run, a |
| 29 | Bash | Read simloader gate, integration test list, bus handler timeout, ledger read path | #!/usr/bin/env python3 """The Sim loader: a bootloader for a program that edits its own source. The creator, 2026-09-07: "at start up we should have an independ |
| 30 | Bash | Confirm tools= ignored in Together adapter and read route config |  self._api_key = os.environ.get("TOGETHER_API_KEY") if api_key is None else api_key self._model = model or DEFAULT_MODEL self._base_url = base_url.rstrip("/") s |
| 31 | Bash | Find write frequency of the largest streams | (eval):1: no matches found: --include=*.py ---- 80: "idle_threshold_s": float, "idle_tick_cooldown_s": float, "sleep_every_s": float, 81: "metrics_every_s": flo |
| 32 | Bash | Read voice ask path and trial suite scoring header |  confidence=utterance.confidence) from .backchannel import is_quiet if is_quiet(reply): # Not for Sim, the model judged: nothing is said. await self._publish(to |
| 33 | Bash | Read tool argument specs and tool registry shape | """How one line of text becomes a tool call's arguments. The model writes `KB_SEARCH: flood cover` and means `{"query": "flood cover"}`. A person types `tool kb |
| 34 | Bash | Read compaction, verification and planning headers | """The graduated context-compaction pipeline (docs/blueprint/subsystems/ 04-cognition.md section 5, "Compaction pipeline"; docs/KnowledgeBase/ harness-01-claude |
| 35 | Bash | Read self-check header and findings docs | """The structural safety proof (docs/blueprint/subsystems/03-kernel.md section 5.4): before any real work is allowed, `--self-check` proves the guarded action p |
| 36 | Bash | Read observer wave header and interface chat session minting | """Pre-stage a wave of observer sandboxes before any agent starts. Every prior wave had each observer spend its own first minute doing a `shutil.copytree` of th |
| 37 | Bash | Find tool definition shape in execution | __init__.py __pycache__ capabilities.py config.py container.py doctext.py domainstatus.py energy external.py geocode.py home htmltext.py knowledge listingsource |
| 38 | Bash | Confirm cadence of the largest stream writers | 111: idle_threshold_s=float(section.get("idle_threshold_s", RuntimeConfig.idle_threshold_s)), 113: sleep_every_s=float(section.get("sleep_every_s", RuntimeConfi |
| 39 | Bash | Read bus request/reply and check for any span concept | 261: async def request(self, message: Message, *, timeout: float \| None = None) -> Message: 262- await self._ensure_inbox() 263- timeout = self._config.request_ |
| 40 | Bash | Read loader gate, execution tool timeout, and MCP support header | 66:def pytest_parallel_args() -> list[str]: 67: """`-n auto` when pytest-xdist is installed, else nothing. 284: subclass pulls whatever it can out of it (a pyte |
| 41 | Bash | Confirm tool spec fields, metrics cadence default and bus request timeout | 195:class Tool(Protocol): 197: description: str 198: read_only: bool 199: reversibility: str # read_only \| reversible \| irreversible 200: args_schema: dict ---- |
| 42 | Bash | Read Tool protocol, kernel tick defaults and bus request timeout |  side_effects: tuple[str, ...] = () metadata: dict = field(default_factory=dict) @runtime_checkable class Tool(Protocol): name: str description: str read_only:  |

## Structured reply

**lens:** PRODUCTION SYSTEMS and evaluation: substrate (bus + event-sourced ledger + per-message trace streams + fsync + 18 packages in one process) judged against the actual load (one laptop, one family, ~1.4 GB / 118k stream files after two weeks) and the actual need (one process, resume after crash, auditability, a voice path with a human waiting); tracing, latency budgets, evals as the gate, per-step model routing, and safety tiers.

### what sim got right

##### 1. The action path is structural, not policy: only Guardian subscribes to action.proposed, only Execution to action.approved, approval is an HMAC over (action_id | tool | sha256(args) | expires), Execution re-verifies, and kernel/selfcheck.py proves the wire (forged token refused, pause denies) before any work runs.

- **decision:** The action path is structural, not policy: only Guardian subscribes to action.proposed, only Execution to action.approved, approval is an HMAC over (action_id | tool | sha256(args) | expires), Execution re-verifies, and kernel/selfcheck.py proves the wire (forged token refused, pause denies) before any work runs.
- **why it matters for the future:** Every 2026 harness pattern this review recommends (native tool calling, sub-agents, MCP servers, skills, computer-use) produces MORE ways for a model to reach an effect. A chokepoint enforced by the bus topology survives all of them unchanged: a native tool_use block, an MCP tool and a sub-agent's call all still become one action.proposed. This is the one design decision that lets the rest be swapped freely.
- **keep or strengthen:** Keep verbatim. Strengthen by recording every Guardian decision (rule that fired, tier, posture) as a span attribute on the turn, so approvals/denials per tier per day is a dashboard number rather than a ledger grep.

##### 2. contracts/ is the only shared dependency, enforced by an AST boundary test; kernel/registry.py is the single composition root; the Tool protocol already carries name, description, read_only, reversibility and args_schema (contracts/protocols.py:195-200).

- **decision:** contracts/ is the only shared dependency, enforced by an AST boundary test; kernel/registry.py is the single composition root; the Tool protocol already carries name, description, read_only, reversibility and args_schema (contracts/protocols.py:195-200).
- **why it matters for the future:** Native tool calling needs a JSON schema per tool; the safety tiers below need a reversibility class per tool; MCP needs a tool descriptor. All three already exist on the Tool protocol. The migration to structured tool use is a serialization of what is there, not a redesign, and the boundary test keeps any one package replaceable without a rewrite.
- **keep or strengthen:** Keep. Strengthen by making args_schema the single source for the model-facing tool definition, the CLI `tool` command, and Guardian's subject extraction (guardian/rules.py _SUBJECT_ARG_KEYS currently guesses 'subject'/'path').

##### 3. Task state is an append-only task:<id> stream, and orchestration/resume.py distinguishes a crash (continue the same attempt, steps already spent) from a retry (fresh budget, carried notes, kept uncommitted edits).

- **decision:** Task state is an append-only task:<id> stream, and orchestration/resume.py distinguishes a crash (continue the same attempt, steps already spent) from a retry (fresh budget, carried notes, kept uncommitted edits).
- **why it matters for the future:** This is exactly the checkpoint-and-resume shape long-horizon agents need. The event stream per task is also the raw material for replayable traces: a task's stream already contains every think, every action and every result, in order.
- **keep or strengthen:** Keep as the ONLY event-sourced truth for agent state (task, action, guardian, plan, memory writes, self-model). Strengthen by adding an explicit checkpoint event after every irreversible action and by treating the stream as the replay fixture for evals (see evals package).

##### 4. Honest floors everywhere: a floor-answered benchmark case is skipped rather than scored wrong; a memory block that could not be consulted says so in the prompt (context.py MEMORY_UNAVAILABLE_NOTE); a suite that cannot be scored to the published scorer is refused (benchmark/README).

- **decision:** Honest floors everywhere: a floor-answered benchmark case is skipped rather than scored wrong; a memory block that could not be consulted says so in the prompt (context.py MEMORY_UNAVAILABLE_NOTE); a suite that cannot be scored to the published scorer is refused (benchmark/README).
- **why it matters for the future:** Eval-driven development only works if the numbers are trustworthy. Most teams discover late that outages, floor answers and partial runs contaminated their baseline; Sim already labels them. This discipline is what makes the migration below measurable at each stage.
- **keep or strengthen:** Keep. Strengthen by sizing noise explicitly (the 2026-09-15 finding: two identical L3 runs gave 3/21 and 9/25) -- every capability suite reports a confidence interval from >=3 repeats before any switch flips.

##### 5. Measurement from the ledger and the running system (tools/trial.py, tools/trial_suite.py, observer waves, benchmark unit that drives task.create through the whole bus rather than calling Cognition), plus the retrospective's own conclusion that shape tests missed every blocker.

- **decision:** Measurement from the ledger and the running system (tools/trial.py, tools/trial_suite.py, observer waves, benchmark unit that drives task.create through the whole bus rather than calling Cognition), plus the retrospective's own conclusion that shape tests missed every blocker.
- **why it matters for the future:** This is the seed of an eval harness in the 2026 sense: scripted tasks, automatic pass/fail on system behaviour, repeated until stable. The project already learned the lesson most agent teams learn a year in.
- **keep or strengthen:** Strengthen into the primary gate: trial_suite + benchmark + a household suite become `simorgh/evals`, and simloader's bless runs them (it already can with --full) rather than CORE_TESTS alone.

##### 6. simloader.py: stdlib-only bootloader that never runs the code it judges, tags sim-good-N only after an independent gate, bounded rollback, decisions printed and written where Sim reads them.

- **decision:** simloader.py: stdlib-only bootloader that never runs the code it judges, tags sim-good-N only after an independent gate, bounded rollback, decisions printed and written where Sim reads them.
- **why it matters for the future:** A self-editing agent needs an A/B image pattern with an external judge; this is it. It also gives the substrate migration a safe shape: every stage lands behind the same gate and rolls back the same way.
- **keep or strengthen:** Keep. Make the gate the eval suite (not only unit tests) and add a 'watch' phase: after handoff, the loader stays alive for N minutes and counts span-level SLO breaches (voice p95, tool error rate) as a bad image.

##### 7. Cognition's production plumbing: per-provider rolling budgets replayed from the ledger, estimated-cost check before dialling, a shared deadline split across failover candidates, transient retry, cooldown circuit breaker, truncated-retry with doubled tokens, image-capable filtering.

- **decision:** Cognition's production plumbing: per-provider rolling budgets replayed from the ledger, estimated-cost check before dialling, a shared deadline split across failover candidates, transient retry, cooldown circuit breaker, truncated-retry with doubled tokens, image-capable filtering.
- **why it matters for the future:** Per-step routing (frontier vs fast vs local) is a policy layered on exactly these primitives: candidate order, budget, deadline share. Nothing here needs replacing.
- **keep or strengthen:** Keep. Add the missing input to routing: a latency budget and a risk tier per request, so the router chooses the route rather than only the order.

##### 8. Every tool has a reversibility class (read_only | reversible | irreversible) and anything unlisted defaults to irreversible (orchestration/tools.py); Guardian's last rule gates on it; Execution's write-watching and worktree landing make code edits revertible commits.

- **decision:** Every tool has a reversibility class (read_only | reversible | irreversible) and anything unlisted defaults to irreversible (orchestration/tools.py); Guardian's last rule gates on it; Execution's write-watching and worktree landing make code edits revertible commits.
- **why it matters for the future:** Reversibility-weighted oversight is the accepted way to give an agent autonomy without giving it blast radius. The classes exist; they only need to become explicit tiers with different approval, rate limits and audit.
- **keep or strengthen:** Keep; formalise as four tiers (below) and restore the human gate for tier 3 only, which the 2026-09-07 auto-approve default currently collapses.


### where it diverges from the future

##### 1. Tool calls are parsed out of free text by a marker protocol (cognition/parser.py: one string per MARKER: line, _CODE_BEARING_MARKERS and MARKER_SPLIT_FIRST_LINE hacks for multi-arg tools). Every provider adapter accepts tools= and drops it (together.py complete() -> _complete_sync(messages, max_tokens, timeout)); cognition/service.py:358 passes tools=None to the router. session.py then polices the text with seven regex families (invented_markers, unhonoured_marker, _transcript_echo, claimed_to_commit, promised_behaviour, claimed_tv_act, claimed_to_note_a_pronunciation), each a live-caught incident turned into a heuristic.

- **current:** Tool calls are parsed out of free text by a marker protocol (cognition/parser.py: one string per MARKER: line, _CODE_BEARING_MARKERS and MARKER_SPLIT_FIRST_LINE hacks for multi-arg tools). Every provider adapter accepts tools= and drops it (together.py complete() -> _complete_sync(messages, max_tokens, timeout)); cognition/service.py:358 passes tools=None to the router. session.py then polices the text with seven regex families (invented_markers, unhonoured_marker, _transcript_echo, claimed_to_commit, promised_behaviour, claimed_tv_act, claimed_to_note_a_pronunciation), each a live-caught incident turned into a heuristic.
- **future pattern:** Native structured tool use: tools sent as JSON schemas, the model returns typed tool_use blocks with ids, results go back as tool_result blocks bound to those ids, several calls per turn are normal. The harness never parses prose for intent; a claim of an action with no tool_use block is simply text.
- **gap:** Reliability and step cost. Each police rule exists because prose and action are the same channel. With typed calls, fabricated-result echo, invented tools, first-line-only arguments and 'promised behaviour' are not failure modes of the protocol; the regexes and their 1,100 dated comments stop being load-bearing. args_schema already exists on every Tool, so this is a serializer plus adapter changes, not a redesign.

##### 2. Tracing is a Ledger stream per message: trace:<trace_id> files, 88,356 of them, fsync per append, retention by deleting files older than 2 days, boot stats the directory. Metrics (metrics:history 114 MB), curiosity ticks (43 MB) and mood samples (persona:state 17 MB) are appended to the same event log with the same durability as a git commit.

- **current:** Tracing is a Ledger stream per message: trace:<trace_id> files, 88,356 of them, fsync per append, retention by deleting files older than 2 days, boot stats the directory. Metrics (metrics:history 114 MB), curiosity ticks (43 MB) and mood samples (persona:state 17 MB) are appended to the same event log with the same durability as a git commit.
- **future pattern:** OpenTelemetry-shaped tracing: one trace per turn/task, spans for think, guardian, tool, verify, stt, tts with start/end, status and attributes; stored in a queryable table (sqlite WAL is enough at this scale); sampled and retained per root span; telemetry (metrics, ticks, mood) in a time-series table with row-level retention and downsampling, never in the decision log.
- **gap:** Latency questions ('why was that turn 9 s?') are unanswerable today without joining 88k files; disk grows ~700 MB/week from streams no decision depends on; the ledger's durability guarantee is paid on every mood sample. A spans table answers p50/p95 per stage in milliseconds and is the substrate every SLO below is measured on.

##### 3. Default ledger backend is one JSONL file per stream with fsync per append and a snapshot every 200 events; sqlite WAL exists (ledger/backends/sqlite.py) but is not the default. Projections (Planning's TaskStore, Learning's competence, Memory's recall index) rebuild by replaying streams at boot.

- **current:** Default ledger backend is one JSONL file per stream with fsync per append and a snapshot every 200 events; sqlite WAL exists (ledger/backends/sqlite.py) but is not the default. Projections (Planning's TaskStore, Learning's competence, Memory's recall index) rebuild by replaying streams at boot.
- **future pattern:** Event-sourced only where the events ARE the decisions (task, action, guardian, plan, self-model, memory writes); everything derived lives as relational projections in the same sqlite file, updated incrementally and queryable with SQL; jsonl kept as an export/import format.
- **gap:** 118k files and 1.4 GB for one household's fortnight; boot cost proportional to file count; 'list open tasks' is a replay, not a query. The sqlite backend already exists; the divergence is defaults and the absence of projection tables.

##### 4. A CLI chat turn is a throwaway Session (interface/service.py:943 mints a uuid per typed line); there is no transcript; continuity is three memory recalls (matched, recent-6, per-person) over hashed bag-of-words vectors, scoring every record, under a 0.25 s timeout that is crossed at ~1,000 records under load (context.py's own comment).

- **current:** A CLI chat turn is a throwaway Session (interface/service.py:943 mints a uuid per typed line); there is no transcript; continuity is three memory recalls (matched, recent-6, per-person) over hashed bag-of-words vectors, scoring every record, under a 0.25 s timeout that is crossed at ~1,000 records under load (context.py's own comment).
- **future pattern:** A durable conversation (thread) per channel and person, with a transcript that is compacted, plus tiered memory: working = the thread; episodic = turns; semantic = distilled facts; procedural = skills. Retrieval is an index lookup over real embeddings (a pre-warmed local embedder, vectors persisted), not a scan under a timer.
- **gap:** 'What did I just say?' fails by construction; the memory block silently vanishes once the store is the size consolidation itself targets (2,000 per kind). The 24.9 s sentence-transformers cold start is a boot-time warm-up problem, not a reason to use hashing at recall time.

##### 5. The voice path has one 95 s reply timeout (voice/config.py reply_timeout_s) and a 20 s TTS stall timeout; cognition chat max_seconds is 90 s; the bus request default is 30 s and the memory-bus handler timeout is 300 s. Measured 2026-09-18: stt 1.8-6.8 s, llm 1.3-9.5 s, full response 4-17 s. No deadline travels with the message; no stage has a budget.

- **current:** The voice path has one 95 s reply timeout (voice/config.py reply_timeout_s) and a 20 s TTS stall timeout; cognition chat max_seconds is 90 s; the bus request default is 30 s and the memory-bus handler timeout is 300 s. Measured 2026-09-18: stt 1.8-6.8 s, llm 1.3-9.5 s, full response 4-17 s. No deadline travels with the message; no stage has a budget.
- **future pattern:** End-to-end latency budgets: a deadline in the envelope, propagated and shrunk at each hop; per-stage budgets (STT final, first model token, first audio) with breaches recorded as span events; fast-tier routing and streaming for conversational turns so first audio does not wait for the whole reply.
- **gap:** Nothing enforces the budget a person experiences; every timeout is a local guard. Without spans the p95 is not even known per stage, so the 4-17 s spread cannot be attributed.

##### 6. Routing is an ordered failover list plus one 'strong' tier requested by orchestration on attempt >= N or after a helper returned nothing (session.py _tier; cognition/service.py routes['strong']). A chat turn and a patch step take the same primary route; reasoning_effort is a constant 'low'.

- **current:** Routing is an ordered failover list plus one 'strong' tier requested by orchestration on attempt >= N or after a helper returned nothing (session.py _tier; cognition/service.py routes['strong']). A chat turn and a patch step take the same primary route; reasoning_effort is a constant 'low'.
- **future pattern:** Per-step routing by (purpose, risk tier, context size, latency budget, expected difficulty): a fast/cheap model for tool-argument formatting, summaries, backchannel and simple chat; the frontier model for planning, code changes and verification; local only as fallback; effort/thinking as a routed parameter; route quality measured per suite.
- **gap:** Cost and latency are spent uniformly; the one lever that could halve voice latency (route chat to a fast tier, stream) is not a routing input today.

##### 7. 447 test files / 90k lines assert code shape; the 8-minute gate is unit tests; the project's own retrospective (07-post-cutover-review.md section 4) says they missed every real blocker; real bugs came from trial.py, trial_suite.py, observer waves and benchmark waves.

- **current:** 447 test files / 90k lines assert code shape; the 8-minute gate is unit tests; the project's own retrospective (07-post-cutover-review.md section 4) says they missed every real blocker; real bugs came from trial.py, trial_suite.py, observer waves and benchmark waves.
- **future pattern:** Eval-driven development: capability suites with scripted tasks and automatic scoring; replayable traces (record a task's spans and provider responses, replay with a fixture provider to test the harness deterministically); regression benchmarks per capability with noise sizing; the eval suite is the release gate.
- **gap:** Unit tests remain useful for contracts and pure functions, but the gate measures the wrong thing. The pieces of the right gate already exist in tools/ and benchmark/; they are not a package, not deterministic, and not what bless runs by default.

##### 8. The growth layer: Learning is unreachable (no publisher for learn.pipeline.run; proposes draft_candidate which is not registered -- learning/service.py UNREACHABLE), Reflection observes, Curiosity writes a 43 MB tick stream, and the Self Model's capabilities['tools'] is never written.

- **current:** The growth layer: Learning is unreachable (no publisher for learn.pipeline.run; proposes draft_candidate which is not registered -- learning/service.py UNREACHABLE), Reflection observes, Curiosity writes a 43 MB tick stream, and the Self Model's capabilities['tools'] is never written.
- **future pattern:** Skills as procedural memory are the unit of learning: a successful trajectory is distilled into a SKILL.md, evaluated on a held-out variant, promoted or discarded; code self-patches land only through the worktree + eval gate; competence is computed from eval results, not self-reported outcomes.
- **gap:** Learning produces no measured capability change; three packages implement one loop's three halves without the middle (evaluation). use_skill and simorgh_skills already exist, so the promotion loop is the missing piece.

##### 9. Guardian: 12 rules in fixed order, posture (guarded/trusted/locked), irreversible_requires_human, and since 2026-09-07 sim.sh auto-approves irreversible actions. Reversibility is binary at the last rule.

- **current:** Guardian: 12 rules in fixed order, posture (guarded/trusted/locked), irreversible_requires_human, and since 2026-09-07 sim.sh auto-approves irreversible actions. Reversibility is binary at the last rule.
- **future pattern:** Explicit safety tiers tied to reversibility, blast radius and origin, each with its own approval, rate limit and audit; the human gate reserved for the tier where it is cheap and matters (external, physical, financial); tightening automatic, loosening human-only.
- **gap:** With auto-approve on, a git commit in a worktree and a siren or a message to a third party are the same tier. Tiering restores the human gate exactly where the creator would want to be asked, without slowing the rest.

##### 10. One asyncio process runs 18 packages; heavy work (whisper, TTS engines, ffmpeg HLS, pytest -n auto for landing) runs in threads or subprocesses inside it; a busy tool thread ignored SIGTERM until os._exit was added; a 300 s bus handler timeout was every task's wall budget until made unbounded.

- **current:** One asyncio process runs 18 packages; heavy work (whisper, TTS engines, ffmpeg HLS, pytest -n auto for landing) runs in threads or subprocesses inside it; a busy tool thread ignored SIGTERM until os._exit was added; a 300 s bus handler timeout was every task's wall budget until made unbounded.
- **future pattern:** A single-loop harness with sub-agents in isolated contexts, and heavy or latency-critical services (STT/TTS, sandboxes, test runs) out of process behind deadlines and health, so a stuck engine cannot stall the loop or block shutdown.
- **gap:** local-multi mode already exists for workers; voice engines and the landing gate are the two things that still hold the main loop hostage.


### target architecture

**one paragraph:** Keep the bus, the contracts-only import rule, the Guardian chokepoint and the kernel; change what is underneath and around them. The Ledger becomes a sqlite-WAL store by default with two halves: a decision log that stays event-sourced (task:<id>, action:<id>, guardian, plan, memory writes, self-model changes) and a telemetry store of plain tables (spans, metrics_ts, samples) with row-level retention; jsonl becomes export/import. Tracing becomes spans: one root span per turn or task, child spans per think, guardian decision, tool call, verify, stt and tts, written by the bus trace writer into the spans table and sampled per root. Tool calling becomes native: a ToolSchema serialised from each Tool's args_schema is sent to providers that support it, the model's tool_use blocks become action.proposed unchanged, results return as tool_result messages, and the marker protocol survives only as a fallback for Ollama and the floor. Orchestration gains a durable Conversation (thread per channel and person, transcript, compaction) so a typed line is a turn in a thread rather than a session; Memory gains a persisted vector index over a pre-warmed real embedder. A deadline field in the envelope propagates end to end and a per-step router picks a route by purpose, risk tier, context size and latency budget. Learning, Reflection and Curiosity merge into one Growth package whose unit of learning is a skill promoted by evaluation; benchmark, trial.py, trial_suite.py and observer_kit merge into an Evals package that is the loader's bless gate. Safety tiers are explicit on every action and every Guardian decision is a span attribute.

#### modules

###### 1. ledger

- **name:** ledger
- **from:** keep (simorgh/ledger), default backend switched to sqlite
- **responsibility:** Decision log (event-sourced, per-stream seq, CAS) plus projection tables and a blob store, in one WAL database; jsonl as export/import.
- **key algorithms or methods:**
  - sqlite WAL with (stream, seq) primary key for CAS (already in backends/sqlite.py)
  - projection tables updated incrementally on append (tasks, actions, competence) instead of replay-at-boot; replay kept as the rebuild path
  - row-level retention per table (DELETE WHERE ts < cutoff) replacing per-file deletion
  - group_commit: batch fsync for telemetry writes, per-append fsync only for decision streams
- **interfaces:** Unchanged Ledger protocol (append/read/head/snapshot/blobs) for decision streams; new `query(table, where)` for projections; `export_jsonl(stream)` / `import_jsonl`.

###### 2. telemetry

- **name:** telemetry
- **from:** merge of bus/trace.py + kernel/metrics.py + the read side of interface/dashfeeds
- **responsibility:** Spans, metrics and samples: every turn/task is a trace with child spans; metrics and mood/tick samples go to time-series tables; SLO evaluation per stage.
- **key algorithms or methods:**
  - OpenTelemetry-shaped span model: trace_id, span_id, parent_id, name, start, end, status, attrs(JSON); the existing trace_id/causation_id on Message map directly
  - sampling per root span (keep every span of a sampled turn), not per message
  - downsampling of metrics_ts on the sleep tick (1 s -> 1 min after a day)
  - SLO table: stage -> budget; breach = span event, counted per day
- **interfaces:** `span(name, parent, attrs)` context manager offered via Context to every subsystem; `spans.query(trace_id)`; `simorgh trace <id>` renders the tree from the table; HTTP /api/traces and /api/metrics read it.

###### 3. cognition

- **name:** cognition
- **from:** keep (simorgh/cognition); add toolcalling.py, routing.py; parser.py demoted to fallback
- **responsibility:** Providers with native tool use, per-step routing, budgets, compaction.
- **key algorithms or methods:**
  - ToolSchema serialiser: Tool.args_schema -> provider tool definitions (OpenAI-style function schema for Together/Ollama, Anthropic tool blocks for the Claude path, Gemini function declarations)
  - tool_use/tool_result message shapes in contracts; a ParsedOutput that carries typed calls with ids
  - routing table keyed by (purpose, tier, context_tokens_bucket, latency_budget_bucket) -> ordered candidates + effort; measured route quality from evals feeds the table
  - existing deadline share, cooldown, budget estimate unchanged; deadline now taken from the envelope
- **interfaces:** cognition.think gains `tools: [ToolSchema]`, `deadline`, `risk_tier`; reply carries `tool_calls: [{id, tool, args}]` typed; marker parsing only when the provider lacks tool support.

###### 4. orchestration (harness)

- **name:** orchestration (harness)
- **from:** keep (simorgh/orchestration); session.py shrinks as the police leave; add conversation.py
- **responsibility:** The single loop: gather -> think -> propose -> verify; durable threads; checkpoints; sub-agent delegation.
- **key algorithms or methods:**
  - Conversation: thread_id = (channel, person); transcript persisted in the decision log; compaction via cognition layers 1-5 on the transcript
  - tool results returned as tool_result messages bound to tool_use ids; several read-only calls per turn without the _read_batch heuristic
  - budgets in (tokens, usd, wall) per attempt instead of steps; checkpoint event after every irreversible action; resume.py unchanged in intent
  - delegate: sub-agent with fresh context and its own budget, returns a summary only (exists; put into an eval arm)
- **interfaces:** percept.text.received carries thread_id; turn.completed carries the thread's compacted state ref; task.step gains span_id.

###### 5. memory

- **name:** memory
- **from:** keep (simorgh/memory); add index.py; embedders pre-warmed
- **responsibility:** Tiered memory: working (the thread), episodic, semantic, procedural (skills); retrieval by index.
- **key algorithms or methods:**
  - real embedder loaded in a thread at boot (the 24.9 s is paid once, off the critical path); hashing only until it is warm
  - persisted vector index in sqlite (vectors as blobs, brute-force cosine over an in-RAM float32 matrix is sufficient at 10^4-10^5 records; an ANN library is optional later)
  - hybrid retrieval: BM25/inverted index + vector, reciprocal-rank fusion, then the existing confidence x recency scoring
  - consolidation on sleep: episodic -> semantic facts with supersedes links so a correction retires the fact it corrects
- **interfaces:** memory.retrieve unchanged on the wire; adds `thread_id`; the 0.25 s timeout becomes a budget from the envelope deadline.

###### 6. guardian

- **name:** guardian
- **from:** keep (simorgh/guardian); add tiers.py
- **responsibility:** Sole approver; explicit safety tiers; every decision a span attribute.
- **key algorithms or methods:**
  - Tier 0 read-only in scope: allow, log. Tier 1 reversible in scope (worktree edits, memory store, config that can be undone): allow in guarded, deny in locked. Tier 2 irreversible but local and bounded (commit/land, sandboxed shell/script/container, package install, device actions with undo): allow if the tool declares an undo or posture is trusted, else escalate; rate-limited per hour. Tier 3 external, physical or financial (notify a third party, run_remote, sirens, mail send, purchases, publishing): human always, in every posture
  - tier = f(reversibility, scope, origin, blast_radius) computed from the Tool protocol fields plus a per-tool override table
  - posture tightening on failure streaks and denial rates (exists); loosening only via human config
- **interfaces:** action.approved/denied gain `tier` and `rule`; guardian.posture unchanged; ui.prompt only for tier 3.

###### 7. execution

- **name:** execution
- **from:** keep (simorgh/execution); heavy tools moved behind out-of-process services
- **responsibility:** Tools, sandboxes, worktrees, MCP client; structured results.
- **key algorithms or methods:**
  - ToolResult carries a structured payload + blob ref + a short model-facing summary (progressive disclosure replaces the 8,000-char cut)
  - per-tool deadline from the envelope; a tool call is a span with success/latency
  - MCP stdio client kept as the integration standard for external services (Home Assistant and similar via their MCP servers, human-configured)
  - sandbox/test runs and media pipelines as subprocesses with kill-on-deadline, never threads
- **interfaces:** action.result gains `span_id`, `summary`, `result_ref`; tool.registered publishes the ToolSchema list so World Model can finally write capabilities['tools'].

###### 8. verification

- **name:** verification
- **from:** keep (simorgh/verification)
- **responsibility:** The critic: mechanical checks cheapest-first, checklist, trajectory; also the scorer inside evals.
- **key algorithms or methods:**
  - critic loop only where an oracle exists (tests, schema, diff applies); the LLM reviewer stays off for research (their own finding: not a net gain)
  - trajectory metrics computed from spans rather than re-reading task streams
- **interfaces:** Unchanged verify.requested/result; a pure-function `score(trajectory, oracle)` exported for evals.

###### 9. growth

- **name:** growth
- **from:** merge of learning + reflection + curiosity
- **responsibility:** One loop: notice (reflection), propose (curiosity sampler), evaluate (evals), promote (skill or patch); competence from evals.
- **key algorithms or methods:**
  - skill distillation from a successful trajectory -> SKILL.md candidate -> held-out variant task -> promote if it beats no-skill
  - diversity sampler kept verbatim (drives, staleness, gaps)
  - competence table = eval pass rates per capability, not self-reported task outcomes
  - self-patch only via worktree landing gated by evals; the unreachable PatchPipeline frozen
- **interfaces:** growth.candidate, growth.promoted, learn.competence.updated (kept name); ticks sampled into telemetry, not the decision log.

###### 10. evals

- **name:** evals
- **from:** merge of simorgh/benchmark + tools/trial.py + tools/trial_suite.py + tools/observer_kit.py
- **responsibility:** Capability suites, replayable traces, regression benchmarks, noise sizing; the bless gate.
- **key algorithms or methods:**
  - record/replay: a FixtureProvider that answers cognition.think from a recorded trace (by prompt hash) so harness changes are tested deterministically without a model
  - suites: household (fake devices), conversation (30-turn scripted recall), code (SWE-bench slice), research (GAIA L1), tool-use (BFCL); each scored automatically
  - >=3 repeats and a bootstrap CI per suite before any switch flips
  - results table in telemetry; dashboard chart per capability
- **interfaces:** `evals run <suite> --repeats N`; simloader bless calls it; results on benchmark.progress (kept).

###### 11. voice

- **name:** voice
- **from:** keep (simorgh/voice); engines out of process
- **responsibility:** Mic to words to speech with a budget per stage.
- **key algorithms or methods:**
  - deadline propagation: speech_end + budget -> envelope deadline; STT final <= 1.0 s, first model token <= 1.5 s, first audio <= 0.5 s after first sentence (targets to measure, not promises)
  - chat turns routed to the fast tier with streaming; first sentence to TTS while the rest generates
  - STT/TTS engines as subprocess services with health and p95 in spans
- **interfaces:** Unchanged bus messages; TurnClock metrics become spans.

###### 12. interface

- **name:** interface
- **from:** keep (simorgh/interface); dispatch.py split by domain
- **responsibility:** CLI/TUI/HTTP/channels over threads, not sessions.
- **key algorithms or methods:**
  - thread registry per channel and person
  - auth on by default for non-loopback binds
- **interfaces:** percept.text.received carries thread_id; /api/threads.

###### 13. worldmodel, planning, persona, kernel, contracts, bus

- **name:** worldmodel, planning, persona, kernel, contracts, bus
- **from:** keep
- **responsibility:** As today, with: capabilities['tools'] written from tool.registered; persona mood written to samples; envelope gains deadline, span_id, tier; bus handler timeout no longer a wall budget.
- **key algorithms or methods:**
  - contracts: ToolSchema, tool_use/tool_result message shapes, deadline and span fields on Message
- **interfaces:** Additive contract changes only.

###### 14. src/ (v1)

- **name:** src/ (v1)
- **from:** delete
- **responsibility:** None.
- **key algorithms or methods:**
- **interfaces:** None.


#### merges

- learning + reflection + curiosity -> growth (one propose/evaluate/promote loop; keep the diversity sampler)
- bus/trace.py + kernel/metrics.py + interface dashfeeds read side -> telemetry (spans + metrics_ts)
- benchmark + tools/trial.py + tools/trial_suite.py + tools/observer_kit.py -> evals (the bless gate)
- the seven regex police in orchestration/session.py -> deleted as native tool use makes each unreachable; marker fallback keeps invented_markers only

#### additions

- native tool calling (ToolSchema serialiser + adapter support + tool_use/tool_result contracts)
- spans table and per-root sampling; SLO table per stage
- Conversation threads with transcripts and compaction
- persisted vector index with a pre-warmed real embedder; hybrid retrieval
- deadline propagation in the envelope
- per-step routing table keyed by purpose x tier x context x latency
- record/replay FixtureProvider and capability suites with noise sizing
- explicit safety tiers 0-3 with tier on every decision

#### deletions or freezes

- src/ (v1) deleted
- PatchPipeline frozen until it is reachable through the worktree + eval gate
- jsonl demoted from default backend to export/import
- trace:<id> per-message streams removed in favour of spans
- metrics:history, curiosity:ticks, persona:state as event streams removed (samples table instead)
- step count as the task budget (replaced by tokens/usd/wall)
- 300 s bus handler timeout as an implicit wall budget
- the 8,000-char tool-result cut (replaced by summary + blob ref)


### capability programs

##### 1. reasoning

- **capability:** reasoning
- **current state:** One think per step; one action per step except read-only batches; tool intent parsed from prose; 'strong' tier only on retry; reasoning_effort fixed at low; the LLM answer reviewer was measured as not a net gain (111 correct and 111 wrong rejected); leading benchmark failure is 'step budget exhausted', not wrong reasoning.
- **method:** Native tool use with several tool_use blocks per turn; effort/thinking as a routed parameter per step (planning and code steps get the frontier route and higher effort, formatting and summaries get the fast route); plan-then-act for tasks whose budget exceeds a threshold, with the plan stored as an artifact in the task stream and re-grounded against it; critic loop only where a mechanical oracle exists (tests, schema, diff applies), never a free-form LLM reviewer on research.
- **how to measure:** BFCL-parallel and GAIA L1-L3 with >=3 repeats and a CI; wasted-step rate from spans (a step whose tool result changed no state); fabricated-claim rate (today's police counters become span events so the baseline is known before the police are removed).
- **first increment:** Native tool calling in the Together adapter and the orchestration tool_result path, marker fallback kept; run BFCL-parallel and one GAIA slice before/after, 3 repeats each.

##### 2. long tasks

- **capability:** long tasks
- **current state:** Per-attempt step budget; resume.py carries notes and kept edits across attempts; re-grounding built (no measured gain); delegate built but never in an arm; the bus handler timeout was the wall budget until unbounded; sqlite lease still caps; worktree landing with whole-suite gate.
- **method:** Budget in (tokens, usd, wall) per attempt; a checkpoint event after every irreversible action so resume starts from state, not from a note; sub-agents (delegate) with isolated context and their own budgets for exploration; transcript compaction on the thread; test-first patch loop where verification is the oracle; heavy steps (test suite, container) out of process with deadlines so a stuck step is a span timeout, not a stalled loop.
- **how to measure:** SWE-bench Verified slice resolved rate with 3 repeats; fraction of tasks ending in budget exhaustion; induced-crash resume success (an eval that kills the process mid-task and checks the task finishes on restart with no duplicated irreversible action); wall time per resolved task from root spans.
- **first increment:** Replace the step cap with a (tokens, usd, wall) budget and put delegate into one eval arm; add the kill-and-resume eval.

##### 3. environment interaction

- **capability:** environment interaction
- **current state:** 98 tools across files/code/git, sandboxes, web, packages and six domains; static MCP client; Home Assistant not configured; cameras via RTSP -> ffmpeg -> HLS on disk (3.8 GB); tool results cut at 8,000 chars; browser tools exist; capabilities['tools'] in the Self Model never written.
- **method:** MCP as the integration standard for external services (human-configured servers, discovered tools flow through the same Guardian path); structured ToolResult with summary + blob ref (progressive disclosure: the model asks for more of a result rather than receiving a cut); every tool call a span with success and latency; browser/computer-use as an isolated sub-agent with its own budget and tier; tool.registered publishes schemas so the Self Model knows its hands.
- **how to measure:** Per-tool success rate and p95 latency from spans (the module map's own suggested handle); a household suite of 10-20 scripted tasks against fake devices run nightly; denial rate per tier.
- **first increment:** Span per tool call with success/latency and the household suite built on tools/trial_suite.py's scoring shape.

##### 4. user interaction

- **capability:** user interaction
- **current state:** Throwaway session per typed line; no transcript; continuity is three memory recalls over hashed bag-of-words under 0.25 s that vanish at ~1,000 records under load; voice full response 4-17 s; speaker identification via TitaNet; barge-in works; per-person memory filtering on voice.
- **method:** Durable Conversation thread per channel and person with a transcript in the prompt and compaction; tiered memory with a pre-warmed real embedder and a persisted index; chat routed to the fast tier and streamed sentence-by-sentence into TTS; deadline propagation with per-stage budgets (STT final, first token, first audio) and breaches counted; per-person privacy kept as a thread property rather than a tag filter.
- **how to measure:** A 30-turn scripted conversation suite: recall@1 for 'what did I just say', a corrected fact answered correctly N turns later, a fact told to one family member not surfacing to another; response p50/p95 per stage from spans; count of stage-budget breaches per day.
- **first increment:** Conversation object with a transcript in the prompt (the memory recalls stay as they are), and the embedder warmed in a boot thread with vectors persisted; measure the conversation suite before/after.

##### 5. self-improvement

- **capability:** self-improvement
- **current state:** Learning unreachable (no publisher, tool not registered); Reflection observes and distils skill candidates; Curiosity samples areas and writes ticks; skills exist (simorgh_skills, use_skill); worktree landing gated by the unit suite; simloader tags known-good images; competence is derived from self-reported task outcomes.
- **method:** Skills as the unit of learning: successful trajectory -> distilled SKILL.md -> evaluated on a held-out variant -> promoted only if it beats no-skill; code self-patches land only through worktree + the eval gate; competence table computed from eval pass rates; the bless gate is the eval suite; the diversity sampler chooses what to try next from measured gaps.
- **how to measure:** Skill promotion rate and measured lift per promoted skill on its capability suite; regressions caught by the gate per month; self-patch acceptance rate; competence calibration (stated vs measured) per capability.
- **first increment:** Make simloader bless run the eval suite by default and write competence from its results; freeze PatchPipeline.


### migration path

##### 1. 0. Telemetry cut-over

- **stage:** 0. Telemetry cut-over
- **weeks:** 1
- **does:** Add spans and metrics_ts tables to the sqlite ledger; bus trace writer writes spans (one root per turn/task, children per think/guardian/tool/verify/stt/tts) instead of trace:<id> files; kernel metrics, curiosity ticks and persona mood go to samples with row retention; `simorgh trace` and the dashboard read the tables; jsonl decision streams untouched.
- **unlocks:** Per-stage p50/p95 for voice and tasks in milliseconds; disk growth stops; boot no longer stats 118k files; every later stage is measurable.
- **risk:** Consumers of trace streams (interface dashfeeds, reflection's trajectory reads) must be ported the same week or they read nothing; mitigated by keeping the old writer behind a switch for one bless cycle.

##### 2. 1. Native tool calling

- **stage:** 1. Native tool calling
- **weeks:** 2
- **does:** ToolSchema from args_schema; tool_use/tool_result shapes in contracts; Together, Claude CLI and Gemini adapters send tools and return typed calls; orchestration feeds results as tool_result messages; Guardian path unchanged; marker parsing kept for Ollama/floor; each regex police rule removed once its span counter reads zero for a bless cycle.
- **unlocks:** Multi-argument and multi-call tools without per-tool hacks; fabricated-result and invented-tool classes disappear; session.py shrinks.
- **risk:** Prompt-shape regressions on the marker fallback path; a provider that half-supports tools; mitigated by running BFCL and one GAIA slice per adapter before enabling by default.

##### 3. 2. Conversation and memory index

- **stage:** 2. Conversation and memory index
- **weeks:** 2
- **does:** Conversation threads with transcripts and compaction; interface and voice send thread_id; embedder pre-warmed at boot; vectors persisted; hybrid retrieval; memory timeout taken from the envelope deadline.
- **unlocks:** Continuity across lines, restarts and channels; recall that does not vanish under load.
- **risk:** Per-person privacy on voice currently lives in a tag filter and must become a thread property before the old filter is removed; measured by the conversation suite's cross-person case.

##### 4. 3. Evals as the gate

- **stage:** 3. Evals as the gate
- **weeks:** 2
- **does:** simorgh/evals package from benchmark + trial harness + observer kit; FixtureProvider record/replay from spans; household, conversation, code, research and tool-use suites with repeats and CIs; simloader bless runs it; results in telemetry.
- **unlocks:** Every switch and every later stage has a number with an interval; harness changes testable without a model.
- **risk:** Eval cost in dollars and minutes; mitigated by a fast tier for scoring and replay for harness-only changes.

##### 5. 4. Latency budgets and per-step routing

- **stage:** 4. Latency budgets and per-step routing
- **weeks:** 2
- **does:** deadline and tier fields on Message; per-stage budgets and SLO table; routing table keyed by purpose x tier x context x latency with measured route quality; chat to the fast tier with streaming into TTS; STT/TTS engines as subprocess services.
- **unlocks:** Voice p95 attributable and reducible; cost per turn falls for the common case.
- **risk:** A fast tier that answers worse; only enabled per route when the conversation suite shows no loss.

##### 6. 5. Long-horizon

- **stage:** 5. Long-horizon
- **weeks:** 3
- **does:** (tokens, usd, wall) budgets; checkpoint events; delegate in an arm; plan artifact for large tasks; landing gate and sandboxes out of process with deadlines; kill-and-resume eval.
- **unlocks:** SWE-bench-shaped tasks finishing rather than exhausting budgets; safe shutdown mid-task.
- **risk:** Worktree landing and checkpoints interacting badly on retry; bounded by the resume eval.

##### 7. 6. Growth merge and cleanup

- **stage:** 6. Growth merge and cleanup
- **weeks:** 2
- **does:** learning + reflection + curiosity -> growth; skill promotion loop through evals; competence from evals; PatchPipeline frozen; src/ deleted; tiers 0-3 explicit in Guardian with tier 3 human-gated in every posture; capabilities['tools'] written.
- **unlocks:** Measured self-improvement; the Self Model finally knows its tools; a human is asked exactly when it matters.
- **risk:** Losing the diversity sampler's behaviour in the merge; keep sampler.py and its regression test verbatim.


**agi honesty:** This architecture is a harness around a frontier model: reasoning comes from the provider, and the harness adds memory, tools, safety, continuity and measured improvement. Its ceiling on general capability is the model's ceiling; nothing here learns at the weight level, and the blueprint says so. What the harness CAN deliver, and what 'more general' concretely means for a household agent, is breadth times depth times autonomy: more task domains completed end to end (code, research, home devices, media, calendar, conversation), longer horizons per task (hours, with resume), across more surfaces (voice, chat, TV, phone), with fewer hand-written per-incident heuristics and with a person asked only at tier 3. Progress toward that is measurable as a capability-suite matrix, which is the honest version of the blueprint's 'generality as a queryable number'. The investments that compound are the ones that survive a model swap: eval suites, span data (replayable), skills, the memory index, tool schemas and the safety tiers. The ones that do not compound are regex police, dated incident comments and per-tool argument hacks; they are paid again with every new model. With the migration above, Sim can become a state-of-the-art personal agent harness of the shape production harnesses have in 2026, continuously improving on measured suites. It will not be AGI under any definition that requires learning beyond its model, open-ended competence growth without a human choosing what to measure, or capability that exceeds the frontier model it routes to; calling it that would contradict the SOUL.md directive on transparency.

**biggest risk of this proposal:** Half-migration. The project's own dominant bug shape is the unconnected wire (a slot with one side implemented), and a substrate migration is the largest producer of unconnected wires there is: two trace formats, two tool protocols, two memory indexes, two budgets, each half-read by something. For one developer working through coding agents, the failure mode is a live, self-editing system that boots from a checkout with both halves present, where the loader's gate is green because the unit suite still asserts the old shape. Mitigation is ordering and deletion discipline: telemetry first (stage 0) because every later stage is judged by it; evals as the gate (stage 3) before routing or long-horizon changes; every stage behind a config switch; and no stage begins until the previous stage's old path has been deleted and the eval suite has passed on the deleted-path build. The Guardian invariant and corrigibility are untouched by every stage, which is what makes the migration safe to do live.

