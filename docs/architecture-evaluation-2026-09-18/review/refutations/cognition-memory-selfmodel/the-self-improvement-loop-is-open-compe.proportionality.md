# refute:proportionality:The self-improvement loop is open: compe

*Workflow: review · Phase: Refute · Agent id: `a890c3d76b8d3b47f` · Tool calls: 10*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "cognition-memory-selfmodel". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "The self-improvement loop is open: competence is polluted by chat turns, reaches the model only as one prompt line, and steers nothing",
    "kind": "wrong-design",
    "severity": "critical",
    "claim": "Outcome -> competence -> different behaviour does not exist today: 88.5% of recorded outcomes are task_type 'unknown' (every chat turn), the only consumer of a competence estimate is a rendered line in the self-summary prompt block, `self.gaps` always returns nothing, and `learn.strategy.suggest` has no publisher -- so Learning is write-only telemetry that surfaces in every prompt as 'Competence: unknown 97% (2466)'.",
    "evidence": [
      "ledger measurement: `learn:outcomes 2714 events; by (type,succeeded): [(('unknown', True), 2403), (('research', False), 65), (('unknown', False), 63), (('research', True), 60), (('patch', True), 44), (('patch', False), 37) ...]`; `with strategy: 0 with stated_confidence: 0`; `last 300 outcomes by type: [('unknown', 299), ('patch:simorgh/interface', 1)]`",
      "~/.simorgh/worldmodel/self/SELF.md (live, v42, 2026-09-18 17:09): `## How well I do it\\n- unknown 97% (2466)`",
      "simorgh/learning/outcomes.py:83-91 -- task_type defaults to \"unknown\" and is read from `task:<id>`'s first event's `kind`; a chat turn's task_id is its per-line session uuid (orchestration/worker.py:402-405) which Planning never `created`, so every chat turn is an 'unknown' success",
      "simorgh/worldmodel/selfmodel.py:309-313 -- the competence section rendered into the protected `self_summary` block (cognition/assembler.py:58-60) sorts by samples, so 'unknown' is the first row",
      "simorgh/worldmodel/selfmodel.py:400-406 `compute_gaps` returns `[], []`; simorgh/curiosity/drives.py:37-40 `_gap` falls back to `_UNKNOWN_AREA_GAP = 0.6` for every area -- the 'gap' drive is a constant",
      "simorgh/learning/service.py:98-103 (and my grep of simorgh/ outside learning/: no reference to LEARN_STRATEGY_SUGGEST) -- nothing publishes `learn.strategy.suggest`; simorgh/learning/strategy.py:9-23 documents that no outcome ever carries a strategy"
    ],
    "why_it_matters": "This is the headline claim of the project ('self-improving'). As built, the measured competence never changes provider choice, tool choice, step budget, escalation, or which area Curiosity explores; the single place it reaches the model is a line that is both wrong (chat turns are not a task type) and, after a restart, the ONLY competence line the model sees. A senior reviewer would call this an unclosed loop, not a self-improving agent.",
    "recommendation": "Pick one concrete behaviour to close the loop on and wire it end to end before adding anything else: e.g. record outcomes only for Planning-created tasks (skip kind='chat' in OutcomeRecorder, as memory/service.py:217-222 already does for episodic writes), and have orchestration/session.py::_tier consult `CompetenceTable.success_rate(task_type)` to choose `tier: strong` or a higher step cap when the rate for that type is below 0.4 with >= 5 samples. Delete `compute_gaps` and the `gap` drive until a producer exists.",
    "confidence": 0.95
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read outcome recorder and worker task_id code |  stream carries the created timestamp and every step's own `cost_usd`. One stream is not always one run. A chat turn's `task_id` IS its `session_id` (`Worker.ru |
| 2 | Bash | Read selfmodel competence section, compute_gaps, and curiosity gap |  f"assistant name; that is not who is answering here. " f"{model.identity.summary}" ).strip() if section == "substrate": # What is actually doing the thinking.  |
| 3 | Bash | Read learning service subscriptions and grep for strategy publisher |  self._subs.append(await ctx.bus.subscribe(topics.LEARN_STRATEGY_SUGGEST, self._on_strategy_suggest)) async def stop(self) -> None: self._action_correlator.canc |
| 4 | Bash | Find all consumers of competence data and tier selection logic | Exit code 1 == consumers of competence outside learning/ == (eval):1: no matches found: --include=*.py == compute_gaps callers == (eval):1: no matches found: -- |
| 5 | Bash | Read assembler protected block, memory chat-skip, and live SELF.md |  steps_left: int \| None = None, ) -> AssembledContext: blocks: list[PromptBlock] = [self._block("constitution", CONSTITUTION_SUMMARY, protected=True)] voice = a |
| 6 | Bash | Recount learn:outcomes events in the live ledger by task_type | blobs heads idem index.json LOCK snapshots streams paths: ['/Users/saeed/.simorgh/ledger/idem/learn%3Aoutcomes.idx', '/Users/saeed/.simorgh/ledger/streams/learn |
| 7 | Bash | Find every consumer of competence, gaps, and tier logic | == consumers of competence outside learning/selfmodel/contracts == simorgh/curiosity/service.py:513: Gap(competence=g["competence"], task_type=g["task_type"], s |
| 8 | Bash | Check what triggers outcome recording and how curiosity uses gap | == who publishes task.completed for chat turns == simorgh/orchestration/worker.py:458: "completed": topics.TASK_COMPLETED, simorgh/orchestration/worker.py:486:  |
| 9 | Bash | Check curiosity competence handler and competence persistence across boot | == curiosity on competence updated == 35: topics.LEARN_COMPETENCE_UPDATED, topics.LEARN_SELF_PATCH_APPLIED, topics.LEARN_SKILL_ACQUIRED, == curiosity gaps fetch |
| 10 | Bash | Check curiosity's competence handler and self model on-disk competence state | == curiosity handler for learn.* == 32- topics.SYSTEM_TICK_IDLE, topics.SYSTEM_TICK_SLEEP, topics.SYSTEM_STATE_CHANGED, 33- topics.TASK_CREATED, topics.TASK_COM |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited fact checks out against the code and the live ledger, and I could not find a hidden consumer that closes the loop. (1) Ledger recount from ~/.simorgh/ledger/streams/learn%3Aoutcomes.jsonl gives exactly the finding's numbers: 2714 events, ('unknown', True) 2403, 0 with a strategy, last 300 = 299 'unknown'. (2) outcomes.py:83-94 defaults task_type to 'unknown' and reads kind from task:<id>'s first event; worker.py builds chat Sessions with task_id=session_id that Planning never created, and the docstring at outcomes.py:63-66 itself acknowledges chat turns land here. (3) The only consumers of competence outside learning/: worldmodel/service.py:117 folds learn.competence.updated into the in-memory SelfModel, which selfmodel.py:309-313 renders as a prompt line sorted by samples (so 'unknown' is first); curiosity/service.py:508-516 asks self.gaps, which worldmodel/service.py:271 answers via compute_gaps -> ([], []) (selfmodel.py:400-406), so drives.py:_gap returns the constant 0.6 for every area. (4) learning/service.py:85 subscribes to LEARN_STRATEGY_SUGGEST but grep finds no publisher outside contracts/; learning/service.py:98-115 UNREACHABLE docstring says so itself. (5) orchestration/session.py:1507-1518 _tier escalates only on attempt count or a failed delegate, never on competence. (6) The SelfModel has no JSON persistence (worldmodel/service.py:105,414 only write SELF.md as a render), so after a restart competence holds only what live events supply since boot -- the live SELF.md indeed shows the single row 'unknown 97% (2466)'. Materially new supporting detail: curiosity/service.py:35 declares LEARN_COMPETENCE_UPDATED in its _CONSUMES tuple but never subscribes to it (only worldmodel does) -- a second declared-but-unwired consumer. On the skeptic lens (scale/proportionality): this is not a scale problem and the recommendation is small (skip kind='chat' in OutcomeRecorder, mirroring memory/service.py:217-222 which does exactly that; one success_rate lookup in _tier; delete dead gap code). The one framing correction: this is less 'wrong-design' than the project's own 'unconnected wire' shape -- the design (outcomes -> CompetenceTable -> strategy/gaps -> behaviour) is coherent; nobody wired the consumers. But the loop is genuinely open and the headline claim depends on it, so severity stands.

### evidence

- python3 recount of ~/.simorgh/ledger/streams/learn%3Aoutcomes.jsonl: n 2714 strategy 0; [(('unknown', True), 2403), (('research', False), 65), (('unknown', False), 63), (('research', True), 60), (('patch', True), 44), (('patch', False), 37) ...]; last300 [('unknown', 299), ('patch:simorgh/interface', 1)]
- ~/.simorgh/worldmodel/self/SELF.md (734 bytes, Sep 18 17:09): '## How well I do it\n- unknown 97% (2466)' -- the only competence row; ~/.simorgh/worldmodel/self/ contains only SELF.md, no JSON state
- simorgh/learning/outcomes.py:83-94: task_type = "unknown"; kind = p.get("kind", "unknown") from task:<id> first event; docstring lines 63-66: 'A chat turn's task_id IS its session_id'
- simorgh/orchestration/worker.py:401-405: Session(task_id=session_id, kind="chat", ...) for a percept Planning never created
- simorgh/worldmodel/selfmodel.py:309-313: competence section sorted by samples desc, top 5; selfmodel.py:400-406 compute_gaps returns [], []
- simorgh/worldmodel/service.py:271: gaps, unexplored = compute_gaps(self._model, ...); service.py:105/414 write SELF.md only (render, no reload)
- simorgh/curiosity/service.py:508-516 requests SELF_GAPS; drives.py:16 _UNKNOWN_AREA_GAP = 0.6; drives.py:38-40 returns it when no matches
- grep -rn 'LEARN_STRATEGY_SUGGEST|learn.strategy.suggest' simorgh/ excluding learning/: only contracts/topics.py:162-163, contracts/messages/learn.py:23-24 and two schema files -- no publisher
- simorgh/learning/service.py:98-115 UNREACHABLE docstring: 'Nothing anywhere publishes learn.pipeline.run or learn.strategy.suggest'
- grep -rn 'success_rate|CompetenceTable|competence' simorgh/ --include='*.py' outside learning/, selfmodel.py, contracts/: hits only in worldmodel/service.py (fold into SelfModel) and curiosity (Gap dataclass / _gap) -- no orchestration, cognition, or execution consumer
- simorgh/orchestration/session.py:1507-1518 _tier: escalates on session.attempt >= _escalate_from_attempt or a failed delegate step only
- simorgh/curiosity/service.py:35 lists LEARN_COMPETENCE_UPDATED in _CONSUMES but grep shows the only bus.subscribe to that topic is worldmodel/service.py:117
- simorgh/memory/service.py:217-222: episodic writer already skips payload kind != 'chat' -- the pattern the recommendation proposes to mirror in OutcomeRecorder
- simorgh/learning/service.py:74: ctx.ledger.rebuild(self._competence, 'learn:outcomes') -- the CompetenceTable itself survives restart, but its only readers are the unpublished suggest handler and the live-event-only SelfModel

**severity adjustment:** keep

**corrected claim:** The claim is accurate as stated. Only the 'kind' label deserves a nudge: this is the project's own 'unconnected wire' shape (a coherent design whose consumers were never wired) rather than a wrong design -- outcomes are recorded, the CompetenceTable is rebuilt from the ledger on boot (learning/service.py:74), but nothing reads it to steer tier, budget, tool choice, or exploration, and the SelfModel is not persisted so the prompt line after a restart reflects only post-boot chat turns. Curiosity additionally declares LEARN_COMPETENCE_UPDATED as consumed (curiosity/service.py:35) without subscribing to it.

