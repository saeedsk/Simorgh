# propose:cognitive

*Workflow: panel · Phase: Propose · Agent id: `a0ec0d2e4ab14f248` · Tool calls: 30*

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
  
  
  LENS: COGNITIVE ARCHITECTURE and long-horizon autonomy. You are an AI scientist who works on memory, planning, world models, reflection and continual learning for agents. Re-architect Sim's memory (tiers, real embeddings, indexes, consolidation, forgetting, supersession), its self model and world model (what should be state, what should be a learned/estimated quantity), planning for multi-day tasks (goal trees, checkpoints, re-grounding, verification, critic), and the growth loop (learning -> competence -> behaviour change; reflection that actually changes prompts/policies/skills; curiosity as directed exploration). Say which of Learning/Reflection/Curiosity/Persona/WorldModel should merge, and what algorithms make the loop close.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/docs/module-map.md | 1 # Simorgh — Module Map and System Blocks 2 3 **What this is.** One picture of every major building block, what each one 4 owns, and how they interact — writte |
| 2 | Read | /Users/saeed/ws/Simorgh/docs/blueprint/01-vision-and-principles.md | 1 # 01 — Vision and Principles 2 3 > Part of the Simorgh v2 blueprint. Read `00-README.md` first for how this 4 > set fits together. This file states *what we a |
| 3 | Read | /Users/saeed/ws/Simorgh/docs/blueprint/02-system-architecture.md | 1 # 02 — System Architecture 2 3 > Part of the Simorgh v2 blueprint. Governing principles are in 4 > `01-vision-and-principles.md`; the exact message envelope,  |
| 4 | Bash | Count lines and list files in the cognitive subsystems |  1942 simorgh/orchestration/session.py 327 simorgh/orchestration/context.py 357 simorgh/cognition/router.py 406 simorgh/cognition/parser.py 528 simorgh/memory/s |
| 5 | Bash | Locate the key functions in session.py | 168:def _transcript_echo(text: str) -> str: 213:def invented_markers(text: str, offered: tuple[str, ...]) -> list[str]: 278:def claimed_to_commit(text: str, ses |
| 6 | Bash | Read SessionRunner class head and run() | class SessionRunner: def __init__( self, bus, ledger, *, clock=None, worker_id: str = "w1", is_paused=None, is_cancelled=None, think_timeout_s: float = 5.0, act |
| 7 | Bash | Read _run loop body |  async def _run(self, session: Session, *, user_text: str = "") -> Outcome: await self._append(session, topics.TASK_STARTED, {"task_id": session.task_id, "worke |
| 8 | Bash | Read _think |  async def _think(self, session: Session, user_text: str, *, last_step: bool, no_tools: bool = False) -> Message \| None: steps_left = session.budget.steps_left  |
| 9 | Bash | Read orchestration/context.py | """ContextAssembler (16 section 5): gathers the memory block and the session transcript for one `cognition.think` call. The persona voice and the self summary a |
| 10 | Bash | Read cognition/router.py | """Provider failover and selection (docs/blueprint/subsystems/04- cognition.md section 5). Ported from v1 `CognitionRouter`'s failover shape: try each candidate |
| 11 | Bash | Read cognition/parser.py head | """Output parsing: markers, edit blocks, non-answer detection (docs/ blueprint/subsystems/04-cognition.md section 5, "Output parsing"). Ported directly from v1  |
| 12 | Bash | Read memory/store.py | """The memory engine (docs/blueprint/subsystems/05-memory.md sections 4-5): episodic/semantic/procedural records as one-event-per-item Ledger streams (`memory:e |
| 13 | Bash | Read memory embed, embedders, consolidation | """A dependency-free semantic embedding via the hashing trick, ported verbatim from v1 `src/memory/long_term.py::embed_text` (docs/blueprint/ subsystems/05-memo |
| 14 | Bash | Read worldmodel/selfmodel.py | """The Self Model. Identity is real, loaded and hashed from `docs/SOUL.md`. As of Phase 4 Wave 2 the other sections (competence, limitations, change_history, ca |
| 15 | Bash | Read learning service, competence, pipeline, strategy | """`Service`: wires `OutcomeRecorder`, `CompetenceTable`, strategy suggestion, and the patch/skill pipeline runner into the real Bus/Ledger (spec section 5). Sc |
| 16 | Bash | Read reflection/service.py head | """Reflection as a `Subsystem` (Layer 3, registry.py). Observer only -- never emits `action.proposed`, never writes `self:model` directly (only `self.observatio |
| 17 | Bash | Read curiosity/service.py head | """`Service`: wires drives, sampling, idea/project proposal, interests, and sharing into the real `Subsystem` protocol (spec section 5). One exploration tick at |
| 18 | Bash | Read voice/session.py top | """The spoken conversation: microphone frames in, speech out, with the floor changing hands the way it does between people. frames -> FrameVad -> TurnManager -> |
| 19 | Bash | Read guardian/rules.py head and structure | """The pipeline's rules, in the fixed order 09-guardian.md section 5.1 specifies. Each rule returns `Decision(kind=allow\|deny\|escalate\|abstain, ...)`; `abstain` |
| 20 | Bash | Read progress notes, planning reground, decomposer | """The progress note: a task session's working memory between re-grounds. A long session used to carry every tool call and result it ever made in `session.messa |
| 21 | Bash | Read reflection service handlers |  await ctx.bus.subscribe(topics.ACTION_DENIED, self._on_action_denied), await ctx.bus.subscribe(topics.SYSTEM_TICK_IDLE, self._on_idle_tick), ] if self.config.r |
| 22 | Bash | Map the rest of reflection service | 2: async def _on_plan_revised(self, message: Message) -> None: 4: # project TASK_CREATED's task_id anywhere in the current 17: async def _on_outcome_recorded(se |
| 23 | Bash | Read worldmodel service and facets | """World Model as a `Subsystem` -- env facets (real, this session) plus a live-updating Self Model (identity real from boot; competence, calibration, limitation |
| 24 | Bash | Read curiosity drives and sampler, how gaps flow | """`DriveEngine`: per-area scores from four drives (spec section 5.1). Unknown-area gap defaults to 0.6, not 0 -- an area nothing has ever been measured on is n |
| 25 | Bash | Read resume and Session shape | """What a Session inherits from the `task:<id>` stream before it runs. Two different situations look alike from here -- a task whose last worker died mid-run, a |
| 26 | Bash | Read planning model, rollup, planmode | """`Task`/`Step` data model and the status transition table (spec section 4). Ported from `src/orchestrator/tasks.py`/`projects.py`, extended with `mode`, `risk |
| 27 | Bash | Read memory config, recall index head, orchestration config defaults | """Memory configuration (docs/blueprint/subsystems/05-memory.md section 3.5). Every field has a working default -- `[memory]` may be absent.""" from __future__  |
| 28 | Bash | Read cognition assembler head and list plan/finding docs | """Prompt assembly (docs/blueprint/subsystems/04-cognition.md section 5, "Prompt assembly order"): ordered blocks, each `protected` (never compacted -- principl |
| 29 | Bash | Read persona user model, outcome task typing, profiles | """The user model (theory of mind) -- a confidence-weighted facet store (spec section 4's `UserModelProjection`: last-write-wins per facet, confidence merged as |
| 30 | Bash | Confirm long-run context design, episodic write path, decomposer scope, revision loop, self-model persistence | # Long runs: context, delegation and model tiers The creator, 2026-09-15, after the first ten-copy benchmark wave: "what architecture changes do you suggest to  |

## Structured reply

**lens:** Cognitive architecture and long-horizon autonomy: memory tiers and retrieval, self model and world model as estimated quantities, goal trees with checkpoints and critics for multi-day work, and a growth loop that actually closes (outcome -> estimate -> proposed change -> evaluated -> adopted -> retired). Verified against the code at /Users/saeed/ws/Simorgh on 2026-09-18; no files modified, nothing booted, no paid calls.

### what sim got right

##### 1. All state is an append-only Ledger of events and every status, competence figure and the Self Model are (meant to be) projections rebuilt from the log (ledger/, learning/competence.py::CompetenceTable is a real fold over learn:outcomes; orchestration/resume.py rebuilds attempts from task:<id>).

- **decision:** All state is an append-only Ledger of events and every status, competence figure and the Self Model are (meant to be) projections rebuilt from the log (ledger/, learning/competence.py::CompetenceTable is a real fold over learn:outcomes; orchestration/resume.py rebuilds attempts from task:<id>).
- **why it matters for the future:** Long-horizon agents live or die on checkpoint/resume and on replayable history. Every pattern this proposal needs -- durable goal trees, checkpoints, a fact store with supersession, competence posteriors, eval baselines -- is 'one more projection over streams that already exist'. Nothing has to be re-platformed.
- **keep or strengthen:** Strengthen: make the Self Model and the memory indexes actual projections with snapshots (today the Self Model is in-memory only and the recall index is rebuilt at boot). Add a `checkpoint` event type to task streams. Keep fsync-per-append for action/task streams; move high-volume trace/metrics streams to batched appends (that is a ledger lens problem, but it is what makes the cognitive projections cheap).

##### 2. Structural safety: proposal -> Guardian (12 rules, HMAC) -> Execution, enforced by bus topology and proved at boot, with corrigibility (pause/stop) as the first rule.

- **decision:** Structural safety: proposal -> Guardian (12 rules, HMAC) -> Execution, enforced by bus topology and proved at boot, with corrigibility (pause/stop) as the first rule.
- **why it matters for the future:** Every serious 2026 agent harness is bolting a permission chokepoint on after the fact; Sim has it natively, which is exactly what lets a self-improving loop be safe: a learned policy, a new skill, a routing change or a self-patch can all be 'just another proposal'. The growth loop below adopts nothing except through action.proposed.
- **keep or strengthen:** Keep unchanged. Strengthen by giving the growth loop's policy store (`growth:policies`) protected-subject status for loosening and by adding one Guardian rule: a proposal may add guidance or restrictions to a task type's rules, never touch guardian/, contracts/, kernel/, execution/verifier.py (already protected) or the policy store's own gate.

##### 3. Worker/Session separation with lease heartbeat, attempts that carry a note, and resume from the task's own stream (orchestration/worker.py, resume.py, session.py::_run).

- **decision:** Worker/Session separation with lease heartbeat, attempts that carry a note, and resume from the task's own stream (orchestration/worker.py, resume.py, session.py::_run).
- **why it matters for the future:** This is the skeleton of a checkpoint-and-resume long-horizon agent: a task already survives crashes and spans attempts. What is missing is a model-authored checkpoint (the progress note exists but is off) and explicit waiting states, not a new loop.
- **keep or strengthen:** Strengthen: turn on `reground_every_steps=3` (the spec's own value, 16-orchestration.md 3.5); persist the model's progress note as the carried note between attempts instead of the mechanical 220-char-per-step summary; add WAITING(until|event|human) as a task status with scheduler wake-ups.

##### 4. A competence table that is a proper statistic: Laplace-smoothed success per task_type, shrinkage toward 0.5 below min_samples, UCB1-style exploration bonus, calibration bins from stated vs empirical confidence (learning/competence.py).

- **decision:** A competence table that is a proper statistic: Laplace-smoothed success per task_type, shrinkage toward 0.5 below min_samples, UCB1-style exploration bonus, calibration bins from stated vs empirical confidence (learning/competence.py).
- **why it matters for the future:** A self model that is an estimated quantity with uncertainty, not a string, is what makes directed exploration (Thompson sampling over Beta posteriors), model escalation and honest 'I am bad at X' possible. The primitive is right; it is under-consumed (compute_gaps returns [], strategy.suggest has no caller).
- **keep or strengthen:** Strengthen: expose the posterior (alpha, beta, last-updated) per task_type and per (task_type, strategy) over the bus; implement compute_gaps from it; add per-tool reliability/latency and per-provider-per-purpose quality as sibling estimates.

##### 5. Epistemic honesty as a design rule: 'unavailable' is distinct from 'absent' (context.py MEMORY_UNAVAILABLE_NOTE), truncation is announced (memory/store.py TRUNCATION_NOTICE), distillation is refused when it invents specifics (memory/consolidation.py::untraceable), verification has an insufficient-evidence outcome.

- **decision:** Epistemic honesty as a design rule: 'unavailable' is distinct from 'absent' (context.py MEMORY_UNAVAILABLE_NOTE), truncation is announced (memory/store.py TRUNCATION_NOTICE), distillation is refused when it invents specifics (memory/consolidation.py::untraceable), verification has an insufficient-evidence outcome.
- **why it matters for the future:** Memory systems fail silently and corruptly; a fact store with provenance and supersession only works if the extractor is held to traceability. Sim already has the check; the rebuilt consolidation below reuses it on structured facts instead of prose.
- **keep or strengthen:** Keep; generalise: every fact carries source_refs, every recall says how many matched but were cut, every self-model figure carries its sample count.

##### 6. Purpose-typed cognition calls (chat, draft, consolidate, review, reground, decompose, verify) with per-purpose budgets and a router that takes a per-call provider order (cognition/router.py::complete(order=...), session.py::_tier).

- **decision:** Purpose-typed cognition calls (chat, draft, consolidate, review, reground, decompose, verify) with per-purpose budgets and a router that takes a per-call provider order (cognition/router.py::complete(order=...), session.py::_tier).
- **why it matters for the future:** Model routing by task is a settled pattern; the seam already exists. Today all purposes go to one model at one effort (long-run-context-design.md section 1). Making purpose select a tier is config plus a small router change, not architecture.
- **keep or strengthen:** Strengthen: purpose -> tier map in [cognition]; plan/decompose/critique/verify on the strong tier, reground/consolidate/classify on the cheap tier; escalate_from_attempt=1.

##### 7. Curiosity's diversity by construction: sample the area from real inventories with drive-weighted softmax, then ask the model to propose within it (curiosity/sampler.py, drives.py).

- **decision:** Curiosity's diversity by construction: sample the area from real inventories with drive-weighted softmax, then ask the model to propose within it (curiosity/sampler.py, drives.py).
- **why it matters for the future:** Directed exploration that does not collapse onto the model's favourite topic is the correct shape for intrinsic motivation. The scoring inputs are broken (gap constant, targets are only Sim's own code areas), not the mechanism.
- **keep or strengthen:** Strengthen: feed it real gaps (Beta posteriors), extend the target space from repo areas to household entities and recurring unanswered questions, replace the softmax over point scores with Thompson sampling over posteriors.

##### 8. Verification is a separate subsystem with mechanical checks cheapest-first, plan review, trajectory scoring and a bounded evaluator-optimizer revision loop (max_revisions=2 for patch/skill; session.py::_verify_then_finish).

- **decision:** Verification is a separate subsystem with mechanical checks cheapest-first, plan review, trajectory scoring and a bounded evaluator-optimizer revision loop (max_revisions=2 for patch/skill; session.py::_verify_then_finish).
- **why it matters for the future:** Plan-verify-critic loops are how long tasks stay on course. The pieces exist; they only run at the end of a task. Moving the critic to checkpoints is a wiring change.
- **keep or strengthen:** Strengthen: invoke trajectory scoring at every checkpoint (progress note) against the task's acceptance criteria, not only at terminal; feed its verdict into re-planning.

##### 9. Skills as procedural memory (SKILL.md catalog, use_skill, Reflection's distillation of a solved task into a skill task; contracts/skills.py).

- **decision:** Skills as procedural memory (SKILL.md catalog, use_skill, Reflection's distillation of a solved task into a skill task; contracts/skills.py).
- **why it matters for the future:** Skills/procedural memory is the one form of learning a harness around a fixed model can do that compounds. The plumbing is in place and gated by Guardian.
- **keep or strengthen:** Keep; make skills one of four typed 'policy artifacts' in the growth loop so a skill is adopted only when it beats baseline on the cases that motivated it.

##### 10. 'Only contracts is shared' and a typed bus: subsystems can be merged or split without touching neighbours as long as topics are preserved.

- **decision:** 'Only contracts is shared' and a typed bus: subsystems can be merged or split without touching neighbours as long as topics are preserved.
- **why it matters for the future:** The merge of Learning+Reflection+Curiosity proposed below is possible precisely because their topics are the interface; the rest of the system will not notice.
- **keep or strengthen:** Keep.


### where it diverges from the future

##### 1. Memory recall = hashed bag-of-words (memory/embed.py, 256 sha256 buckets) scored over every record via an exact inverted index (memory/recall.py); three recalls per turn (matched k=8, recent k=6, person k=5), 0.25 s budget, 4,000-char block; flat records with tags; contradictions = 'two most recent distinct under the first tag, penalise both 0.5' (store.py::flag_contradictions); supersession is a sentence in the prompt header asking the model to prefer later lines.

- **current:** Memory recall = hashed bag-of-words (memory/embed.py, 256 sha256 buckets) scored over every record via an exact inverted index (memory/recall.py); three recalls per turn (matched k=8, recent k=6, person k=5), 0.25 s budget, 4,000-char block; flat records with tags; contradictions = 'two most recent distinct under the first tag, penalise both 0.5' (store.py::flag_contradictions); supersession is a sentence in the prompt header asking the model to prefer later lines.
- **future pattern:** Tiered memory (working/episodic/semantic/procedural) with real embeddings computed off the hot path, hybrid lexical+dense retrieval with rank fusion, filters by person/time/entity, and a semantic tier that is a fact store with first-class supersession and provenance; consolidation extracts and merges facts rather than summarising prose.
- **gap:** Paraphrases score 0.0 (measured in embedders.py); a correction and the thing it corrected arrive as peers; 'the machine names' failure documented in context.py is structural, not a tuning problem. The local embedder was rejected because its 24.9 s first call broke the 0.25 s recall budget -- the fix is to embed at store time in the background and persist vectors, not to give up on semantics.

##### 2. A chat turn is a throwaway Session with a fresh session_id per line; there is no transcript; continuity is similarity recall. WorkingMemory exists in memory/store.py and nothing feeds it.

- **current:** A chat turn is a throwaway Session with a fresh session_id per line; there is no transcript; continuity is similarity recall. WorkingMemory exists in memory/store.py and nothing feeds it.
- **future pattern:** Persistent conversation threads per (person, channel) with compaction; working memory is the thread plus the current task's progress note; long-term recall supplements it rather than replacing it.
- **gap:** Sim cannot reliably remember what was said two turns ago unless the vocabulary overlaps. The class that would hold the thread is already written and unwired.

##### 3. Self Model is in-memory only (selfmodel.py docstring), capabilities['tools'] never written, compute_gaps returns [], open_questions never populated; the summary is a 300-token string of counts.

- **current:** Self Model is in-memory only (selfmodel.py docstring), capabilities['tools'] never written, compute_gaps returns [], open_questions never populated; the summary is a 300-token string of counts.
- **future pattern:** A self model that is a durable projection of estimated quantities with uncertainty: competence posteriors per task type and strategy, calibration, per-tool reliability and latency, per-provider quality per purpose, expected cost -- consumed by routing, planning and exploration, not only rendered into a prompt.
- **gap:** Every consumer of self-knowledge (Curiosity's gap drive, Planning's risk, Cognition's tier choice) is either reading a constant or not reading at all.

##### 4. World Model facets are the repository (capability_map, file_index, git_state) plus a regex-fed user_profile facet. No persistent household state; cameras, TV, presence arrive as tool results and are forgotten; percepts are text only.

- **current:** World Model facets are the repository (capability_map, file_index, git_state) plus a regex-fed user_profile facet. No persistent household state; cameras, TV, presence arrive as tool results and are forgotten; percepts are text only.
- **future pattern:** An environment state store: entities (people, rooms, devices, cameras, calendars) with observed state, last_seen, source and staleness; 'observe' tools that return diffs against known state; a compact 'world now' block in the prompt for household turns, symmetric with the self summary.
- **gap:** For a household agent the world model is the house, not the repo. Sim re-observes everything from scratch on every question and cannot notice change.

##### 5. Planning decomposes only into patch/research steps under simorgh/ (planning/decomposer.py); a project is COMPLETED when its children exist and no session waits on them (long-run-context-design.md section 1); re-grounding is one STILL_VALID yes/no per stale child; no acceptance criteria per node; no waiting states or wake-ups for tasks.

- **current:** Planning decomposes only into patch/research steps under simorgh/ (planning/decomposer.py); a project is COMPLETED when its children exist and no session waits on them (long-run-context-design.md section 1); re-grounding is one STILL_VALID yes/no per stale child; no acceptance criteria per node; no waiting states or wake-ups for tasks.
- **future pattern:** Hierarchical goal trees (goal -> milestones -> tasks) with acceptance criteria per node, checkpoints, event-driven waits (time, human answer, external event) with scheduler wake-ups, a critic at each checkpoint, and re-planning as a structured revision of the subtree given what changed.
- **gap:** Sim cannot run a multi-day household or research goal; it can only fan out code tasks and lose track of them.

##### 6. The growth loop is open at every seam: Learning's PatchPipeline is unreachable (no publisher, no self_patch.draft tool; service.py::UNREACHABLE); Reflection's critiques and lessons are stored as episodic prose nobody reads back; patterns become task proposals or limitation strings; strategy.suggest has no caller; Curiosity sees a constant gap. Nothing ever changes a prompt, a policy, a route or a scaffold as a result of experience.

- **current:** The growth loop is open at every seam: Learning's PatchPipeline is unreachable (no publisher, no self_patch.draft tool; service.py::UNREACHABLE); Reflection's critiques and lessons are stored as episodic prose nobody reads back; patterns become task proposals or limitation strings; strategy.suggest has no caller; Curiosity sees a constant gap. Nothing ever changes a prompt, a policy, a route or a scaffold as a result of experience.
- **future pattern:** A closed loop: outcomes -> posteriors -> diagnosed failure clusters -> a typed change artifact (rule, skill, routing, code patch) -> evaluated against a held-out case set in isolation -> adopted through the gate -> monitored and retired. Eval-driven development applied to the agent's own policies.
- **gap:** Three subsystems each own a fragment of one loop, and the fragments do not connect. Merging them is the fix, not more wires between them.

##### 7. Curiosity's target space is Sim's own code areas (worldmodel capability_map); ideas are PATCH/RESEARCH on the repo.

- **current:** Curiosity's target space is Sim's own code areas (worldmodel capability_map); ideas are PATCH/RESEARCH on the repo.
- **future pattern:** Directed exploration by expected information gain over the agent's competence posteriors and over the user's world: unanswered recurring questions, stale facts, devices never probed, skills never exercised.
- **gap:** Idle time improves Sim's codebase, not Sim's usefulness to the family.

##### 8. One model, one reasoning effort, purposes differ only in budgets; no separation of planner, actor and critic; verification only at terminal; free-text marker tool protocol with regex police for fabrication (session.py invented_markers, _transcript_echo, claimed_to_commit...).

- **current:** One model, one reasoning effort, purposes differ only in budgets; no separation of planner, actor and critic; verification only at terminal; free-text marker tool protocol with regex police for fabrication (session.py invented_markers, _transcript_echo, claimed_to_commit...).
- **future pattern:** Native structured tool use; purpose-routed models with escalation; plan-act-critique separation; cheap-model voting for verdicts (reground, verify) instead of one sample.
- **gap:** The tool-protocol part belongs to another lens, but it is a prerequisite here: the regex police are the cost of asking a model to act through prose, and a critic cannot be trusted while results can be echoed as text.

##### 9. Evaluation: 447 test files asserting shape; the trial harness (tools/trial.py, trial_suite.py) and the benchmark unit exist and found every real bug, but no learned change is gated by them and there is no recall/continuity eval built from the ledger's real conversations.

- **current:** Evaluation: 447 test files asserting shape; the trial harness (tools/trial.py, trial_suite.py) and the benchmark unit exist and found every real bug, but no learned change is gated by them and there is no recall/continuity eval built from the ledger's real conversations.
- **future pattern:** Every behavioural change -- learned or hand-made -- must beat a baseline on a held-out case set; memory has a recall@k eval on real questions; long tasks have a resume-after-kill eval.
- **gap:** Without this, the growth loop below would adopt changes that fit their motivating case and regress the rest; the project's own retrospective already documents that failure mode for humans.


### target architecture

**one paragraph:** Keep the substrate (Bus, Ledger, Kernel), the action path (Guardian, Execution, Verification) and Cognition's routing seam exactly as they are. Rebuild the cognitive core behind unchanged contracts: Memory becomes four real tiers with a fact store and hybrid retrieval; World Model becomes two durable projections -- a Self Model of estimated quantities and an Environment State of household entities -- and absorbs Persona's user model; Planning becomes goal trees with acceptance criteria, checkpoints, waiting states and a checkpoint critic; Orchestration keeps its one loop but runs persistent threads, progress-note compaction and isolated delegation. Merge Learning, Reflection and Curiosity into one Growth subsystem that owns a single loop over a versioned policy store: estimate (posteriors), diagnose (failure clusters), propose (rule | skill | routing | patch), evaluate (held-out cases in a worktree), adopt (through Guardian), retire (TTL and regression). Every recommendation is a projection, a wire, or a merge; none is a rewrite, and nothing acts on the world except through action.proposed.

#### modules

###### 1. memory

- **name:** memory
- **from:** keep (internals rebuilt: store.py, recall.py, consolidation.py, embedders.py)
- **responsibility:** Four tiers. Working: not a Ledger stream -- the per-(person, channel) rolling thread (the existing unfed WorkingMemory class, fed from turn.completed keyed by person+channel) plus the current task's progress note. Episodic: turn/step/critique records as today, indexed at write time. Semantic: a fact store `memory:facts` of (subject, predicate, object, valid_from, valid_to, superseded_by, confidence, source_refs, person_scope) with first-class supersession. Procedural: skills (SKILL.md) and adopted growth policies, plus tool-usage recipes distilled from successful trajectories.
- **key algorithms or methods:**
  - Hybrid retrieval: BM25 over real tokens (extend the existing inverted index in recall.py with tf and doc length; stdlib) UNION dense top-N (local sentence-transformers as the optional adapter that already exists in embedders.py), fused by reciprocal rank fusion, then person/time/channel filters and the existing recency and confidence terms. Hashing stays as the floor when the dense index is cold.
  - Embed at store time in a background thread and persist vectors as a projection file keyed by ref (array('f') per record); warm at boot in the background; recall never waits on embedding. This removes the 24.9 s first-call problem that got the local embedder switched off.
  - Fact extraction at consolidation: cognition purpose=consolidate returns JSON triples, each with the quoted span it came from; the existing untraceable() check is applied per triple (a triple whose subject/object never appears in the window is dropped). Same-(subject, predicate, scope) with a different object stated by the fact's owner supersedes: append `superseded` and set valid_to on the old fact. Replaces the symmetric 0.5 penalty of flag_contradictions, which currently punishes the correction as much as the error.
  - Entity linking at recall: names of known people/devices/places in the query (from World Model's entity list) pull their current facts into a separate, small 'facts' block rendered before the episodic block.
  - Person digest: at sleep, a ~150-token per-person summary regenerated from current facts (never from prose), delivered as a protected block when that person is the speaker; supersedes the regex user_profile facet.
  - Forgetting: retention score = f(recency, access count, number of linked facts, tombstones); prune episodic below the score, never facts with live links; keep the forget_window tool.
  - Recall budget raised to ~1.0 s and prefetched: Orchestration issues the recall on percept.text.received (for voice, on the STT partial) in parallel with session setup, so the model waits on nothing.
- **interfaces:** Unchanged topics memory.store/retrieve/forget/stored/consolidated; add memory.fact.stored/superseded and a `facts` field on memory.retrieve.reply; the `working` kind is served from the thread keyed by (person, channel) as well as session_id.

###### 2. worldmodel

- **name:** worldmodel
- **from:** keep + merge of persona.user_model into it; selfmodel.py becomes a fold of a durable self:model stream
- **responsibility:** Two durable projections. Self Model: state (identity/SOUL hash, registered tools -- written from tool.registered, which is the missing wire -- providers, active goals, restarts) and estimated quantities (competence Beta posteriors per task_type and per (task_type, strategy) with time decay; calibration as expected calibration error; per-tool p(ok) and latency quantiles from action.result; per-provider quality per purpose from verify.result; expected cost per task type; staleness per fact). Environment State: entities (people, rooms, devices, cameras, calendars, vehicles) with observed value, last_seen, source, confidence and typical change rate; fed from action.result of home/media/pim tools, camera.event, tv.state, voice speaker identification, and calendar reads.
- **key algorithms or methods:**
  - Beta(alpha, beta) per task_type with exponential forgetting (weight = 0.5^(age/half_life)); compute_gaps returns areas ranked by posterior mean minus a confidence term, with sample counts -- today it returns [] and Curiosity sees 0.6 everywhere.
  - Staleness = age / typical change rate learned per entity from its observation history; a 'world now' block renders only entities under a staleness threshold and marks the rest as unknown, so the model never reasons on a device state from yesterday as if current.
  - Self summary rendered from the posteriors with sample counts ('patch:memory 62% over 13, overconfident'), and a 'what I am bad at' line computed, not copied from limitation strings.
  - self:model and world:home as Ledger projections with snapshots every N events; rebuilt on boot in milliseconds.
- **interfaces:** Keep self.summary/self.gaps/world.env.query; add world.entity.observed (published) and self.estimate.request/reply (a posterior for a task_type, for Planning risk and Cognition tier choice); PERSONA_USER_MODEL_UPDATED becomes a memory.fact.stored with subject=person.

###### 3. planning

- **name:** planning
- **from:** keep; model.py, decomposer.py, reground.py, service.py extended
- **responsibility:** Goal trees for any kind of work, not only code: Goal -> Milestone -> Task, each node with acceptance criteria (a checklist Verification can evaluate), a checkpoint ref, a risk estimate from the Self Model, and a waiting_on condition. Owns re-planning: given the tree and what changed since the last checkpoint, revise the subtree and log plan.revised.
- **key algorithms or methods:**
  - Decomposition prompt produces typed nodes {kind: patch|research|action|question|wait, acceptance: [...], depends_on} with kind 'action' scoped to tool families (home, pim, web, files) so a household goal decomposes without naming a repo path.
  - WAITING status with wake condition (until: ts | event: topic+filter | human: question_id); the Kernel scheduler publishes task.wake; a human answer arrives as a task.answer event and resumes; project sessions wait on children by subscribing to task.completed/failed, never through the work queue (avoids the documented workers=1 deadlock).
  - Checkpoint critic: at every progress note, Verification's trajectory scorer is asked, against the node's acceptance criteria, for {on_track|drifting|blocked, unmet: [...], next}; two consecutive drifting verdicts trigger re-planning rather than continuing.
  - Re-grounding as re-planning: replace STILL_VALID yes/no with a structured revision call on the cheap tier that returns the revised subtree; verdict voting (3 cheap samples, majority) for the yes/no cases that remain.
  - Risk from the Self Model: a node whose task_type posterior mean is below threshold or sample count is low is scheduled with plan mode and a human gate; high-competence nodes run autonomously (reversibility-weighted oversight, principle 4.10, now data-driven).
- **interfaces:** Keep plan.proposed/approved/revised, task.*; add task.waiting, task.wake, task.answer, plan.node.verified. Rollup stays a pure function of children.

###### 4. orchestration

- **name:** orchestration
- **from:** keep; switch on what exists, add threads and checkpoint hooks
- **responsibility:** One loop, unchanged shape: gather -> think -> act (through Guardian) -> verify. Runs persistent conversation threads, progress-note compaction, isolated delegation, and publishes checkpoints the critic and resume can use.
- **key algorithms or methods:**
  - Progress-note re-grounding on (reground_every_steps=3, keep_recent_steps=2); the note becomes the carried note across attempts and the checkpoint the critic scores.
  - Persistent thread per (person, channel): last N turns kept in Orchestration's WorkingMemory, placed before the memory block; compaction of the thread by the same progress-note mechanism when long.
  - Delegation on: fresh-context sub-session for research with summary-only return (exists behind `delegation`); parallel read-only batches on.
  - Escalation: attempt >= 2 or a failed critic verdict routes the next think to the strong tier (escalate_from_attempt=1, `_tier` exists).
  - Speculative recall: memory and world-now blocks fetched on percept, not on think.
- **interfaces:** Unchanged; task.progress already exists and becomes the checkpoint event; add task.checkpoint.scored consumed from Verification.

###### 5. growth

- **name:** growth
- **from:** merge of learning + reflection + curiosity (topics preserved; packages folded into simorgh/growth/ with estimate.py, diagnose.py, policies.py, explore.py, monitors.py)
- **responsibility:** The single closed loop over a versioned policy store `growth:policies`. Estimate: outcomes -> posteriors (CompetenceTable, calibration, reliability). Diagnose: at sleep, cluster failures by (task_type, verify failure kind, denied tool, drift kind, critic 'unmet' items) into lesson candidates with evidence refs. Propose: one of four typed artifacts -- a task-type rule (a line rendered by scaffolds for that task_type), a skill, a routing change (purpose or task_type -> tier), or a code patch (through the existing worktree landing). Evaluate: run the candidate against a held-out case set for that task_type (trial suite cases and benchmark cases tagged by task_type) in a worktree; adopt only on no regression plus at least one motivating case fixed. Adopt: through action.proposed(tool=policy_adopt) so Guardian gates it; the policy becomes active and is read by scaffolds.render, the Router and the skills catalog. Retire: TTL and re-evaluation; a policy whose task_type posterior falls after adoption is reverted (bounded rollback, same shape as simloader). Explore: Thompson sampling over competence posteriors and over world-model unknowns chooses idle work.
- **key algorithms or methods:**
  - Thompson sampling: per area draw from Beta(alpha, beta), pick the lowest draw (largest expected gain), then the existing 'ask the model to propose within this target' step; boredom still flattens by raising the temperature. Replaces the constant-gap softmax.
  - Failure clustering: group terminal failures in the window by a small feature vector (task_type, verify check that failed, tool denied, critic unmet item text hashed); a cluster with >= 3 members and rate above the type's baseline becomes a lesson candidate. Deterministic, no model call; the model is asked only to phrase the rule.
  - Sequential adoption test: for cheap policies (rules, routing) the eval is the held-out set; for skills and patches it is the full gate plus the held-out set; a candidate never becomes active on its motivating case alone.
  - Policy artifact schema: {id, kind, task_type|purpose, body, evidence_refs, evaluated_on, baseline, result, adopted_at, ttl, status}. Task-type rules are the first kind because they close the loop with the least machinery: Reflection's lesson becomes a line every future session of that type reads.
  - Exploration targets extended beyond repo areas: unanswered recurring questions from threads, stale high-query facts, devices never probed, skills never exercised.
- **interfaces:** Keeps publishing learn.*, reflect.*, curiosity.* so no consumer changes; adds growth.policy.proposed/adopted/retired and growth.lesson.found; consumes task.*, verify.result, action.result/denied, plan.node.verified, system.tick.sleep/idle, self.estimate.reply.

###### 6. cognition

- **name:** cognition
- **from:** keep; router.py and config.py gain a purpose -> tier map; providers gain native tool calling (other lens, prerequisite)
- **responsibility:** Unchanged: routing, budgets, compaction, prompt assembly. Adds: tier by purpose and by escalation; verdict voting for reground/verify; a 'world now' protected block for household turns; the person digest as a protected block when the speaker is known.
- **key algorithms or methods:**
  - purpose -> ordered provider list from config; strong tier for plan/decompose/critique/verify-on-failure, cheap tier for reground/consolidate/classify/critique-on-success; escalation overrides per call (the `order` parameter exists).
  - Majority vote of 3 cheap samples for yes/no verdicts; a split vote is 'unknown', which already defers to the existing plan.
  - Prompt assembly order: constitution, voice, self summary (from posteriors), person digest, world now, active task-type rules (from growth policies), task rules, thread, memory facts, memory episodic, conversation.
- **interfaces:** Unchanged cognition.think; payload gains optional `tier` and `vote` fields.

###### 7. persona

- **name:** persona
- **from:** keep, minus user_model.py (moved into memory facts / worldmodel people entities)
- **responsibility:** Mood, emotion floor, voice register, proactive-sharing pacing. Stays out of the call path.
- **key algorithms or methods:**
  - Mood continues to modulate exploration temperature and voice register only.
- **interfaces:** Unchanged persona.voice, persona.state.changed; persona.user_model.updated retired in favour of memory.fact.stored.

###### 8. verification

- **name:** verification
- **from:** keep
- **responsibility:** As today plus the checkpoint critic (trajectory scoring against acceptance criteria mid-task) and the held-out eval runner used by the growth loop's adoption test.
- **key algorithms or methods:**
  - Acceptance-criteria checklist evaluation returning unmet items, with insufficient-evidence preserved.
  - Eval runner: given a policy candidate and a task_type, run the tagged case set in a worktree and report pass/fail per case against the stored baseline.
- **interfaces:** Add verify.checkpoint.request/reply and verify.eval.request/reply.


#### merges

- learning + reflection + curiosity -> growth (one loop, one policy store; their published topics are preserved so nothing else changes)
- persona.user_model -> memory facts with subject=person, surfaced through worldmodel's people entities and a per-person digest
- memory.WorkingMemory (unfed) + orchestration session transcript -> one working-memory tier owned by Orchestration, keyed by (person, channel) and by task

#### additions

- memory:facts stream with supersession and provenance; fact extraction at consolidation (JSON triples, per-triple traceability)
- Hybrid BM25 + dense retrieval with rank fusion; background embedding at store time; persisted vector projection
- self:model as a durable projection of estimated quantities (Beta posteriors, calibration, tool reliability, provider quality per purpose); compute_gaps implemented; capabilities.tools written
- world:home environment-state projection and a 'world now' prompt block
- Goal-tree nodes with acceptance criteria; WAITING status with scheduler wake-ups; project sessions that wait on children by event
- Checkpoint critic (Verification at every progress note)
- growth:policies store with four artifact kinds and eval-gated adoption through Guardian
- Thompson-sampled exploration over posteriors and world unknowns
- Purpose -> tier routing and verdict voting
- A recall/continuity eval built from real ledger conversations (recall@k on labeled questions) and a resume-after-kill eval for long tasks

#### deletions or freezes

- Retire learning/pipeline.py PatchPipeline and the self_patch.draft/skill.draft tool names: unreachable and superseded by worktree landing through Orchestration (docs/plans/worktree-landing-design.md)
- Freeze the regex police family in orchestration/session.py (invented_markers, unhonoured_marker, _transcript_echo, claimed_to_commit, promised_behaviour, claimed_tv_act, claimed_to_note_a_pronunciation): no new members; delete each as native tool calling makes it unreachable
- Replace memory/store.py::flag_contradictions' symmetric penalty with supersession; keep the contradictions stream read-only for history
- Freeze persona/user_model.py regex extraction once facts exist
- Freeze curiosity's repo-area-only target space as the default; household/world targets first
- Delete src/ (v1) from the tree; it still aims the decomposer's DEFAULT_SOURCE_ROOTS at retired code
- Stop rendering limitation strings from patterns into the self summary once posteriors render 'what I am bad at' from data


### capability programs

##### 1. reasoning

- **capability:** reasoning
- **current state:** One model at low reasoning effort for every purpose (long-run-context-design.md section 1); tool use through free-text markers, one action per step, regex police for fabricated results; no planner/actor/critic separation; verification only at task end; reground and review verdicts from one sample; the plan profile exists (read-only, 8 steps) but is used only for projects.
- **method:** Separate the roles by purpose and route by tier: plan/decompose/critique/verify-on-failure on the strong tier, act on the cheap tier, escalate on a failed attempt or a drifting critic verdict (cognition/router.py order parameter and session.py::_tier already exist). Write acceptance criteria before acting (the plan profile's output becomes the task's checklist). Critic at checkpoints via Verification's trajectory scorer. Majority vote of three cheap samples for yes/no verdicts. Native tool calling with parallel read batches (prerequisite from the tool lens) so reasoning tokens are not spent on protocol compliance.
- **how to measure:** The benchmark unit already in the tree (GAIA-L1, BFCL, SWE-bench lite) per model/config; the trial suite pass rate; steps and cost per solved task; critic precision (fraction of 'drifting' verdicts followed by a failure if ignored) read off task streams.
- **first increment:** Config only: purpose -> tier map with review/decompose/reground on a stronger Together model, escalate_from_attempt=1; run the trial suite and one benchmark wave before and after; record in docs/findings/.

##### 2. long tasks

- **capability:** long tasks
- **current state:** Transcript grows unbounded until context_too_large; progress-note re-grounding, delegation, clean revisions and parallel reads are built and switched off (orchestration/config.py); retries carry a mechanical note; a project is COMPLETED when children exist and nothing waits on them; no waiting states or wake-ups; verification only at terminal; the Self Model is rebuilt from nothing at each boot.
- **method:** Checkpointed goal trees. Data: task:<id> gains checkpoint events (the existing task.progress note plus acceptance status, open files, waiting_on); Planning nodes carry acceptance criteria and depends_on; a WAITING status with wake condition (until|event|human) and Kernel scheduler wake-ups; project sessions wait on children via task.completed/failed events, never the queue. Loop: think -> act -> every 3 steps write the note, replace the transcript, ask the critic against the acceptance criteria; two drifting verdicts -> re-plan the subtree; the note is what the next attempt or the next day starts from. Delegation with isolated context for research legs so exploration noise never enters the parent's context.
- **how to measure:** Long-run benchmark arm (tools/bench_instance.py waves exist): completion rate of tasks needing more than one attempt; context tokens per step (must plateau, not grow); resume-after-kill success rate (kill the process mid-task in a repo copy, count tasks that finish without redoing steps); wall-clock to completion for a three-day scripted household goal (wait on a calendar event, then act).
- **first increment:** Switch on reground_every_steps=3 and keep_recent_steps=2; make the model's progress note the carried note across attempts (resume.py already reads task.progress); measure tokens per step and multi-attempt completion on the trial suite.

##### 3. environment interaction

- **capability:** environment interaction
- **current state:** 98 tools including home/media/pim/cameras, but no persistent environment state: every household question re-observes; World Model facets are the repository; tool results reach the model as 8,000-char text with no structured state; camera.event and tv.state are published and not folded anywhere the model can read; Home Assistant not configured; MCP exists only as a proposal tool.
- **method:** An environment-state projection (world:home) of entities with observed value, last_seen, source, confidence and a learned typical change rate; fed from action.result of home/media/pim tools, camera.event, tv.state, and voice speaker identification (who is present). Observe-tools return diffs against the last known state ('living room: TV on since 19:02, lights unchanged'). A 'world now' protected block (~200 tokens) for household turns, rendering only fresh entities and naming stale ones as unknown. MCP client in Execution (Guardian still sees every call) for external services rather than hand-written tools. Optional: images to a vision-capable provider are already routed (router.py blind filter); camera snapshots become percepts with a world-entity tag.
- **how to measure:** Staleness distribution per entity (the module map's own handle); fraction of household questions answered from state with zero tool calls; tool success rate and p95 latency per tool from action streams; false-fresh rate (state rendered as current but contradicted by the next observation).
- **first increment:** WorldModel subscribes to tv.state, camera.event and action.result for the home/media tool families, keeps world:home as a projection, and answers world.env.query{what:'home_now'}; Cognition renders it as a protected block for chat/voice; measure how often it is used by counting turns that answer without a tool.

##### 4. user interaction

- **capability:** user interaction
- **current state:** Throwaway session per typed line; no thread; continuity is three similarity recalls with hashed bag-of-words under 0.25 s; user model is two regexes ('I prefer', 'call me'); per-person memory tags exist; corrections are not superseded, only ordered; voice full response 4-17 s with recall on the critical path.
- **method:** Persistent thread per (person, channel) as working memory placed before recall; a fact store with supersession so a correction replaces the old value and the model is told it was corrected; a per-person digest regenerated from facts at sleep, rendered as a protected block when that person speaks; entity-linked facts for names mentioned in the query; speculative recall started on percept (for voice, on the STT partial) so the model never waits on memory; recall budget raised to ~1 s once it is off the critical path. Persona keeps mood and register; the user model becomes facts about people.
- **how to measure:** A continuity regression set built from the ledger's real failures documented in context.py (the two machine names, the corrected birthday) plus new labeled question/answer pairs: recall@k for facts and exact-answer rate for corrections; voice response latency (stt/llm/first_audio already measured); count of 'I don't have that in my notes' answers when the fact exists.
- **first increment:** Feed the existing WorkingMemory from turn.completed keyed by (speaker or 'typed', channel) and render the last 6 turns before the memory block; run the continuity set before and after. Zero new contracts.

##### 5. self-improvement

- **capability:** self-improvement
- **current state:** Outcomes and a real competence table exist but feed only a 300-token summary; strategy.suggest has no caller; Learning's PatchPipeline is unreachable (Health reports it); Reflection's critiques become episodic prose and limitation strings; patterns become task proposals; Curiosity's gap drive is a constant because compute_gaps returns []; self-patches land through worktree + gate + simloader rollback (this part works); nothing changes a prompt, policy, route or skill from experience; the Self Model is not durable.
- **method:** One closed loop in a merged Growth subsystem over a versioned policy store: estimate (Beta posteriors with decay per task_type and strategy; calibration; tool reliability) -> diagnose (deterministic clustering of failures by task_type, verify check, denied tool, critic unmet items; >= 3 members above baseline = lesson candidate) -> propose one typed artifact (task-type rule, skill, routing change, code patch) -> evaluate on a held-out tagged case set in a worktree against the stored baseline -> adopt via action.proposed(policy_adopt) through Guardian -> monitor; retire on TTL or posterior drop, with bounded rollback. Exploration by Thompson sampling over the posteriors and over world unknowns. Rules first because they close the loop cheapest: scaffolds.render reads active rules for the task_type.
- **how to measure:** Competence posterior per task_type over time (the module map's handle) with sample counts; number of adopted policies surviving 30 days vs retired; eval delta per adoption (held-out pass rate before/after); regression count attributed to a policy; exploration yield (fraction of curiosity tasks that raised a posterior).
- **first increment:** Implement compute_gaps from CompetenceTable and write capabilities.tools from tool.registered (two wires, no contracts change); add a growth:rules projection read by scaffolds.render and a policy_adopt tool gated by Guardian; let Reflection's first lesson become a task-type rule only after it passes the trial-suite cases for that type.


### migration path

##### 1. 1. Wire what exists

- **stage:** 1. Wire what exists
- **weeks:** 2
- **does:** compute_gaps from the competence table; capabilities.tools from tool.registered; reground_every_steps=3 and the model's note as the carried note; WorkingMemory fed per (person, channel) and rendered before recall; purpose -> tier routing with escalate_from_attempt=1; delegation and parallel reads on for research/patch. Build the continuity eval set from the ledger and the resume-after-kill trial.
- **unlocks:** Measurable gains on continuity, long-task completion and steps per task with zero contract changes; the eval sets every later stage is gated by.
- **risk:** Low. Behaviour changes are config and two producers; each can be reverted by config. The only subtle one is the thread block changing what the model sees first -- run the continuity set before and after.

##### 2. 2. Memory tiers

- **stage:** 2. Memory tiers
- **weeks:** 3
- **does:** BM25 over real tokens in recall.py; background embedding at store time with a persisted vector projection; hybrid retrieval with rank fusion; memory:facts with supersession and per-triple traceability at consolidation; person digests; entity-linked facts block; recall prefetched on percept with a 1 s budget.
- **unlocks:** Paraphrase recall, corrections that win, per-person continuity, and a memory that gets better the more the family talks to Sim.
- **risk:** Ranking changes silently. Mitigate with the labeled recall set from stage 1 as a gate, keep hashing as the cold floor, and keep every fact's source_refs so a wrong fact can be traced and tombstoned.

##### 3. 3. Self and world as projections

- **stage:** 3. Self and world as projections
- **weeks:** 2
- **does:** self:model as a durable fold with Beta posteriors, calibration, per-tool reliability/latency and per-provider quality per purpose; self.estimate.request/reply; world:home entity projection fed from home/media/camera/tv events; 'world now' and self summary rendered from data.
- **unlocks:** Planning risk, routing and exploration all read real estimates; household questions answered from state; a self summary that says what it is bad at with sample counts.
- **risk:** Medium-low: a stale world block rendered as fresh would mislead the model. Mitigate with the staleness threshold and 'unknown' rendering, and the false-fresh metric.

##### 4. 4. Goal trees, waits and the checkpoint critic

- **stage:** 4. Goal trees, waits and the checkpoint critic
- **weeks:** 3
- **does:** Typed nodes with acceptance criteria (action/question/wait kinds beyond patch/research); WAITING status with scheduler wake-ups and task.answer; project sessions wait on children by event; Verification checkpoint scoring against acceptance criteria; re-planning as subtree revision; verdict voting.
- **unlocks:** Multi-day household and research goals that pause, wake, re-plan and finish; drift caught mid-task, not at the end.
- **risk:** The documented workers=1 deadlock if a wait ever goes through the queue; keep waits event-driven and add the integration scenario from long-run-context-design.md as a gate. Critic false positives could thrash re-planning: require two consecutive drifting verdicts.

##### 5. 5. Growth merge and the policy loop

- **stage:** 5. Growth merge and the policy loop
- **weeks:** 4
- **does:** Fold learning/, reflection/, curiosity/ into growth/ preserving their topics; growth:policies store; failure clustering; task-type rules as the first artifact kind, routing second, skills third, patches through the existing landing; eval-gated adoption via policy_adopt through Guardian; TTL, monitoring, bounded rollback; Thompson-sampled exploration over posteriors and world unknowns.
- **unlocks:** The loop closes: experience changes future behaviour, and only when it demonstrably helps. Idle time improves usefulness to the family, not only the repo.
- **risk:** Highest of the plan: a self-modifying loop with weak evals adopts overfitted rules. Mitigate: no adoption without a held-out case set for that task_type; rules may only add guidance or restrictions; Guardian protects the policy store's own gate; every adoption is a revertible ledger event and a git commit where code is involved.

##### 6. 6. Native tool use and police retirement (dependent on the tool lens)

- **stage:** 6. Native tool use and police retirement (dependent on the tool lens)
- **weeks:** 3
- **does:** Provider adapters honour tools=; parser keeps markers as the floor/Ollama fallback; delete each regex police function as its failure becomes structurally impossible; parallel tool calls native.
- **unlocks:** Reasoning tokens spent on the task, a critic that can trust tool results, and ~600 lines of heuristics gone from session.py.
- **risk:** Provider differences in tool-call formats; keep the marker path as a fallback and gate on BFCL and the trial suite.


**agi honesty:** What this architecture is: a harness around a cloud model. Its reasoning ceiling is the provider's; Sim does not learn at the weight level and the blueprint rightly says so (01-vision section 3). What it can become, and what compounds: (1) a memory that gets better with every conversation -- facts with supersession, per-person digests, hybrid recall -- so the family experiences an assistant that knows them; (2) a world model of the house so answers come from state and actions are diffs, not re-observation; (3) long-horizon autonomy -- goal trees that pause, wake, re-plan and finish over days without a human holding the thread; (4) procedural learning -- skills, task-type rules and routing that are adopted only when they beat a baseline and retired when they stop helping; (5) calibrated self-knowledge -- posteriors with sample counts driving when to ask, when to escalate and when to act alone. Together these give 'more general' a concrete meaning for a household agent: more task types with measured competence above threshold without per-task engineering, more of the family's world modelled, longer autonomous horizons with fewer interventions, and no safety regressions -- each a number in the ledger, as the blueprint's own AGI stance asks. What it cannot deliver: general intelligence independent of the provider, open-ended learning of new cognitive abilities, or anything that would justify the word AGI in its usual sense; a strong foundation model plus this harness will look far more capable than the same harness on a weak one, and that gap is the model's, not Sim's. Investments that compound: the ledger and evals (every change measured), the fact store (every conversation improves the next), the world model (every observation saves a tool call), skills and policies (every solved problem reusable), and the safety chokepoint (every new capability inherits the gate). Investments that do not compound: per-incident regex heuristics, more tools without persistent state, more prompt text without a policy store, and a bigger test suite that asserts shape. Honest framing for the creator: build toward 'the most capable, trustworthy, self-improving personal agent on one laptop', measured by its own competence table; if the underlying models keep improving, the harness proposed here is the one that will let Sim absorb that improvement without a rewrite.

**biggest risk of this proposal:** Closing the growth loop before the evaluation harness that must gate it. A self-modifying loop with weak evals will adopt rules, routes and skills that fit their motivating case and quietly regress everything else, and the project's own retrospective (07-post-cutover-review.md section 4) already shows that shape-asserting tests miss exactly this; the trial suite and observer waves are the only things that have ever caught a real blocker. So the order matters more than the content: stage 1's continuity, resume-after-kill and per-task-type case sets are not optional prerequisites, they are the loop's safety mechanism, and no policy kind should be adoptable until its task_type has a held-out set with a stored baseline. The secondary risk is scope drift into a rewrite: the memory rebuild and the growth merge must stay behind unchanged contracts (same topics, same schemas) so the 447-file suite, the boot self-check and the Guardian invariant continue to hold at every commit; the moment a stage requires touching contracts/ and guardian/ together, it has left the proportional path.

