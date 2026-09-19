# refute:correctness:25 of 137 non-reply topics have only one

*Workflow: review · Phase: Refute · Agent id: `a2604bb7625963252` · Tool calls: 6*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "big-picture-proportionality". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "25 of 137 non-reply topics have only one side (or none), each with a schema file, a declaration and tests",
    "kind": "over-engineering",
    "severity": "medium",
    "claim": "The catalogue is 174 types; after excluding the 37 `.reply` types, 10 are published and never consumed, 9 are subscribed and never published, 5 are declared and never referenced, and 1 is referenced only in a comment -- the 'unconnected wire' shape exists at the contract level and nothing fails on it.",
    "evidence": [
      "topics_audit2.py over simorgh/ (excluding contracts/): \"{'both': 111, 'unreferenced': 5, 'pub-only': 10, 'reply': 37, 'ref-only': 1, 'sub-only': 10}\" (memory.forget was a false positive via an aliased import, so sub-only is 9)",
      "pub-only: benchmark.run.completed, curiosity.interest.updated, plan.approved, reflect.alert.cleared, reflect.alert.raised, self.model.updated, system.schedule.added, task.dependency.satisfied, tool.invoked, world.env.observed",
      "sub-only: cognition.compact.request, curiosity.discover.request, curiosity.interest.follow_up.request, curiosity.share.request, learn.pipeline.run, learn.strategy.suggest, reflect.review.request, research.finding.recorded (plus task.progress, which is a ledger-only event read by orchestration/resume.py:58 -- not a bus defect)",
      "unreferenced: learn.experiment.result, percept.file.changed, plan.reground, plan.reground.reply, system.reload, ui.rendered",
      "ls simorgh/contracts/schema | wc -l -> 174; contracts/topics.py:1-8 \"CATALOG is the authoritative list ... messages/ must define exactly this set (tests/simorgh/contracts/test_catalog.py proves it)\" -- the test proves the catalogue matches itself, not that it is used"
    ],
    "why_it_matters": "A catalogue that is 18% one-sided teaches the model (and the next reader) that a topic existing means a capability exists. Three of the sub-only requests are the whole public surface of Curiosity and Reflection review, so those subsystems are partly unreachable by design rather than by bug.",
    "recommendation": "Turn the audit script into a test: fail on any CATALOG type that is neither published nor consumed in simorgh/, with a short allow-list of externally-triggered types. Delete the 6 unreferenced types and the dead-pipeline types (learn.pipeline.run, learn.strategy.suggest, learn.experiment.result) with finding 1; decide per remaining item whether to wire or remove.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count schema files and read topics.py header |  174 """The topic catalog: every domain, every message type (as a constant), subscription-pattern matching, reply naming, and the reserved-topology table the Ke |
