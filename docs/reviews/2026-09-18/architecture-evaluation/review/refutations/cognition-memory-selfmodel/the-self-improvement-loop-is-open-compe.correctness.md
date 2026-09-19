# refute:correctness:The self-improvement loop is open: compe

*Workflow: review · Phase: Refute · Agent id: `ae4e8d811ec4c2e9c` · Tool calls: 8*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "cognition-memory-selfmodel". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Read outcome recorder task_type logic and worker task_id |  stream carries the created timestamp and every step's own `cost_usd`. One stream is not always one run. A chat turn's `task_id` IS its `session_id` (`Worker.ru |
| 2 | Bash | Read selfmodel competence, gaps, drives, assembler, learning service |  # because "which model are you?" is a question about who is # answering, and Sim had no way to answer it: `capabilities # ["providers"]` was declared with the  |
| 3 | Bash | Grep for competence consumers, strategy publishers, chat skip, live SELF.md | --- LEARN_STRATEGY_SUGGEST refs --- (eval):1: no matches found: --include=*.py --- competence consumers outside learning/worldmodel --- (eval):1: no matches fou |
| 4 | Bash | Grep competence consumers and list ledger streams | --- LEARN_STRATEGY_SUGGEST refs outside learning --- simorgh/contracts/topics.py:162:LEARN_STRATEGY_SUGGEST = "learn.strategy.suggest" simorgh/contracts/topics. |
| 5 | Bash | Inspect Curiosity competence usage, session tier, gaps handler | --- curiosity/service.py competence --- 35: topics.LEARN_COMPETENCE_UPDATED, topics.LEARN_SELF_PATCH_APPLIED, topics.LEARN_SKILL_ACQUIRED, 507: gaps_reply = awa |
| 6 | Bash | Check Curiosity subscriptions and tally learn:outcomes in ledger | --- curiosity line 30-40 and any subscribe to competence --- _CONSUMES = ( topics.SYSTEM_TICK_IDLE, topics.SYSTEM_TICK_SLEEP, topics.SYSTEM_STATE_CHANGED, topic |
| 7 | Bash | Tally learn:outcomes JSONL and find Curiosity competence handler | --- curiosity handler map --- 4: handlers = { 5: topics.SYSTEM_TICK_IDLE: self._on_tick_idle, 6: topics.SYSTEM_TICK_SECOND: self._on_tick_metrics, 7: topics.SYS |
| 8 | Bash | Check prior reviews for overlap and outcome recorder filters | === docs/architecture-review-2026-09-18.html 234: <td><b>4. Failing-test-first self-improvement</b></td> === docs/architecture-audit-2026.md 20:5. **Self-Improv |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited fact holds against the code as of today and the live ledger. (1) simorgh/learning/outcomes.py:83-91 sets task_type="unknown" and only overrides it from the first event of `task:<id>`; chat turns use task_id=session_id (orchestration/worker.py:402-405, and outcomes.py:63-66 docstring says the same), Planning never creates that stream, so every chat turn records as 'unknown'. No `kind=="chat"` skip exists anywhere in outcomes.py (grep). Reproduced tally of ~/.simorgh/ledger/streams/learn%3Aoutcomes.jsonl: 2714 events, ('unknown',True)=2403, ('unknown',False)=63, strategy=0, stated_confidence=0, last 300 = 299 unknown. (2) Live ~/.simorgh/worldmodel/self/SELF.md (v42, Sep 18 17:09) line 10: "- unknown 97% (2466)". (3) selfmodel.py:309-313 sorts competence rows by samples desc, so 'unknown' leads; assembler.py:58-60 injects SELF_SUMMARY as a protected block. (4) compute_gaps at selfmodel.py:400-406 returns `[], []`; worldmodel/service.py:271 serves SELF_GAPS from it; curiosity/service.py:507-514 requests it and drives.py:37-40 falls back to the constant _UNKNOWN_AREA_GAP when no gaps match -- so the gap drive is constant. (5) grep for LEARN_STRATEGY_SUGGEST outside simorgh/learning/ hits only contracts/topics.py, contracts/messages/learn.py and JSON schemas -- no publisher; learning/service.py:98-103 and strategy.py:9-23 docstrings say so themselves. (6) No consumer of competence steers behaviour: `_tier` (orchestration/session.py:1507-1518) looks only at attempt count and a failed delegate; grep for 'competence' outside learning/ and worldmodel/ hits only contracts and curiosity, and curiosity/service.py lists LEARN_COMPETENCE_UPDATED in _CONSUMES (line 35) but binds no handler for it in the handlers map (lines 143-166) -- a further unconnected wire that strengthens the claim. Not in the known-findings list: prior reviews mention self_patch.draft not registered and test-gaming in self-patching, not competence pollution or the absent consumer. Minor correction: the "88.5%" figure counts only successful unknowns (2403/2714); all unknown outcomes are 2466/2714 = 90.9%. Parts of the chain (no strategy publisher, empty compute_gaps) are self-documented in code docstrings, so the creator partly knows them, but the synthesis -- chat turns polluting the table, the wrong line being the only competence the model sees, and nothing downstream steering on it -- is materially new. Severity 'critical' is defensible for a project whose headline claim is self-improvement; I keep it.

### evidence

- simorgh/learning/outcomes.py:83-91 -- `task_type = "unknown"` default, overridden only from `task:{task_id}` first event's `kind`; no kind=='chat' filter anywhere in the file (grep -n 'chat' returns only docstring lines 63-65, 158)
- simorgh/orchestration/worker.py:402-405 -- `Session(task_id=session_id, kind="chat", ...)`; docstring lines 395-400 states Planning never created this id
- Command: python3 tally of ~/.simorgh/ledger/streams/learn%3Aoutcomes.jsonl -> `events: 2714 with strategy: 0 stated_confidence: 0`; `[(('unknown', True), 2403), (('research', False), 65), (('unknown', False), 63), (('research', True), 60), (('patch', True), 44), (('patch', False), 37), ...]`; `unknown share: 90.9%`; `last300: [('unknown', 299), ('patch:simorgh/interface', 1)]`
- ~/.simorgh/worldmodel/self/SELF.md (v42, 2026-09-18 17:09, mtime Sep 18 17:09) line 9-10: `## How well I do it` / `- unknown 97% (2466)`
- simorgh/worldmodel/selfmodel.py:309-313 -- competence rows sorted by samples desc, top 5 rendered; simorgh/cognition/assembler.py:58-60 -- SELF_SUMMARY text appended as protected block 'self_summary'
- simorgh/worldmodel/selfmodel.py:400-406 -- `compute_gaps` returns `[], []`; simorgh/worldmodel/service.py:271-272 serves SELF_GAPS from it; simorgh/curiosity/service.py:507-514 requests SELF_GAPS; simorgh/curiosity/drives.py:37-40 `_gap` returns `_UNKNOWN_AREA_GAP` when no matches
- Command: `grep -rn 'LEARN_STRATEGY_SUGGEST\|learn\.strategy\.suggest' simorgh/ | grep -v '^simorgh/learning/'` -> only contracts/topics.py:162-163, contracts/messages/learn.py:23-24, and two JSON schemas; no publisher
- simorgh/learning/service.py:98-103 and simorgh/learning/strategy.py:9-23 -- docstrings state nothing publishes learn.strategy.suggest and no outcome carries a strategy
- simorgh/orchestration/session.py:1507-1518 `_tier` -- decides on `session.attempt` and a failed `delegate` step only; no competence lookup (grep 'competence|success_rate' in session.py: no hits)
- Command: `grep -rln competence simorgh/ | grep -v '^simorgh/learning/\|^simorgh/worldmodel/'` -> contracts/topics.py, contracts/messages/self_.py, two schemas, curiosity/{README.md,api.py,service.py,drives.py} only
- simorgh/curiosity/service.py:35 lists LEARN_COMPETENCE_UPDATED in `_CONSUMES`, but the handlers dict (lines 143-166) has no entry for it -- declared consumer, no handler
- Prior reviews: docs/architecture-third-opinion-2026-09-18.md:117,223 and docs/architecture-audit-2026.md:20 cover self_patch.draft / test-gaming; no mention of competence pollution, compute_gaps, or the missing strategy publisher

**severity adjustment:** keep

**corrected claim:** As claimed, with one number fixed: 90.9% (2466/2714) of recorded outcomes are task_type 'unknown' (88.5% is the successful-unknown share alone). Additionally, Curiosity declares itself a consumer of learn.competence.updated (curiosity/service.py:35) but binds no handler for it, so the only live consumer of competence is the self-summary line.

