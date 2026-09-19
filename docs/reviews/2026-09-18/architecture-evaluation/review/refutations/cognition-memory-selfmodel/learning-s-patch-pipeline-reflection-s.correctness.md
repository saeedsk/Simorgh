# refute:correctness:Learning's patch pipeline, Reflection's

*Workflow: review · Phase: Refute · Agent id: `abb1b34559f694234` · Tool calls: 15*

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
| 1 | Bash | Read Learning service health and UNREACHABLE text |  #: Two independent reasons, both verified 2026-09-09 (wave-21 #: observer W21-12), either of which alone is fatal: #: #: 1. Nothing anywhere publishes `learn.p |
| 2 | Bash | Check publishers, tool registration, and package sizes | == publishers of learn.pipeline.run / learn.strategy.suggest / draft_candidate == (eval):1: no matches found: --include=*.py == in learning == simorgh/learning/ |
| 3 | Bash | Recheck publishers with correct glob quoting | == publishers outside learning == simorgh/cognition/parser.py:12: (`orchestration/profiles.py`), so this is `draft_candidate`/ simorgh/cognition/parser.py:42:#  |
| 4 | Bash | Read curiosity drives and reflection drift review code | == tool registry mentions of draft_candidate == simorgh/execution/external.py:43:object. `orchestration/tools.py::register_tool_policy` learns each tool simorgh |
| 5 | Bash | Count commits per package and locate ledger drift streams | == commits last 30 days == learning: 10 reflection: 12 curiosity: 9 orchestration: 178 == ledger dir == benchmark benchmark-waves benchmarks bus cognition curio |
| 6 | Bash | Inspect drive constants, budget feed, and drift heuristic | == UNKNOWN_AREA_GAP == 16:_UNKNOWN_AREA_GAP = 0.6 == gaps producer in curiosity service == 507: gaps_reply = await self._bus.request_or_error( 510: gaps: tuple[ |
| 7 | Bash | List ledger streams for drift, critique, learning | == streams layout == action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl action%3A00085e844cff.jsonl action%3A0009062c07cc.jsonl |
| 8 | Bash | Count drift, critique, curiosity, learning events in the ledger | drift streams: 181 critique streams: 125 drift detected events: 0 drift review events: 66 -- sample drift stream: {"causation_id":null,"idempotency_key":null,"p |
| 9 | Bash | Inspect gap producer, budget feed, drive weights, status rendering | == curiosity gaps query == names = reply.payload.get("areas") or [] modules_by_area = reply.payload.get("modules_by_area") or {} areas = tuple(Area(name=n, modu |
| 10 | Bash | Trace gap producer, budget fraction publisher, drift threshold, interest topics | == worldmodel gaps source == def _set_areas(model, now): if areas == model.capabilities.get("areas"): return model # `_apply` treats an unchanged model as a no- |
| 11 | Bash | Inspect curiosity tick records for drive values | == ticks with gap scores == 161096 curiosity%3Aticks.jsonl 10 curiosity%3Acandidates.jsonl 1 curiosity%3Aprojects.jsonl 3 reflect%3Apatterns.jsonl 7 reflect%3Ad |
| 12 | Bash | Check whether any provider status carries remaining_fraction | == remaining_fraction anywhere == simorgh/curiosity/service.py:233: remaining = budget.get("remaining_fraction") == provider status subscription in curiosity == |
| 13 | Bash | Check why the gap drive stays constant | == compute_gaps == 400:def compute_gaps(model: SelfModel, k: int) -> tuple[list[dict], list[dict]]: 401- """No real competence/coverage data exists yet (both pr |
| 14 | Bash | Check whether prior reviews already reported these points | == docs/architecture-audit-2026.md == == docs/architecture-review-2026-09-18.html == == docs/architecture-third-opinion-2026-09-18.md == |
| 15 | Bash | Confirm provider status budget keys and router floor behaviour |  topics.COGNITION_PROVIDER_STATUS, source=self._ctx.source, payload={ "provider": status.provider, "available": not status.exhausted, "model": self._model_of(st |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every load-bearing assertion in the claim holds against the code today and the live ledger; two of them are actually stronger than stated. (1) Learning: simorgh/learning/service.py:120-125 `health()` returns `Health.degraded(self.UNREACHABLE)` unless `_running_pipelines` is non-empty, and the only thing that populates that is `_on_pipeline_run` (line 166), subscribed to `learn.pipeline.run` (line 84). A repo-wide grep for `learn.pipeline.run|learn.strategy.suggest|LEARN_PIPELINE_RUN|LEARN_STRATEGY_SUGGEST` outside simorgh/learning/ hits only the constant definitions in contracts/topics.py:160-163 -- no publisher, no requester -- so Learning is degraded on every boot, by construction. `draft_candidate` appears only as a risk-class/arg-name entry (orchestration/tools.py:51, contracts/toolargs.py:102, scaffolds.py:212), never as a registered handler in execution/. (2) Reflection drift: ledger has 181 `reflect:drift:*` streams, 66 `review` events, 0 `detected` events (verdict split: 37 on_track, 28 unknown, 1 drifting -- even the one 'drifting' verdict did not clear `drift_emit_threshold=0.6`, reflection/config.py:19, per drift.py:105-116). Each review is a `cognition.think purpose=review` request (reflection/service.py:307-321). (3) Curiosity: the gap drive is not merely empirically constant but structurally so -- worldmodel/selfmodel.py:400-406 `compute_gaps` unconditionally returns `[], []`, so `ctx.gaps` is always empty and drives.py:37-40 always returns `_UNKNOWN_AREA_GAP = 0.6` (ledger: 94 recorded gap values, all 0.6). The budget rate is likewise structurally 1.0: curiosity/service.py:233 reads `budget["remaining_fraction"]`, but cognition/service.py:456-460 publishes `window_seconds/calls/max_calls/spend_usd/max_spend_usd/exhausted` and no `remaining_fraction` exists anywhere else in simorgh/, so `worst_remaining` stays None and `_exploration_rate` (service.py:480-488) returns 1.0. (4) Line counts and 30-day commit counts (learning 10, reflection 12, curiosity 9, orchestration 178) reproduce exactly. Minor inaccuracies: the dead Learning code is ~380 lines (pipeline 227 + correlator 38 + strategy 50 + ~65 handler lines), not ~450; the interest drive matches area names against interest topic strings which may be feed URLs OR plain labels (interests.py:4-6; ledger shows labels like "AI and AI agents"), not only feed URLs; drift reviews are capped at max_cost_usd 0.02 with `require_real_provider: False`, so 'costs money' is a small cost, though the calls are real and yield nothing. Overlap with known findings is limited to the draft tool not being registered; none of the three prior review docs mention UNREACHABLE, the permanent degraded health, drift review yield, or the constant drives (grep returned nothing). Extra supporting observations found along the way: curiosity:ticks holds 161,096 events (recent ones `skipped_reason: autonomy_paused`), and 2,466 of 2,714 learn:outcomes records carry `task_type: "unknown"`, which is why no real competence-gap producer could be built on them as-is.

### evidence

- simorgh/learning/service.py:115-125 -- UNREACHABLE text and health(): `if self._running_pipelines: return Health.ok(...)` else `return Health.degraded(self.UNREACHABLE)`; only _on_pipeline_run (line 166) populates _running_pipelines
- grep -rn --include='*.py' 'learn\.pipeline\.run\|learn\.strategy\.suggest\|draft_candidate' simorgh/ | grep -v '^simorgh/learning/' -> only contracts/topics.py:160-163 (constants), toolargs.py:102, orchestration/tools.py:51, scaffolds.py:212, profiles.py:90, cognition/parser.py comments; no publish(), no tool registration in simorgh/execution/
- wc -l: learning/pipeline.py 227, correlator.py 38, strategy.py 50 (=315, +~65 handler lines in service.py:146-210); package totals learning 992 / reflection 2145 / curiosity 1402; tests learning 1016 / reflection 2239 / curiosity 1299
- git log --since='30 days ago' --oneline -- simorgh/<pkg> | wc -l: learning 10, reflection 12, curiosity 9, orchestration 178
- ~/.simorgh/ledger/streams: reflect%3Adrift%3A* = 181 streams, reflect%3Acritique%3A* = 125; grep -c '"detected"' over drift streams = 0; grep -c '"review"' = 66; verdict distribution 37 on_track / 28 unknown / 1 drifting
- simorgh/reflection/service.py:307-321 _request_review builds `topics.COGNITION_THINK` with purpose=review, max_tokens 200, max_cost_usd 0.02, require_real_provider False; reflection/config.py:19 drift_emit_threshold=0.6; drift.py:105-116 combined() returns None below threshold
- simorgh/curiosity/drives.py:16 `_UNKNOWN_AREA_GAP = 0.6`; drives.py:37-40 returns it when ctx.gaps has no match
- simorgh/worldmodel/selfmodel.py:400-406 `def compute_gaps(...)`: docstring 'No real competence/coverage data exists yet' and `return [], []` unconditionally; worldmodel/service.py:270-273 answers SELF_GAPS from it; curiosity/service.py:507-515 consumes it
- ledger curiosity ticks/candidates: grep -o '"gap": *[0-9.]*' | sort | uniq -c -> 94 x "gap":0.6, no other value
- simorgh/curiosity/service.py:231-238 _on_provider_status reads budget['remaining_fraction']; cognition/service.py:452-460 publishes budget keys window_seconds, calls, max_calls, spend_usd, max_spend_usd, exhausted; grep -rn remaining_fraction simorgh/ hits only curiosity/service.py:233 -> worst_remaining is never set, _exploration_rate (service.py:480-488) always 1.0
- simorgh/curiosity/drives.py:58-66 _interest: `if name in topic or any(word == name for word in topic.split())`; interests.py:4-6 topics are feed URLs OR plain labels; ledger curiosity:interests holds labels e.g. "AI and AI agents"
- grep -n -i 'UNREACHABLE|learning.*degraded|drift|exploration_rate|worst_remaining|PatchPipeline|correlator' over docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html, docs/architecture-third-opinion-2026-09-18.md -> no matches (not previously reported)
- Side evidence: wc -l curiosity%3Aticks.jsonl = 161096 events; learn%3Aoutcomes.jsonl task_type distribution: 2466 unknown / 125 research / 81 patch / 3 skill / 1 project

**severity adjustment:** keep

**corrected claim:** Learning's PatchPipeline/Correlator/strategy (~380 lines incl. handlers) have no publisher or requester anywhere in simorgh/ and `draft_candidate` is not a registered tool, so Learning's health() is `degraded` on every boot by construction (learning/service.py:120-125). Reflection's DriftTracker has 181 streams and 66 LLM drift reviews (cheap: max_cost_usd 0.02, require_real_provider False) with 0 detections. Curiosity's gap drive is structurally constant at 0.6 because worldmodel/selfmodel.py:400-406 compute_gaps hard-returns empty lists, and its budget-derived exploration rate is structurally 1.0 because cognition's provider-status payload never carries the `remaining_fraction` key curiosity reads; the interest drive is a substring match of area name against interest topic strings (feed URLs or plain labels).