| 2 | Bash | Audit CATALOG topic usage across simorgh/ excluding contracts | catalog 174 Counter({'both': 57, 'other': 40, 'reply': 37, 'sub-only': 23, 'pub-only': 12, 'unreferenced': 5}) sub-only action.needs_human simorgh/interface/ser |
| 3 | Bash | Grep every named topic across simorgh, tools and tests | === benchmark.run.completed (BENCHMARK_RUN_COMPLETED) : 4 hits simorgh/benchmark/service.py:40: topics.BENCHMARK_PROGRESS, topics.BENCHMARK_RUN_COMPLETED, topic |
| 4 | Bash | Check wildcard subscriptions, catalog test, and prior review docs | --- wildcard subs (eval):1: no matches found: --include=*.py --- ledger subscribes? simorgh/ledger/service.py:63: self._subscription = await ctx.bus.subscribe(t |
| 5 | Bash | Check wildcard matching, generic publish surfaces, and internal paths of sub-only handlers | --- matches() def source_name(source: str) -> str: """`orchestration@w3` -> `orchestration` (the subsystem identity).""" return source.split("@", 1)[0] def matc |
| 6 | Bash | Inspect edits_kept usage, camera generic topic, curiosity/reflection internal paths, and prior docs | --- edits_kept simorgh/orchestration/resume.py:32:from .session import EDITS_KEPT simorgh/orchestration/resume.py:63: elif e.type == EDITS_KEPT: simorgh/orchest |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The counts are reproducible and correct for simorgh/ today: CATALOG has 174 types, 37 end in `.reply` (python -c over simorgh.contracts.topics), and my own grep of every named topic (constant name or string literal, excluding contracts/ and schema/) confirms 5 non-reply types with zero references anywhere in simorgh/, tools/ or tests/ (learn.experiment.result, percept.file.changed, plan.reground, system.reload, ui.rendered), 10 types published in simorgh/ with no subscribe()/handler entry in simorgh/, and 9 types subscribed in simorgh/ with no publisher in simorgh/ (memory.forget correctly excluded: execution/tools.py publishes it). There are no wildcard ('*'/'#') subscriptions anywhere in simorgh/ outside the bus docstring, so nothing consumes the pub-only types implicitly. The catalog test characterization is accurate: tests/simorgh/contracts/test_catalog.py:17 asserts CATALOG == all_specs() and checks schema files/reply pairing; nothing checks that a type is used. This contract-level audit is not in the prior review documents (grep of docs/architecture-audit-2026.md, architecture-review-2026-09-18.html, architecture-third-opinion-2026-09-18.md finds no pub-only/sub-only/one-sided discussion). However the finding's impact statement is overstated and part of it is already known/deliberate: (1) learn.pipeline.run's missing publisher is self-declared by the subsystem (simorgh/learning/service.py:98 "Nothing anywhere publishes `learn.pipeline.run`", :116 health detail "no publisher for learn.pipeline.run, and draft_candidate is not a registered tool") and PINNED by a test (tests/simorgh/learning/test_service.py:51 fails if a publisher appears) -- so the project already uses exactly the recommended 'turn it into a test' pattern for that one, and this overlaps the known 'self_patch.draft not registered' item. (2) "Three of the sub-only requests are the whole public surface of Curiosity and Reflection review, so those subsystems are partly unreachable" is wrong: curiosity.discover.request's handler is `await self._run_tick(force=True)` (curiosity/service.py:314-316) and the same _run_tick plus the share decision run on every idle tick (:364-369); reflection's review handler mines the same PatternMiner that _on_sleep -> _run_pass runs on every sleep tick and publishes REFLECT_PATTERNS_FOUND (reflection/service.py:561-569, 605-613), which planning consumes. Curiosity's interest.add and interest.list.request are also published from interface/dispatch.py. So the unpublished request/reply pairs are unused on-demand entry points, not the subsystems' whole reachable surface. (3) benchmark.run.completed has a real consumer outside the package at tools/bench_instance.py:153, and plan.approved, reflect.alert.*, self.model.updated, tool.invoked are subscribed by integration tests -- 'never consumed' holds only within simorgh/. (4) The '6 unreferenced' list includes plan.reground.reply, which is one of the 37 reply types, so it is double-counted. (5) Several pub-only types are pure facts (task.dependency.satisfied, world.env.observed, system.schedule.added) in an event-sourced design where emitting a fact nobody yet reads is cheap and ledger-visible; that is a much weaker smell than the sub-only requests. Net: the arithmetic and the 'catalog test proves self-consistency only' point stand and are new; the 'why it matters' should be cut back, and severity is better at low.

**corrected claim:** Of the 137 non-reply types in the 174-type CATALOG, 5 are referenced nowhere in simorgh/, tools/ or tests/ (learn.experiment.result, percept.file.changed, plan.reground, system.reload, ui.rendered) yet each carries a schema file and dataclass; 10 are published by a subsystem but subscribed by no subsystem (one, benchmark.run.completed, is consumed by tools/bench_instance.py:153; several are pure ledger-visible facts); and 9 are subscribed but never published inside simorgh/ -- three of these (learn.pipeline.run, learn.strategy.suggest, with learn.experiment.result) are already self-declared dead by learning/service.py:98-116 and pinned by tests/simorgh/learning/test_service.py:51. The unpublished curiosity.*.request and reflect.review.request are unused on-demand entry points, not unreachable capabilities: the same code runs from the idle/sleep ticks (curiosity/service.py:314-316, 364-369; reflection/service.py:561-569, 605-613). tests/simorgh/contracts/test_catalog.py:17 proves only CATALOG == all_specs(), never that a type is used.

### evidence

- python -c 'from simorgh.contracts import topics; c=list(topics.CATALOG); print(len(c), sum(t.endswith(".reply") for t in c))' -> 174 37
- ls simorgh/contracts/schema | wc -l -> 174
- grep -rn over simorgh/ tools/ tests/ (excluding contracts/, schema/): LEARN_EXPERIMENT_RESULT, PERCEPT_FILE_CHANGED, PLAN_REGROUND, SYSTEM_RELOAD, UI_RENDERED -> 0 hits each
- pub-only in simorgh/ (publish site, no subscribe/handler): benchmark/service.py:417, curiosity/service.py:255,273, planning/service.py:1277 (PLAN_APPROVED), reflection/service.py:744,762, worldmodel/service.py:418 (SELF_MODEL_UPDATED), kernel/scheduler.py:231 (SYSTEM_SCHEDULE_ADDED), planning/service.py:655 (TASK_DEPENDENCY_SATISFIED), execution/service.py:857 (TOOL_INVOKED), worldmodel/service.py:56 (WORLD_ENV_OBSERVED, only the produces tuple)
- external consumer of a 'pub-only' type: tools/bench_instance.py:153 `await kernel.bus.subscribe(topics.BENCHMARK_RUN_COMPLETED, _on_completed)`
- sub-only in simorgh/ (subscribe, no publisher): cognition/service.py:223, curiosity/service.py:161,162,165, learning/service.py:84,85, reflection/service.py:199, planning/service.py:176 (RESEARCH_FINDING_RECORDED)
- no wildcard subscriptions: grep -rn -E 'subscribe\([^)]*\*' simorgh -> none outside simorgh/bus/api.py:62 docstring; topics.matches() at contracts/topics.py:337 supports '*'/'#' but no subsystem uses them
- already self-declared: simorgh/learning/service.py:98 '#: 1. Nothing anywhere publishes `learn.pipeline.run`'; :116 'no publisher for learn.pipeline.run, and draft_candidate is not a registered tool'; tests/simorgh/learning/test_service.py:51 regex pins that no publish site for LEARN_PIPELINE_RUN exists
- capability reachable without the request: simorgh/curiosity/service.py:314-316 `_on_discover_request` -> `self._run_tick(force=True)`; :364-369 `_on_tick_idle` runs `_run_tick` and `maybe_share`; simorgh/reflection/service.py:561-563 `_on_sleep` -> `_run_pass` mines patterns and publishes REFLECT_PATTERNS_FOUND; :605-613 `_on_review_request` mines the same `self._patterns`
- curiosity requests that ARE published: simorgh/interface/dispatch.py publishes CURIOSITY_INTEREST_ADD and CURIOSITY_INTEREST_LIST_REQUEST
- tests/simorgh/contracts/test_catalog.py:17 `self.assertEqual(sorted(CATALOG), sorted(all_specs()))` -- self-consistency only; no usage check in the file
- prior reviews: grep -i 'pub-only|sub-only|one-sided|never consumed|never published' over docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html, docs/architecture-third-opinion-2026-09-18.md -> no hits (only the JSONL 'sweep_unreferenced_blobs' line)

**severity adjustment:** lower

