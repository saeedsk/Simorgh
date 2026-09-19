# refute:proportionality:Learning's patch pipeline, Reflection's

*Workflow: review · Phase: Refute · Agent id: `acb276752344ae816` · Tool calls: 15*

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
    "title": "Learning's patch pipeline, Reflection's drift review and Curiosity's drives are scaffolding that costs money or health noise without producing decisions",
    "kind": "over-engineering",
    "severity": "medium",
    "claim": "Of the three growth packages, the parts that demonstrably change behaviour are Reflection's pattern mining and distillation and Curiosity's candidate sampling; Learning's PatchPipeline/Correlator/strategy (~450 lines) have no publisher and make Learning report itself degraded forever, Reflection's DriftTracker has run 181 trackers and 66 LLM drift reviews with 0 detections, and Curiosity's four-drive engine has two constant drives (gap always 0.6, budget always 1.0).",
    "evidence": [
      "simorgh/learning/service.py:115-125 `UNREACHABLE = (\"no publisher for learn.pipeline.run, and draft_candidate is not a registered tool ...\")`; `health()` returns `Health.degraded(self.UNREACHABLE)` whenever no pipeline runs -- i.e. always",
      "ledger: `reflect critique streams: 125 drift streams: 181 drift detected events: 0 drift reviews: 66` (each review is a `cognition.think purpose=review` call, reflection/service.py:307-321)",
      "simorgh/curiosity/drives.py:37-40 (`_gap` constant, see finding 1) and curiosity/service.py:480-488 (`_exploration_rate` constant, see finding 8); the `interest` drive is a substring match of area name against feed URLs (drives.py:58-66)",
      "package sizes: learning 992 lines / 1,016 test lines; reflection 2,145 / 2,239; curiosity 1,402 / 1,299; commits in the last 30 days: learning 10, reflection 12, curiosity 9 vs orchestration 178"
    ],
    "why_it_matters": "Three packages, ~4,500 lines and ~4,500 test lines, whose live output is: one prompt line, seven skill tasks, three pattern tasks, feed-item memories, and a permanently red health row. The permanent 'degraded' in particular trains the operator to ignore `status`, which is the one place a real regression would show.",
    "recommendation": "Delete learning/pipeline.py, correlator.py and strategy.py (the `improve` path already goes through Orchestration) and make Learning's health honest `ok`; drop the LLM drift review and keep the heuristic tracker only if it ever emits; reduce Curiosity's drives to staleness + interest until a real competence gap producer exists. Fold what is left of Learning into Reflection or World Model -- one 'growth' package is the right size for one laptop.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read Learning service health and UNREACHABLE |  #: Two independent reasons, both verified 2026-09-09 (wave-21 #: observer W21-12), either of which alone is fatal: #: #: 1. Nothing anywhere publishes `learn.p |
