# read:cognition-memory-selfmodel

*Workflow: review · Phase: Read · Agent id: `a76ed2f36101ffa0e` · Tool calls: 55*

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
  
  
  CONCERN: the cognitive core -- Cognition provider router and budgets, prompt/compaction, Memory (episodic/semantic, embeddings, recall), World Model / Self Model, and the growth loop (Learning, Reflection, Curiosity) that feeds it.
  Read simorgh/cognition/ (router, providers/*, budgets, compaction, prompt assembly), simorgh/memory/ (service, store/engine, recall, consolidation, embeddings), simorgh/worldmodel/ (selfmodel.py, facets), simorgh/learning/, simorgh/reflection/, simorgh/curiosity/ (skim the services: what do they subscribe to, what do they emit, and who consumes what they emit -- does anything downstream actually CHANGE behaviour because of a competence estimate, a reflection finding, or a curiosity idea?).
  Questions: What are the embeddings (real model or a hash/bag-of-words floor)? What is recall quality likely to be and is memory ever used in a prompt that matters? Is the "self-improving" claim backed by a closed loop (outcome -> competence -> different behaviour next time), or is it write-only telemetry? Is the provider failover design sound (the Together day cap silently failed over to the Claude CLI once)? Is the floor provider a good idea or does it mask outages? Is there a coherent notion of a conversation/session across chat, voice, and tasks? Evaluate: which of these subsystems earn their existence as separate packages, and which are speculative scaffolding?
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | List Python files and line counts in the cognitive-core packages | == cognition 3 simorgh/cognition/__init__.py 5 simorgh/cognition/providers/__init__.py 15 simorgh/cognition/tokens.py 50 simorgh/cognition/providers/base.py 96  |
| 2 | Bash | Read the module map orientation doc | # Simorgh — Module Map and System Blocks **What this is.** One picture of every major building block, what each one owns, and how they interact — written so a s |
| 3 | Bash | Read cognition router | """Provider failover and selection (docs/blueprint/subsystems/04- cognition.md section 5). Ported from v1 `CognitionRouter`'s failover shape: try each candidate |
| 4 | Bash | Read cognition budget and config | """Per-provider rolling-window spend/call accounting, durable via the Ledger stream `cognition:budget:<provider>` (docs/blueprint/subsystems/ 04-cognition.md se |
| 5 | Bash | Read cognition service | <persisted-output> Output too large (30.3KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 6 | Bash | Read provider base, Together, and Claude CLI providers | """The guaranteed floor (principle 4.5): a stdlib, offline provider that always answers every purpose with a fixed, clearly-labeled template. Never raises -- it |
| 7 | Bash | Read cognition service body |  40 if expected == "tool_calls": 41 return {"kind": "markers", "markers": tuple(payload.get("tools") or ())} 42 if expected in ("edit_blocks", "verdict"): 43 re |
| 8 | Bash | Read rest of cognition service |  330 tool_instructions = _tool_instruction_block(payload) 331 think_messages: list[dict] = [] 332 if protected_text: 333 think_messages.append({"role": "system" |
| 9 | Bash | Read prompt assembler, cognition API and token estimator |  1 """Prompt assembly (docs/blueprint/subsystems/04-cognition.md section 5, 2 "Prompt assembly order"): ordered blocks, each `protected` (never 3 compacted -- p |
| 10 | Bash | Read compaction head and function outlines |  1 """The graduated context-compaction pipeline (docs/blueprint/subsystems/ 2 04-cognition.md section 5, "Compaction pipeline"; docs/KnowledgeBase/ 3 harness-01 |
| 11 | Bash | Read Ollama provider and check native tool passing in providers |  1 """Ollama provider: a local model as the last resort before the floor. 2 3 The creator, 2026-09-15: "give Sim the option of using Ollama as last-resort 4 fal |
| 12 | Bash | Read memory embedders and config |  1 """Where an embedding comes from -- and what each source can actually do. 2 3 `embed.py` hashes tokens into buckets. It needs no network, no key and 4 no pac |
| 13 | Bash | Read memory service and recall | <persisted-output> Output too large (33.2KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 14 | Bash | Read memory store head and outline |  1 """The memory engine (docs/blueprint/subsystems/05-memory.md sections 4-5): 2 episodic/semantic/procedural records as one-event-per-item Ledger streams 3 (`m |
| 15 | Bash | Read memory consolidation and API |  1 """Consolidation on `system.tick.sleep` (docs/blueprint/subsystems/05- 2 memory.md section 4): flag contradictions, prune each durable kind, and 3 -- if a re |
| 16 | Bash | Inspect the live data directory, ledger layout and config file | total 3808 drwxr-xr-x@ 26 saeed staff 832 Sep 18 15:04 . drwxr-x---+ 100 saeed staff 3200 Sep 18 18:39 .. drwxr-xr-x@ 2 saeed staff 64 Sep 9 21:27 benchmark drw |
| 17 | Bash | Read memory service body from saved output |  42 async def start(self, ctx: Context) -> None: 43 self._ctx = ctx 44 # Live-caught as a class 2026-09-08: every service is handed its 45 # own `[section]` fro |
| 18 | Bash | Read recall index and retrieve/scoring |  1 """What `retrieve` scans, so that it stops scanning everything. 2 3 The problem this exists for, measured on a real jsonl ledger before it 4 did (2026-09-10, |
| 19 | Bash | List ledger streams and count events in cognitive-core streams | action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl action%3A00085e844cff.jsonl action%3A0009062c07cc.jsonl action%3A000947307a9 |
| 20 | Bash | Read the self model |  1 """The Self Model. Identity is real, loaded and hashed from 2 `docs/SOUL.md`. As of Phase 4 Wave 2 the other sections (competence, 3 limitations, change_hist |
| 21 | Bash | Read world model service and capability facet |  1 """World Model as a `Subsystem` -- env facets (real, this session) plus a 2 live-updating Self Model (identity real from boot; competence, 3 calibration, lim |
| 22 | Bash | Read learning service, competence and outcomes | <persisted-output> Output too large (31.3KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 23 | Bash | Read learning pipeline, strategy, correlator, models and config |  1 """`PatchPipeline` / `SkillPipeline`: the self-patch and skill state 2 machine (spec section 5.2/5.3) -- policy only. Every actual file 3 read/write/test/com |
| 24 | Bash | Read learning service, competence and outcomes from saved output |  44 self._config_from_caller = config 45 self._config = config or Config() 46 self._ctx: Context \| None = None 47 self._competence = CompetenceTable() 48 self._ |
| 25 | Bash | Read reflection service first half |  1 """Reflection as a `Subsystem` (Layer 3, registry.py). Observer only -- 2 never emits `action.proposed`, never writes `self:model` directly (only 3 `self.obs |
| 26 | Bash | Read reflection service second half |  420 421 async def _on_plan_revised(self, message: Message) -> None: 422 # Known simplification: plan_id isn't guaranteed to equal the 423 # project TASK_CREATE |
| 27 | Bash | Read curiosity service first half |  1 """`Service`: wires drives, sampling, idea/project proposal, interests, 2 and sharing into the real `Subsystem` protocol (spec section 5). One 3 exploration  |
| 28 | Bash | Read curiosity service second half, sampler and drives |  330 topic = message.payload.get("topic") or message.payload.get("feed_url") 331 if topic: 332 self._interests.note(topic) 333 await self._append(_INTERESTS_STR |
| 29 | Bash | Find external consumers and producers of growth-loop topics | == who publishes/subscribes growth-loop topics (eval):1: no matches found: --include=*.py |
| 30 | Bash | Read orchestration context builder |  1 """ContextAssembler (16 section 5): gathers the memory block and the 2 session transcript for one `cognition.think` call. The persona voice and 3 the self su |
| 31 | Bash | Measure sizes of hot ledger streams and stream-name distribution | -rw-r--r--@ 1 saeed staff 1608128 Sep 18 17:09 streams/cognition%3Abudget%3Atogether.jsonl -rw-r--r--@ 1 saeed staff 2482677 Sep 18 17:13 streams/cognition%3Aca |
| 32 | Bash | Find how the ledger read path is implemented | simorgh/ledger/api.py:74: async def read(self, stream: str, *, from_seq: int, limit: int \| None) -> list[Event]: ... simorgh/ledger/api.py:80: async def read_sn |
| 33 | Bash | Find who consumes growth-loop events and whether the budget fields Curiosity reads exist | == external producers/consumers of growth-loop topics (outside learning/reflection/curiosity/contracts) simorgh/guardian/service.py:104: topics.REFLECT_DRIFT_DE |
| 34 | Bash | Inspect the JSONL backend read path | 138: 138 def _read_mark(self, stream: str) -> int: 254: 254 def _read_index(self) -> dict[str, _StreamMeta]: 260: 260 raw = json.loads((self.root / "index.json" |
| 35 | Bash | Measure budget replay cost, curiosity tick composition, outcome counts, and memory tag distributions from the live ledger | budget:together replay: 6991 events in 13.1 ms curiosity ticks total 161096 last-20000 reasons: {'autonomy_paused': 20000} mean interval last 2000 ticks: 3.02 s |
| 36 | Bash | Time the filesystem scan done per self-summary request and read curiosity defaults | list_capability_areas: 19 areas in 1.0 ms (runs on every self.summary request, i.e. every think) modules_by_area: 380 modules in 11.1 ms (Curiosity's capability |
| 37 | Bash | See how sessions are minted across chat, voice and tasks | == session minting simorgh/orchestration/worker.py:154: self.worker_id = worker_id or f"w-{uuid.uuid4().hex[:8]}" simorgh/orchestration/worker.py:295: session = |
| 38 | Bash | Check floor handling, escalation wiring and the marker parser | == floor handling in orchestration/voice/interface simorgh/orchestration/worker.py:470: if outcome.floor: simorgh/orchestration/worker.py:471: payload["floor"]  |
| 39 | Bash | Check Gemini availability and how learning derives task types and publishes competence | 15:from ..api import ProviderUnavailable 23: def __init__(self, api_key: str \| None = None, model: str = DEFAULT_MODEL, client: Any \| None = None) -> None: 24:  |
| 40 | Bash | Read how learning derives task types and the ledger retention defaults | from simorgh.ledger.client import LedgerClient from .competence import CompetenceTable from .config import Config _MAX_VERIFY_CACHE = 500 class OutcomeRecorder: |
| 41 | Bash | Read what Planning and Guardian do with curiosity candidates, reflection patterns, drift and health findings | 159: topics.INTENT_GOAL_STATED: self._on_goal_stated, 160: topics.CURIOSITY_CANDIDATE: self._on_candidate, 177: topics.REFLECT_PATTERNS_FOUND: self._on_patterns |
| 42 | Bash | Read think reply handling, escalation, and per-line session minting in interface, voice and worker |  # replace the transcript with it, and ask again -- once. session.last_think_error = "" if await self._reground(session, forced=True): think_reply = await self. |
| 43 | Bash | Read reflection defaults, native tool tag unwrapping and the marker hint format | 19: drift_emit_threshold: float = 0.6 22: critique_max_tokens: int = 400 28: distillation_enabled: bool = True 29: max_distillations_per_day: int = 3 32: patter |
| 44 | Bash | Measure source/test size and recent commit activity per cognitive-core package | == test lines per package (eval):1: no matches found: tests/simorgh/test_cognition*.py (eval):1: no matches found: tests/simorgh/test_cognition*.py cognition sr |
| 45 | Bash | Measure outcome type mix over time, failover call costs and reflection output volumes | last 300 outcomes by type: [('unknown', 299), ('patch:simorgh/interface', 1)] first ts 1789014580.9088352 last ts 1789776569.536758 claude_code_cli budget event |
| 46 | Bash | Read how task types are derived and the live rendered self model |  Nothing was missing: this already read the same `task:<id>` stream for the kind and the subject, with `limit=1`. The whole stream carries the created timestamp |
| 47 | Bash | Locate test files per cognitive-core package and count them | __init__.py __pycache__ benchmark bus cognition contracts curiosity execution guardian helpers.py integration interface kernel learning ledger memory orchestrat |
| 48 | Bash | Read Planning handlers for goals, curiosity candidates and reflection patterns |  async def _on_goal_stated(self, message: Message) -> None: p = message.payload result = await self._intake.on_goal_stated( goal=p["goal"], origin=p["origin"],  |
| 49 | Bash | Read how Planning and Guardian react to drift and health findings |  async def _on_drift_detected(self, message: Message) -> None: """Reflection's `reflect.drift.detected`: flags the drifting task's project so its remaining PEND |
| 50 | Bash | Read chat session construction, session restoration and floor handling in the orchestration loop |  unchanged: every `TASK_*` handler this fires (`_on_task_started` et al. in `simorgh.planning.service`) checks `task is None` first, so an id Planning never cre |
| 51 | Bash | Check whether interface or voice keep a dialogue history across turns | 29:The readline history file (originally also descoped) landed later, 33:text instead of moving a cursor or recalling history, corrupting 35:(history recall, in |
| 52 | Bash | Check ledger retention defaults, user-profile persistence and how many sites special-case the floor | == retention defaults 5:Policy is per stream prefix: a duration ("7d", "90d") or "forever". 6:- Per-id streams (`trace:<id>`, `dead:<type>`) under a duration ar |
| 53 | Bash | Trace what happens to a floor reply on a chat turn | 31: return Outcome("completed", result_summary=text, floor=False) 32: return await self._verify_then_finish(session, text, floor=False) --- how a floor chat rep |
| 54 | Bash | Sample a self-critique memory and check whether critiques compete with chat in the recency recall | sample self_critique episodic content: 'Honest final status: **no source change was applied, and the task is not complete.**\n\nWhat I did this session:\n- Veri |
| 55 | Bash | Confirm user-model persistence, working-memory producers and native tool passing | == persona user model persistence 28:# inline exceeds 4096` out of `ledger.append` -- AFTER the bus 92: found.append(("preference", value)) 97: found.append(("p |

## Structured reply

**concern:** Cognitive core: Cognition (router/providers/budgets/prompt/compaction), Memory (store/recall/embeddings/consolidation), World Model / Self Model, and the growth loop (Learning, Reflection, Curiosity) -- whether it closes into changed behaviour, whether failover and the floor are sound, whether a session is coherent across chat/voice/tasks, and which packages earn their existence.

**summary of what is actually there:** Every model call goes through simorgh/cognition/service.py::_on_think: a PromptAssembler (assembler.py) makes three sequential bus requests (persona.voice, self.summary, and for chat world.env.query user_profile) to build protected system blocks, then flattens the caller's whole message list into ONE string of "[role] content" lines (assembler.py:70) which is sent as a single role:user message (service.py:339-340); tools are never passed to a provider (service.py:358 `tools=None`) -- tool use is a hand-rolled first-line "NAME: argument" marker protocol (service.py:67-93, parser.py:235-278, orchestration/tools.py:669-690). The Router (router.py) tries together -> claude_code_cli -> gemini -> ollama -> floor with a shared deadline, per-candidate time slices, a 30 s cooldown, one transient retry and a truncation retry; RollingWindowBudget (budget.py) replays the provider's whole `cognition:budget:<name>` ledger stream on every status/can_spend call. The live config (~/.simorgh/simorgh.toml) adds only an Ollama chat-only fallback; no routes, so `tier: strong` escalation is a no-op. Memory (memory/) stores every chat turn as an episodic record (service.py:195-250), Curiosity feed items and consolidation distillations as semantic, and skills as procedural; recall is a hashing-trick bag-of-words (embed.py, 256 sha256 buckets; config default `embedder="hashing"`, and the live toml has no [memory] section) over an incremental inverted index (recall.py); orchestration/context.py builds the memory block for every think from three recalls (8 matched + 6 most-recent + 5 per-speaker, capped at 4,000 chars) and that block is the only cross-turn context any channel has, because the CLI mints a uuid per typed line (interface/service.py:943), voice a uuid per spoken turn (voice/session.py:888, pipeline.py:353), and the designed per-session WorkingMemory (store.py:51-95) has no producer. World Model (worldmodel/) serves real env facets (capability map, file index, git state, tool registry, user profile) and an in-memory-only Self Model (selfmodel.py:16-23) rendered into every prompt's protected `self_summary` block, whose competence section is fed live by `learn.competence.updated`; `compute_gaps` is a stub returning `[], []` (selfmodel.py:400-406). Learning's only live path is OutcomeRecorder -> CompetenceTable (rebuilt from `learn:outcomes` at boot) -> the `learn.competence.updated` event; its PatchPipeline/Correlator/strategy code has no publisher and its health() is permanently `degraded` (learning/service.py:98-125). Reflection runs a per-task DriftTracker plus an LLM drift review at task end, an LLM critique for patch/skill/research/project tasks that is written into episodic memory, calibration and pattern mining on an hourly pass, distillation of solved tasks into `task.create{kind:skill}`, denial mining, and the domain alert/digest router; Planning consumes its patterns and drift, Guardian tightens posture on drift/critical health. Curiosity runs on the kernel's 3 s idle tick: gates on pause/auto-off/backlog/cooldown/budget, then samples a code area by four "drives", asks Cognition for an idea, and publishes `curiosity.candidate` which Planning turns into tasks; every tick, taken or skipped, is appended to `curiosity:ticks`.

### strengths

- Provider failover is genuinely battle-hardened and it works in production: router.py shares one deadline across candidates (`_share_of`, router.py:337-357), stamps the cooldown when the failure happens (router.py:207-212), records billable spend on failed calls (router.py:230-236, together.py `billable=`), and retries a reasoning-only truncation with doubled room (router.py:271-330). Measured from ~/.simorgh/ledger `cognition:calls`: 9,379 think calls, 0 floor replies.
- Recall is O(query buckets), not O(store), and provably identical to the dense path: recall.py KindIndex keeps a cursor into the append-only stream and an inverted sparse index (recall.py:127-185), with `sum()` used deliberately so the indexed score equals the full-scan float (recall.py:147-171). At 2,746 episodic records this is far inside the 0.25 s budget.
- Consolidation has a real fabrication guard, not just a prompt: `untraceable()` (memory/consolidation.py:78-111) refuses to store a distillation that names files, shas or identifiers absent from the transcript, and the service logs the refusal (memory/service.py:280-287). That is the right shape for an honesty check in a system that writes its own memory.
- Per-provider budgets are durable across restarts because they are a fold of the Ledger (budget.py:30-33), and the Together provider prices cached vs uncached tokens from the response itself (together.py:170-215) rather than trusting a static table -- the cheap primary really is cheap: 6,991 Together calls cost $4.56 in total.
- Autonomy is bounded in practice, not just on paper: Curiosity's `min_explore_interval_seconds`, backlog gate and `auto off` (curiosity/service.py:394-426) hold -- the last 20,000 ticks in the ledger are all `skipped_reason: autonomy_paused`, i.e. nothing spent.
- Reflection -> Planning is a closed loop in the 'make work' sense: mined patterns (`reflect:patterns`, 3 events) and distillations (`reflect:distillation`, 7 `proposed` events) become real `task.create`/`task.created` via planning/service.py:264-266 and reflection/service.py:386-389; Guardian reacts to drift and critical health (guardian/service.py `_on_drift_detected`, `_on_health_finding`).
- The Together provider is stdlib urllib with a fixed endpoint and a transport seam (together.py:128-160), and `MIN_REASONING_MAX_TOKENS` (together.py:56-66) encodes a lesson learned from a real billed-and-useless failure rather than a guess.

### findings

##### 1. The self-improvement loop is open: competence is polluted by chat turns, reaches the model only as one prompt line, and steers nothing

- **kind:** wrong-design
- **severity:** critical
- **claim:** Outcome -> competence -> different behaviour does not exist today: 88.5% of recorded outcomes are task_type 'unknown' (every chat turn), the only consumer of a competence estimate is a rendered line in the self-summary prompt block, `self.gaps` always returns nothing, and `learn.strategy.suggest` has no publisher -- so Learning is write-only telemetry that surfaces in every prompt as 'Competence: unknown 97% (2466)'.
- **evidence:**
  - ledger measurement: `learn:outcomes 2714 events; by (type,succeeded): [(('unknown', True), 2403), (('research', False), 65), (('unknown', False), 63), (('research', True), 60), (('patch', True), 44), (('patch', False), 37) ...]`; `with strategy: 0 with stated_confidence: 0`; `last 300 outcomes by type: [('unknown', 299), ('patch:simorgh/interface', 1)]`
  - ~/.simorgh/worldmodel/self/SELF.md (live, v42, 2026-09-18 17:09): `## How well I do it\n- unknown 97% (2466)`
  - simorgh/learning/outcomes.py:83-91 -- task_type defaults to "unknown" and is read from `task:<id>`'s first event's `kind`; a chat turn's task_id is its per-line session uuid (orchestration/worker.py:402-405) which Planning never `created`, so every chat turn is an 'unknown' success
  - simorgh/worldmodel/selfmodel.py:309-313 -- the competence section rendered into the protected `self_summary` block (cognition/assembler.py:58-60) sorts by samples, so 'unknown' is the first row
  - simorgh/worldmodel/selfmodel.py:400-406 `compute_gaps` returns `[], []`; simorgh/curiosity/drives.py:37-40 `_gap` falls back to `_UNKNOWN_AREA_GAP = 0.6` for every area -- the 'gap' drive is a constant
  - simorgh/learning/service.py:98-103 (and my grep of simorgh/ outside learning/: no reference to LEARN_STRATEGY_SUGGEST) -- nothing publishes `learn.strategy.suggest`; simorgh/learning/strategy.py:9-23 documents that no outcome ever carries a strategy
- **why it matters:** This is the headline claim of the project ('self-improving'). As built, the measured competence never changes provider choice, tool choice, step budget, escalation, or which area Curiosity explores; the single place it reaches the model is a line that is both wrong (chat turns are not a task type) and, after a restart, the ONLY competence line the model sees. A senior reviewer would call this an unclosed loop, not a self-improving agent.
- **recommendation:** Pick one concrete behaviour to close the loop on and wire it end to end before adding anything else: e.g. record outcomes only for Planning-created tasks (skip kind='chat' in OutcomeRecorder, as memory/service.py:217-222 already does for episodic writes), and have orchestration/session.py::_tier consult `CompetenceTable.success_rate(task_type)` to choose `tier: strong` or a higher step cap when the rate for that type is below 0.4 with >= 5 samples. Delete `compute_gaps` and the `gap` drive until a producer exists.
- **confidence:** 0.95

##### 2. Failover to the Claude Code CLI is invisible to the budget model and has cost 20x the primary in total

- **kind:** wrong-design
- **severity:** high
- **claim:** The second candidate in the default order has no price, no spend cap and an unknown per-call cost, so neither the per-request `max_cost_usd` gate nor the rolling spend cap can ever refuse it -- and the ledger shows 1,034 CLI calls reported at $99.32 against 6,991 Together calls at $4.56.
- **evidence:**
  - ledger measurement: `claude_code_cli budget events: 1034 total reported cost: $99.32`; `together budget events: 6991 total cost: $4.56` (i.e. ~$0.096/call vs ~$0.00065/call); `cognition:calls` by (purpose, provider): `('draft','claude_code_cli') 526, ('review','claude_code_cli') 287, ('chat','claude_code_cli') 214`
  - simorgh/cognition/config.py:96-99 -- `"claude_code_cli": ProviderConfig(max_calls=..., window_seconds=18_000.0, timeout_seconds=180.0)`: no `max_spend_usd`, no `price_in/out`
  - simorgh/cognition/budget.py:85-92 -- `estimate_cost` docstring: providers with no configured price 'estimate to 0.0, so this never blocks them'; router.py:131-134 uses that estimate for the per-request `max_cost_usd` gate (chat's cap is $0.05, config.py:22 -- every CLI chat call exceeds it and is never refused)
  - simorgh/cognition/router.py:139-140 -- a candidate skipped because `can_spend` is false is skipped with no log or ledger event; the only human-visible signal is the provider-changed UI notice (service.py:508-537), which fires once per switch
  - simorgh/cognition/providers/claude_code.py:83-92,101 -- every call spawns a fresh `claude -p ... --disallowedTools "*"` process in a temp dir; `tools` and `max_tokens` are ignored; `input_tokens=0, output_tokens=0` reported (line 149), so the CLI's budget can only count calls
- **why it matters:** The design intent ('Together is Sim's LLM now') is right for one family on one laptop; the failover undermines it. A day cap on the cheap provider silently promotes a 5x slower, 150x dearer, subscription-quota-burning backend that the budget subsystem cannot see, and 'review' -- the most frequent autonomous purpose -- goes there too. The 2026-09-11 incident in config.py:78-84 is the symptom; the structural cause is a provider with no price in a system whose only guard is price.
- **recommendation:** Give `claude_code_cli` `only_purposes = ["draft"]` (or drop it from `provider_order` by default) and put a same-cost-class provider second (a second Together model via `backend = "together"`, or Gemini flash with a key). Give the CLI a nominal `price_in/price_out` and a `max_spend_usd` so both gates apply, and log `cognition.provider_skipped_budget` at router.py:139 so a budget-driven failover is on the ledger like a failure-driven one.
- **confidence:** 0.9

##### 3. Curiosity appends a ledger event every 3 seconds while doing nothing: 161k events, 45 MB of 'autonomy_paused'

- **kind:** bug
- **severity:** high
- **claim:** `_record_tick` is called on every skipped idle tick, the idle tick fires every 3 s, and `curiosity:` streams have no retention, so a paused Curiosity has written the largest single stream in the cognitive core (45,068,994 bytes) recording that it did nothing.
- **evidence:**
  - `ls -la streams/curiosity%3Aticks.jsonl` -> `45068994` bytes; `wc -l` -> 161,096 events (vs `cognition:calls` 2.4 MB, `memory:episodic` 1.8 MB)
  - ledger measurement: `curiosity ticks total 161096 last-20000 reasons: {'autonomy_paused': 20000}`; `mean interval last 2000 ticks: 3.02 s`; last record: `{"backlog":0,"picked":[],"proposed":[],"skipped_reason":"autonomy_paused",...}`
  - simorgh/curiosity/service.py:396-403 -- `_run_tick_locked` calls `await self._record_tick(skipped_reason="autonomy_paused")` (and the same for paused/backlog/cooldown/budget) on every idle tick; simorgh/kernel/api.py:40 `idle_tick_cooldown_s: float = 3.0`
  - simorgh/ledger/compaction.py:36 `DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"}` -- no entry for `curiosity:`, so 'no match means forever' (compaction.py:66)
- **why it matters:** This is the same 'ledger growth' shape that produced the 192k-trace-file cleanup, coming from a subsystem that is switched off. It also makes the audit record useless: 99.99% of `curiosity:ticks` carries no information.
- **recommendation:** Record a skipped tick only when `skipped_reason` changes from the previous tick (edge-triggered), and add `"curiosity:ticks": "2d"` to DEFAULT_RETENTION. Ten lines.
- **confidence:** 0.98

##### 4. No native tool calling: tools are a first-line text marker with one positional argument, and the model is never told what a tool does

- **kind:** wrong-design
- **severity:** high
- **claim:** Cognition always passes `tools=None`, the Together/Ollama providers never send a `tools` array, and the model is told only tool NAMES plus a few hand-written argument hints -- so it invents argument shapes, emits its own native `<tool_call>` syntax that has to be unwrapped, and can make at most one call per reply outside a whitelisted parallel set.
- **evidence:**
  - simorgh/cognition/service.py:357-358 `response, floor = await self._router.complete(purpose, think_messages, tools=None, ...)`; providers/together.py:120-131 builds `body` with only model/messages/max_tokens/reasoning_effort (no `tools`)
  - simorgh/cognition/service.py:67-93 `_tool_instruction_block`: 'Tools available this turn: NAMES ... write its name in capitals, a colon, then your argument, as the very first line' -- names only; per-tool `tool_hints` are 'a short, hand-maintained, per-tool addendum' (lines 63-66)
  - simorgh/cognition/parser.py:151-166 `_unwrap_native_tool_tags`: 'GLM-5.3-Flash replied ... <tool_call>SEARCH_CODE: word_count</arg_value>' -- the model uses the tool syntax it was trained on and the parser has to strip it
  - simorgh/orchestration/tools.py:669-690 `to_action_payload` splits the single `argument` by first line / fenced code / JSON rest per tool; simorgh/orchestration/api.py:111-121 -- `marker_corrected`, `claim_corrected`, `invented_corrected` flags exist to send malformed markers back once each
- **why it matters:** A large share of the harness's live-caught bugs (markers mid-sentence, invented tools, wrong JSON shape for propose_mcp_server, fenced code in sandbox args) are symptoms of re-implementing function calling in prose for a model that already speaks the OpenAI tools schema. The Guardian invariant does not depend on the marker protocol -- every call still flows through `action.proposed` -- so the safety argument for keeping it does not hold.
- **recommendation:** Pass the Execution registry's JSON schemas as `tools` on the OpenAI-compatible endpoints (Together and Ollama both accept them) and read `message.tool_calls` back into the same `tool_calls` reply field; keep the marker parser only as the fallback for the CLI provider, which cannot take tools. Do it for the CHAT profile first (34 tools, the primary UX).
- **confidence:** 0.85

##### 5. The Self Model is volatile: a restart forgets competence, limitations and change history, so the prompt's self-knowledge is whatever happened since boot

- **kind:** right-design-undermined
- **severity:** medium
- **claim:** The Self Model is mutated in memory only and never folded from a ledger stream, so the one real self-finding Reflection produced (research overconfident: stated 0.78 vs empirical 0.53) and 44 applied patches are absent from the live model, whose rendered state after one restart is 'bad at: none, changed: none, competence: unknown 97%'.
- **evidence:**
  - simorgh/worldmodel/selfmodel.py:16-23: 'mutations here are in-memory only for this session, not yet a fold of a durable `self:model` Ledger stream across restarts'
  - ~/.simorgh/worldmodel/self/SELF.md (live): `## What I know I'm bad at\n(none recorded yet)` / `## What I've changed about myself (last 10)\n(none recorded yet)` / `Restarts recorded: 1`
  - ledger: `reflect:calibration` 1 snapshot `{"brier": 0.218, "empirical_accuracy": 0.526, "samples": 19, "stated_confidence": 0.78, "task_type": "research"}`; `learn:outcomes` has 44 `('patch', True)`; neither appears in the live model
  - simorgh/learning/service.py:74 rebuilds the CompetenceTable from `learn:outcomes` at start but only publishes `learn.competence.updated` on new outcomes (outcomes.py:127-131), so World Model learns a task type only when one finishes after boot; reflection's CalibrationTable is likewise in-process (reflection/service.py:149)
- **why it matters:** The blueprint's idea -- the Self Model is exactly the fold of a stream -- is the right one and the rest of the system (Learning's CompetenceTable via `ledger.rebuild`) already does it. Leaving the one subsystem whose job is continuity as the one without it means 'what I know about myself' is reset by the loader's own rollbacks and by every `sim.sh` restart.
- **recommendation:** At worldmodel start, fold `learn:outcomes`, `reflect:calibration` and `reflect:self` through the existing pure mutators (they are already `(SelfModel, fields) -> SelfModel`), or have Learning and Reflection re-publish their current tables on `system.started`. Either is a day's work and turns SELF.md into a real record.
- **confidence:** 0.92

##### 6. Reflection's critiques undo Memory's own 'no task text in episodic memory' rule and land in family chat prompts

- **kind:** bug
- **severity:** medium
- **claim:** Memory refuses to store non-chat turns as episodic memory, but Reflection writes every patch/skill/research/project critique into the same episodic kind with no person tag, so they pass the voice-channel ownership filter and compete for the six 'most recent' slots that are a chat's only conversational context.
- **evidence:**
  - simorgh/memory/service.py:217-222 -- `if str(payload.get("kind") or "chat") != "chat": return` ('A task's own model session ends with turn.completed too; its description is not something a person said')
  - simorgh/reflection/service.py:346-349 -- `MEMORY_STORE {"kind": "episodic", "content": critique.what_changed, "tags": ["self_critique", f"task:{task_id}"]}`
  - simorgh/orchestration/context.py:251-254 (recent recall: `query=""`, `kinds=["episodic"]`, k=6, pure recency) and :288-294 (`_theirs` admits any item with no `person:` tag)
  - ledger measurement: `self_critique episodic: 125`; `125 critiques; 122 within 10 min of a human chat turn`; sample content: `'Honest final status: **no source change was applied, and the task is not complete.**\n\nWhat I did this session: ...'`
- **why it matters:** This is the 'one side fixed, the other side undone' shape in miniature: a self-critique about a failed code patch is exactly the text that should never be recalled into a child's spoken turn as 'what we were just saying'. It also skews the recency window that was added specifically to keep corrections ('March 6th, not 4th') in view.
- **recommendation:** Store critiques as `procedural` (or a new `reflective` kind) tagged `origin:reflection`, and have the chat recall in context.py request `kinds=["episodic"]` with `filters={"tags": ...}` that excludes them; five lines in each place.
- **confidence:** 0.9

##### 7. Chat and voice sessions are per-turn task ids; the designed session window (WorkingMemory) has no producer, so 'the conversation' is a global 6-record recency recall

- **kind:** wrong-design
- **severity:** medium
- **claim:** There is no session object that spans turns in any channel: the CLI mints a uuid per line, voice per spoken turn, the orchestration `Session` is a task-attempt record whose `restore_session` reads an empty stream for a fresh id, and Memory's `WorkingMemory` (bounded per-session turns, with config fields) has never had a producer -- so the substitute for dialogue history is the 6 most recent episodic records across all speakers and channels (extends the already-known 'no sliding buffer' finding with where the designed slot is).
- **evidence:**
  - simorgh/interface/service.py:943 `session_id = str(uuid.uuid4())` per typed line; simorgh/voice/session.py:888 and voice/pipeline.py:353 per spoken turn; simorgh/orchestration/worker.py:402-405 `Session(task_id=session_id, kind="chat", ...)`; orchestration/resume.py:112 `events = await ledger.read(f"task:{session.task_id}")`
  - simorgh/memory/store.py:51-75 WorkingMemory docstring: 'nothing in the codebase publishes `memory.store{kind:"working"}` outside tests'; my grep for `"working"` outside simorgh/memory/ finds only the wire enum (contracts/messages/memory.py:9); memory/config.py:15-21 `working_max_turns`/`working_max_chars` bound 'a window that never receives real data'
  - simorgh/orchestration/context.py:36-66 documents the measured consequence (machine names and a corrected birthday lost within one 22-turn session) and the `_MEMORY_RECENT_K = 6` workaround; context.py:292-294 shows the recency window is only speaker-filtered on the voice channel
  - simorgh/learning/outcomes.py:63-71 -- the HTTP path that DOES reuse an id ('send the same id every time') then collides with retry/attempt semantics in `_task_facts`
- **why it matters:** For one family talking to one agent, a dialogue is the primary unit of interaction, and today it is reconstructed from vocabulary-overlap recall plus a recency window shared with every autonomous task. The blueprint already reserved the right slot (working memory keyed by session); building the recency hack instead of wiring it means every channel re-solves continuity differently.
- **recommendation:** Give each channel a stable conversation id (the REPL's existing `self.session_id`; the voice `device`+speaker; the HTTP client id) separate from the per-turn task id, feed `turn.completed` into `WorkingMemory.add(conversation_id, ...)` in memory/service.py, and have context.py ask `kinds=["working"]` with `filters={"session_id": conversation_id}` before the episodic recalls. Keep the per-turn task id for leases and traces.
- **confidence:** 0.85

##### 8. Curiosity's budget throttle reads fields Cognition never sends

- **kind:** bug
- **severity:** medium
- **claim:** `_on_provider_status` reads `budget.remaining_fraction` and `budget.free`, but the provider-status payload carries `calls/max_calls/spend_usd/max_spend_usd/exhausted`, so `worst_remaining` stays None, `_exploration_rate()` is always 1.0, and `budget_backoff_below_remaining`/`budget_stop_below_remaining` are dead config.
- **evidence:**
  - simorgh/curiosity/service.py:231-238 -- `remaining = budget.get("remaining_fraction")`, `free = bool(budget.get("free", False))`
  - simorgh/cognition/service.py:456-460 publishes `"budget": {"window_seconds", "calls", "max_calls", "spend_usd", "max_spend_usd", "exhausted"}`; `grep -rn 'remaining_fraction' simorgh` finds only the Curiosity reader
  - simorgh/curiosity/service.py:480-488 `_exploration_rate` returns 1.0 when `remaining is None`
  - guardian/service.py `_on_provider_status` computes `_fraction_used(p.get("budget"))` from the real fields -- the derivation Curiosity should share
- **why it matters:** The 2026-09-07 'unattended night drained the daily budget' incident was answered with `min_explore_interval_seconds` (which works) while the budget-proportional backoff designed for it has silently never fired. It is a fresh instance of the project's dominant bug shape, in the subsystem that spends money on its own initiative.
- **recommendation:** Compute `remaining = 1 - max(calls/max_calls, spend/max_spend)` from the fields actually sent (or lift Guardian's `_fraction_used` into contracts) and delete the `free` flag, which nothing sets.
- **confidence:** 0.95

##### 9. The recall time budget, not the embedder, is the wrong constant: hashing is forced by a 0.25 s limit on a path whose STT alone takes seconds

- **kind:** wrong-design
- **severity:** medium
- **claim:** Embeddings are a 256-bucket sha256 bag of words with no paraphrase ability (measured 0.000 for 'stop the loop' vs 'halting a runaway iteration'), chosen because `orchestration/context.py` gives the whole recall 0.25 s and a local sentence-transformer costs 47 ms warm; that budget is arbitrary next to 1.8-6.8 s of STT and 1.3-9.5 s of LLM per turn, and it is what keeps the memory that every prompt depends on at vocabulary-match quality.
- **evidence:**
  - simorgh/memory/embed.py:23-32 (hashing trick), simorgh/memory/config.py:64 `embedder: str = "hashing"`; ~/.simorgh/simorgh.toml has no `[memory]` section, so production runs hashing
  - simorgh/memory/embedders.py:6-16: '"how do I stop the loop" vs "halting a runaway iteration" -> 0.000'; memory/config.py:51-63: local MiniLM '24.9 SECONDS on the first call ... warm it is still 47 ms against 3 ms' and 'orchestration/context.py allows recall 0.25 s'
  - simorgh/orchestration/context.py:21 `DEFAULT_TIMEOUT_S = 0.25`; docs/module-map.md section 3: 'stt 1.8-6.8 s ... llm 1.3-9.5 s'
  - simorgh/memory/store.py:175-187 `warm()` already builds the index at boot, so the 24.9 s cold cost is boot-time, not first-turn time
- **why it matters:** Memory is the only cross-turn context (see the session finding), so recall quality bounds conversation quality. The current choice optimises a latency that is a rounding error on the voice path while accepting that a fact phrased differently last week is unfindable.
- **recommendation:** Raise the recall timeout to ~1 s, opt in `[memory] embedder = "local"` (warm at boot via `warm()`), and keep hashing as the fallback the code already has. Separately, consider embedding distilled facts ('Saeed's mini PC is called falcon') rather than raw turn transcripts, which is where paraphrase matters most.
- **confidence:** 0.8

##### 10. The floor provider is an in-band success that 41 sites must special-case, and the purposes/budget table is largely fiction

- **kind:** over-engineering
- **severity:** medium
- **claim:** A 'provider' that always answers with canned text has produced 0 of 9,379 real replies but forced floor-handling into 18 files outside cognition and once cascaded a budget outage into a Guardian lockdown; meanwhile 9 purposes are configured, 4 account for 99.97% of calls, the primary provider overrides `max_tokens_out` to 4,000 while the pre-call cost estimate still uses the configured 512-1,000, and `Budget.require_real` from the purposes table is never read.
- **evidence:**
  - ledger: `floor calls: 0` of 9,379; `grep -rln '"floor"\|floor=' simorgh --include='*.py' | grep -v cognition | wc -l` -> 18 files, 41 sites
  - simorgh/guardian/service.py `_on_health_finding` comment: 'a floor-reply-pinned valence locked the whole session for hours over what was really a budget problem'
  - ledger purposes: chat 4,651 + draft 2,443 + review 2,101 + consolidate 182 of 9,379; plan 1, decompose 1, research/reground/ensemble 0
  - simorgh/cognition/providers/together.py:217-222 `_room_to_answer` -> `max(max_tokens, MIN_REASONING_MAX_TOKENS=4_000)` vs config.py:22-30 (chat 1,000; review 1,000; reground 512) and router.py:131 `estimate_cost(prompt_tokens, budget.max_tokens_out)`
  - simorgh/cognition/service.py:282 `require_real=payload.get("require_real_provider", False)` -- the purpose's own `require_real` (config.py:30 ensemble=True) is never consulted
- **why it matters:** For one laptop the honest answer to 'no model' is an error the caller already handles (`no_real_provider` exists and orchestration/session.py:919-924 turns it into a clean outcome). Making it a successful reply pushes the outage into data that Persona, Reflection, Guardian, Memory and Curiosity each had to learn to recognise -- the module boundaries you built are being paid for by every subsystem re-deriving 'was that real?'.
- **recommendation:** Delete FloorProvider and make every purpose `require_real`; collapse `DEFAULT_PURPOSE_BUDGETS` to chat/draft/review/consolidate and let the Together provider's 4,000-token floor be the configured number so the pre-call estimate matches what is sent.
- **confidence:** 0.8

##### 11. Cognition's 'no real provider' health timer is inverted

- **kind:** bug
- **severity:** low
- **claim:** `_no_real_provider_since` is set to `now` on every floor reply, so `health()` reports degraded only when more than 300 s have passed since the LAST floor reply -- i.e. only once the system has stopped asking, never while it is actively falling to the floor.
- **evidence:**
  - simorgh/cognition/service.py:374 `self._no_real_provider_since = self._ctx.clock.now() if floor else None`
  - simorgh/cognition/service.py:242-247 `elapsed = now - self._no_real_provider_since; if elapsed > 300: return Health.degraded(...)`
- **why it matters:** Has not bitten (0 floor replies on the ledger) but it is the one health signal for the subsystem the whole system depends on, and it is wired backwards; if the floor is kept, this is what would tell the operator.
- **recommendation:** Set the timestamp only when it is None (`self._no_real_provider_since = self._no_real_provider_since or now` on floor, `None` on a real reply), or drop it with the floor.
- **confidence:** 0.95

##### 12. RollingWindowBudget replays its whole stream on every candidate check and the stream is never truncated

- **kind:** right-design-undermined
- **severity:** low
- **claim:** `status()` reads the full `cognition:budget:<provider>` stream on every `can_spend` (once per candidate per think), four times every 30 s, and on each provider change; the 24 h window is computed over a file kept forever, currently 6,991 events / 1.6 MB / 13 ms per replay and growing linearly.
- **evidence:**
  - simorgh/cognition/budget.py:55-60 `events = await self._ledger.read(stream_for(self._provider))` with no `from_seq`; callers router.py:139 (`can_spend`), service.py:448 (`[await b.status() for b in self._budgets.values()]` on the 30 s tick), service.py:492, :524
  - measurement: `budget:together replay: 6991 events in 13.1 ms`; `ls -la streams/cognition%3Abudget%3Atogether.jsonl` -> 1,608,128 bytes
  - simorgh/ledger/compaction.py:36 DEFAULT_RETENTION has no `cognition:` entry (forever); the Ledger already offers projections with snapshots (`ledger.rebuild`, used at learning/service.py:74)
- **why it matters:** The durable-window design is right; replaying instead of folding is the part that will turn into 'Sim got slow' after a few months of voice use, at exactly the call site on every think.
- **recommendation:** Keep a per-provider deque of (ts, cost) folded once at start (from the last 24 h only, via `read(from_seq=...)` or a snapshot) and appended in `record()`, or simply add `"cognition:budget:": "2d"` to retention so the replay stays bounded.
- **confidence:** 0.9

##### 13. Learning's patch pipeline, Reflection's drift review and Curiosity's drives are scaffolding that costs money or health noise without producing decisions

- **kind:** over-engineering
- **severity:** medium
- **claim:** Of the three growth packages, the parts that demonstrably change behaviour are Reflection's pattern mining and distillation and Curiosity's candidate sampling; Learning's PatchPipeline/Correlator/strategy (~450 lines) have no publisher and make Learning report itself degraded forever, Reflection's DriftTracker has run 181 trackers and 66 LLM drift reviews with 0 detections, and Curiosity's four-drive engine has two constant drives (gap always 0.6, budget always 1.0).
- **evidence:**
  - simorgh/learning/service.py:115-125 `UNREACHABLE = ("no publisher for learn.pipeline.run, and draft_candidate is not a registered tool ...")`; `health()` returns `Health.degraded(self.UNREACHABLE)` whenever no pipeline runs -- i.e. always
  - ledger: `reflect critique streams: 125 drift streams: 181 drift detected events: 0 drift reviews: 66` (each review is a `cognition.think purpose=review` call, reflection/service.py:307-321)
  - simorgh/curiosity/drives.py:37-40 (`_gap` constant, see finding 1) and curiosity/service.py:480-488 (`_exploration_rate` constant, see finding 8); the `interest` drive is a substring match of area name against feed URLs (drives.py:58-66)
  - package sizes: learning 992 lines / 1,016 test lines; reflection 2,145 / 2,239; curiosity 1,402 / 1,299; commits in the last 30 days: learning 10, reflection 12, curiosity 9 vs orchestration 178
- **why it matters:** Three packages, ~4,500 lines and ~4,500 test lines, whose live output is: one prompt line, seven skill tasks, three pattern tasks, feed-item memories, and a permanently red health row. The permanent 'degraded' in particular trains the operator to ignore `status`, which is the one place a real regression would show.
- **recommendation:** Delete learning/pipeline.py, correlator.py and strategy.py (the `improve` path already goes through Orchestration) and make Learning's health honest `ok`; drop the LLM drift review and keep the heuristic tracker only if it ever emits; reduce Curiosity's drives to staleness + interest until a real competence gap producer exists. Fold what is left of Learning into Reflection or World Model -- one 'growth' package is the right size for one laptop.
- **confidence:** 0.85


### measurements

- cognition:calls -- 9,379 think calls; by (purpose, provider): ('chat','together') 3076, ('draft','together') 1916, ('review','together') 1814, ('chat','ollama') 1360, ('draft','claude_code_cli') 526, ('review','claude_code_cli') 287, ('chat','claude_code_cli') 214, ('consolidate','together') 175; plan 1, decompose 1, gemini 2; floor calls: 0
- cognition:budget -- claude_code_cli: 1034 events, total reported cost $99.32 (~$0.096/call); together: 6991 events, total cost $4.56 (~$0.00065/call); replaying the together stream (what RollingWindowBudget.status does per can_spend): 6991 events in 13.1 ms; file 1,608,128 bytes
- curiosity:ticks -- 161,096 events, 45,068,994 bytes; last 20,000 ticks: {'autonomy_paused': 20000}; mean interval over last 2,000 ticks 3.02 s
- learn:outcomes -- 2,714 events; ('unknown', True) 2403, ('research', False) 65, ('unknown', False) 63, ('research', True) 60, ('patch', True) 44, ('patch', False) 37; with strategy: 0; with stated_confidence: 0; last 300: 299 'unknown'
- ~/.simorgh/worldmodel/self/SELF.md (live v42): 'How well I do it: - unknown 97% (2466)'; 'What I know I'm bad at: (none recorded yet)'; 'What I've changed about myself: (none recorded yet)'; 'Restarts recorded: 1'
- memory streams -- episodic 2,746 records (self_critique-tagged: 125, of which 122 within 10 min of a human chat turn); semantic 175 (first tag 'consolidation' 175/175); procedural 18; contradictions 133 (all 'both tagged consolidation'); tombstones 53
- reflection -- critique streams 125; drift streams 181; drift 'review' events (LLM calls) 66; drift 'detected' events 0; reflect:calibration 1 snapshot (research: stated 0.78, empirical 0.526, brier 0.218, 19 samples); reflect:patterns 3 'mined'; reflect:distillation 7 'proposed'
- ledger layout -- 118,218 stream files (88,356 trace:, 26,737 action:, 2,431 task:, 310 reflect:); streams/ 696 MB, blobs/ 325 MB; DEFAULT_RETENTION covers only trace:/dead:/activity
- world model capability scan on every self.summary request: list_capability_areas -> 19 areas in 1.0 ms; full modules_by_area (Curiosity per tick) -> 380 modules in 11.1 ms
- package sizes (src / test lines, test files): cognition 3,119 / 4,273 (19); memory 1,880 / 3,326 (20); worldmodel 1,218 / 878 (8); learning 992 / 1,016 (7); reflection 2,145 / 2,239 (14); curiosity 1,402 / 1,299 (11); commits touching each in the last 30 days: cognition 50, memory 23, worldmodel 11, learning 10, reflection 12, curiosity 9, orchestration 178
- live config ~/.simorgh/simorgh.toml: `[cognition.providers.ollama] model = "qwen3:4b-instruct", only_purposes = ["chat"], vision_model = "qwen2.5vl:3b"`; no [memory] section (embedder = hashing); no [cognition] routes (tier:strong escalation is a no-op)