| 2 | Bash | Check publishers and package sizes | == publishers of learn.pipeline.run / strategy.suggest / draft_candidate == (eval):1: no matches found: --include=*.py --- in learning: (eval):1: no matches fou |
| 3 | Bash | Find publishers and Learning subscriptions | == publishers outside learning == simorgh/contracts/topics.py:160:LEARN_PIPELINE_RUN = "learn.pipeline.run" simorgh/contracts/topics.py:162:LEARN_STRATEGY_SUGGE |
| 4 | Bash | Check tool registration, consumers, commit counts, status aggregation | == draft_candidate tool registration == simorgh/contracts/toolargs.py:102: "draft_candidate": "code", simorgh/orchestration/tools.py:51: "draft_candidate": ("re |
| 5 | Bash | Read kernel health aggregation | == kernel health aggregation == # closes the very backend connection `_append_state` needs # (`ledger`/`bus` are ordinary layers here too, stopped last by # `st |
| 6 | Bash | Read Reflection drift review code | == reflection/service.py 280-340 == await self._run_drift_close(message, meta) await self._publish(message, topics.SELF_OBSERVATION, { "kind": "success" if succ |
| 7 | Bash | Read drift tracker logic and config | == drift.py 55-130 == """One per in-progress task (or, at plan level, per project -- children stand in for steps; see spec section 5.4's closing paragraph)."""  |
| 8 | Bash | Read review call sites and Curiosity drives | == _request_review / observe_step call sites == 263: meta.tracker.observe_step(p.get("tool"), p.get("summary", "")) 280: await self._run_drift_close(message, me |
| 9 | Bash | Check gap and budget sources, improve path, ledger layout | == gap sources == 16:_UNKNOWN_AREA_GAP = 0.6 507: gaps_reply = await self._bus.request_or_error( 510: gaps: tuple[Gap, ...] = () 511: if gaps_reply.payload.get( |
| 10 | Bash | Read gap query, budget, improve path, ledger drift streams | == curiosity gaps query 500-520 == names = reply.payload.get("areas") or [] modules_by_area = reply.payload.get("modules_by_area") or {} areas = tuple(Area(name |
| 11 | Bash | Count drift ledger events and check gap/budget publishers | == drift events == Counter({'step_seen': 2059, 'goal_registered': 181, 'review': 66, 'stalled': 8}) verdicts Counter({'on_track': 37, 'unknown': 28, 'drifting': |
| 12 | Bash | Verify budget publisher, gap name matching, ledger learn streams | == remaining_fraction anywhere == docs/blueprint/subsystems/13-curiosity.md:230:`remaining_fraction < backoff_below_remaining`; `r = 0` below docs/blueprint/sub |
| 13 | Bash | Check budget payload keys, gap computation, live drive values | == cognition budget payload keys == # request actually spent against what it stated it could -- # reported alongside the rolling per-provider window in # `cogni |
| 14 | Bash | Quote gap stub, drift close context, outcome task types | == selfmodel compute_gaps == def compute_gaps(model: SelfModel, k: int) -> tuple[list[dict], list[dict]]: """No real competence/coverage data exists yet (both p |
| 15 | Bash | Check whether competence reaches the self model |  async def _on_competence_updated(self, message: Message) -> None: p = message.payload await self._apply( lambda m, now: update_competence( m, p["task_type"], u |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every factual leg of the claim checks out against the code and the live ledger, and the parts I could probe further turned out worse than stated, not better. (1) Learning: `grep -rn 'learn\.pipeline\.run\|LEARN_PIPELINE_RUN\|LEARN_STRATEGY' simorgh` finds only the topic/contract definitions and Learning's own subscriber -- no publisher anywhere; `draft_candidate` appears only in policy/scaffold tables (orchestration/tools.py:51, toolargs.py:102, scaffolds.py:212), never a registration; `health()` (learning/service.py:120-125) returns degraded unless a pipeline is running, i.e. permanently. `improve` goes to TASK_CREATE kind=patch (interface/dispatch.py:251-262), bypassing Learning entirely. (2) Reflection drift: the ledger holds 181 `reflect:drift:*` streams with 181 goal_registered, 2059 step_seen, 66 review, 0 detected events; verdicts 37 on_track / 28 unknown / 1 drifting. Materially new: `_request_review` is called from exactly one site, `_run_drift_close` (reflection/service.py:280,296), which runs in `_on_task_terminal` -- the LLM is asked "Is the work so far still serving the goal?" AFTER the task has finished, with a prompt containing only the goal string and scope paths and no evidence of the work (service.py:309-312). The consumers of REFLECT_DRIFT_DETECTED (planning/service.py:178, guardian/service.py:182) are built for in-flight correction, so even a positive verdict could not act. This is a design that is right (heuristic + LLM drift check) undermined by implementation (post-mortem placement, evidence-free prompt), not merely over-engineering. The arithmetic also makes an `on_track` verdict unable to ever emit (combined = 0.5*h, threshold 0.6, h capped at 1.0; drift.py:106-116). (3) Curiosity: `_gap` returns `_UNKNOWN_AREA_GAP = 0.6` when no gaps match (drives.py:16,37-40), and the SELF_GAPS provider `compute_gaps` (worldmodel/selfmodel.py:401-406) is a stub that unconditionally returns `[], []` -- even though World Model does fold LEARN_COMPETENCE_UPDATED into `model.competence` (worldmodel/service.py:303-311, selfmodel.py:110-119), so the data exists and is simply never read. `_exploration_rate` reads `budget.remaining_fraction`/`free` from COGNITION_PROVIDER_STATUS (curiosity/service.py:232-238, 480-488), but Cognition publishes `{window_seconds, calls, max_calls, spend_usd, max_spend_usd, exhausted}` (cognition/service.py:456-460); `grep -rn remaining_fraction simorgh` matches only Curiosity and the blueprint doc, so `worst_remaining` stays None and the rate is always 1.0. Live confirmation: `curiosity:candidates.jsonl` has 10 events and none record a gap value. Also new: 2466 of 2714 `learn:outcomes` rows have task_type "unknown", so the competence tracking that Learning does perform is mostly keyed to a bucket nobody can act on. Sizes and commit counts match (learning 1307 lines incl. __init__; pipeline+correlator+strategy = 315 lines, not ~450; tests 1016/2239/1299; commits 10/12/9 vs 178). On the disproportion lens: the drift review's cost is negligible (max_cost_usd 0.02 x 66 <= $1.32) so "costs money" is overstated, and the status glyph is a yellow half-ring rather than red (interface/render.py:535); but the substantive point stands -- three growth packages whose decision-producing paths are either unpublished, evidence-free, or fed by stubs, at a scale where one developer maintains 4.5k lines plus 4.5k test lines that change nothing. The recommendation to delete pipeline/correlator/strategy and make health honest is proportionate; the recommendation to drop the LLM drift review is defensible but the cheaper fix (wire compute_gaps to model.competence; publish remaining_fraction; move the review mid-task with step evidence) would rescue the design rather than remove it.

### evidence

- simorgh/learning/service.py:98-125 -- UNREACHABLE constant and health() returning Health.degraded(self.UNREACHABLE) whenever no pipeline runs
- grep -rn 'learn\.pipeline\.run\|LEARN_PIPELINE_RUN\|LEARN_STRATEGY' simorgh --include='*.py' | grep -v learning/ -> only contracts/topics.py:160-163 and contracts/messages/learn.py:9,23 (definitions, no publisher)
- grep -rn draft_candidate simorgh | grep -v learning/ -> orchestration/tools.py:51, contracts/toolargs.py:102, orchestration/scaffolds.py:212, cognition/parser.py comments -- policy tables only, no registration
- simorgh/interface/dispatch.py:251-262 -- `improve` -> TASK_CREATE kind=patch, never touches Learning
- ledger: ls ~/.simorgh/ledger/streams | grep -c drift -> 181; event counts over reflect:drift:* -> step_seen 2059, goal_registered 181, review 66, stalled 8, detected 0; verdicts on_track 37 / unknown 28 / drifting 1
- simorgh/reflection/service.py:266-296 -- _run_drift_close is invoked only from _on_task_terminal; _request_review has a single call site (line 296), so the LLM review runs after the task ended
- simorgh/reflection/service.py:309-312 -- review prompt is only `Goal: ...\nDeclared scope: [...]\nIs the work so far still serving the goal?` with no step evidence; budget max_tokens 200, max_cost_usd 0.02
- simorgh/reflection/drift.py:106-116 and reflection/config.py:17-19 -- combined = 0.5*h on on_track, emit threshold 0.6, h capped at 1.0, so an on_track verdict can never emit
- simorgh/planning/service.py:178 and simorgh/guardian/service.py:182 subscribe to REFLECT_DRIFT_DETECTED (in-flight consumers)
- simorgh/curiosity/drives.py:16 `_UNKNOWN_AREA_GAP = 0.6`; drives.py:37-40 `_gap` returns it when ctx.gaps has no match
- simorgh/worldmodel/selfmodel.py:401-406 compute_gaps docstring 'returns empty lists' and body `return [], []` -- the SELF_GAPS provider (worldmodel/service.py:269-273) is a stub
- simorgh/worldmodel/service.py:303-311 folds LEARN_COMPETENCE_UPDATED into model.competence via update_competence (selfmodel.py:110-119) -- data exists, compute_gaps ignores it
- simorgh/curiosity/service.py:232-238 reads budget.remaining_fraction / budget.free; cognition/service.py:456-460 publishes window_seconds/calls/max_calls/spend_usd/max_spend_usd/exhausted; grep -rn remaining_fraction simorgh -> only curiosity/ and docs/blueprint/subsystems/13-curiosity.md
- simorgh/curiosity/service.py:480-488 _exploration_rate returns 1.0 when worst_remaining is None
- ledger curiosity:candidates.jsonl -> 10 events, payload keys area/candidate_id/description/kind/subject, no gap values recorded
- ledger learn:outcomes.jsonl -> 2714 rows; task_type distribution unknown 2466, research 125, patch 81, skill 3
- wc -l: learning pkg 1307 (pipeline 227 + correlator 38 + strategy 50 = 315); tests learning 1016 / reflection 2239 / curiosity 1299; git log --since='30 days ago' -- learning 10, reflection 12, curiosity 9, orchestration 178
- simorgh/interface/render.py:535 -- degraded renders as a yellow half-ring, not red; kernel/service.py:559-564 only reports 'down' subsystems in its own health

**severity adjustment:** keep

**corrected claim:** Learning's PatchPipeline/Correlator/strategy (315 lines, not ~450) have no publisher and no `draft_candidate` tool, so Learning's health is permanently degraded; Reflection's LLM drift review runs only at task close, from `_on_task_terminal`, with a prompt that carries no evidence of the work, and has produced 0 detections in 181 trackers / 66 reviews; Curiosity's gap drive is constant 0.6 because World Model's `compute_gaps` is a `return [], []` stub even though it stores competence from Learning, and its budget rate is constant 1.0 because Cognition never publishes the `remaining_fraction` key Curiosity reads. The dollar cost of the drift reviews is negligible (<= $1.32 total); the real cost is three unconnected wires and a status row that is always degraded.

