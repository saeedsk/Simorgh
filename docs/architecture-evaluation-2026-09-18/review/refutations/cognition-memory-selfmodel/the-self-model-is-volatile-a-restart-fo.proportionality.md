# refute:proportionality:The Self Model is volatile: a restart fo

*Workflow: review · Phase: Refute · Agent id: `af4dc0a39d7bda9dd` · Tool calls: 8*

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
    "title": "The Self Model is volatile: a restart forgets competence, limitations and change history, so the prompt's self-knowledge is whatever happened since boot",
    "kind": "right-design-undermined",
    "severity": "medium",
    "claim": "The Self Model is mutated in memory only and never folded from a ledger stream, so the one real self-finding Reflection produced (research overconfident: stated 0.78 vs empirical 0.53) and 44 applied patches are absent from the live model, whose rendered state after one restart is 'bad at: none, changed: none, competence: unknown 97%'.",
    "evidence": [
      "simorgh/worldmodel/selfmodel.py:16-23: 'mutations here are in-memory only for this session, not yet a fold of a durable `self:model` Ledger stream across restarts'",
      "~/.simorgh/worldmodel/self/SELF.md (live): `## What I know I'm bad at\\n(none recorded yet)` / `## What I've changed about myself (last 10)\\n(none recorded yet)` / `Restarts recorded: 1`",
      "ledger: `reflect:calibration` 1 snapshot `{\"brier\": 0.218, \"empirical_accuracy\": 0.526, \"samples\": 19, \"stated_confidence\": 0.78, \"task_type\": \"research\"}`; `learn:outcomes` has 44 `('patch', True)`; neither appears in the live model",
      "simorgh/learning/service.py:74 rebuilds the CompetenceTable from `learn:outcomes` at start but only publishes `learn.competence.updated` on new outcomes (outcomes.py:127-131), so World Model learns a task type only when one finishes after boot; reflection's CalibrationTable is likewise in-process (reflection/service.py:149)"
    ],
    "why_it_matters": "The blueprint's idea -- the Self Model is exactly the fold of a stream -- is the right one and the rest of the system (Learning's CompetenceTable via `ledger.rebuild`) already does it. Leaving the one subsystem whose job is continuity as the one without it means 'what I know about myself' is reset by the loader's own rollbacks and by every `sim.sh` restart.",
    "recommendation": "At worldmodel start, fold `learn:outcomes`, `reflect:calibration` and `reflect:self` through the existing pure mutators (they are already `(SelfModel, fields) -> SelfModel`), or have Learning and Reflection re-publish their current tables on `system.started`. Either is a day's work and turns SELF.md into a real record.",
    "confidence": 0.92
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read the Self Model module header | """The Self Model. Identity is real, loaded and hashed from `docs/SOUL.md`. As of Phase 4 Wave 2 the other sections (competence, limitations, change_history, ca |
| 2 | Bash | Locate worldmodel service handlers and any ledger fold | 3:calibration, limitations, change history, and skills folded in real 28: bump_restarts, 64: self._restarts = 0 101: areas=self._capability_map.areas(), continu |
| 3 | Bash | Read worldmodel service start and self-fold handlers |  topics.WORLD_ENV_QUERY_REPLY, topics.SELF_SUMMARY_REPLY, topics.SELF_GAPS_REPLY, topics.WORLD_ENV_OBSERVED, topics.SELF_MODEL_UPDATED, topics.SYSTEM_HEALTH, )  |
| 4 | Bash | Read _apply, live SELF.md, learning rebuild, reflection calibration | === _apply 167: await self._apply( 242: It goes through `_apply` like every other change to the model, 257: return model # `_apply` treats an unchanged model as |
| 5 | Bash | Trace producers of the self-model input events | === _record/publish in outcomes.py simorgh/learning/competence.py:3:4.4) -- `apply()` never does anything a fresh `rebuild()` wouldn't also simorgh/learning/com |
| 6 | Bash | Find event producers, ledger streams, and prompt consumers of the Self Model | === producers simorgh/learning/service.py:39: topics.LEARN_STRATEGY_SUGGEST_REPLY, topics.LEARN_SELF_PATCH_APPLIED, topics.LEARN_SELF_PATCH_REVERTED, simorgh/le |
| 7 | Bash | Inspect ledger streams and prompt consumers of the self model | === calibration 1 reflect%3Acalibration.jsonl {"causation_id":null,"idempotency_key":null,"payload":{"brier":0.21794736842105264,"empirical_accuracy":0.52631578 |
| 8 | Bash | Check prompt consumption of self model and whether self-patch events ever fired | === assembler self usage 58: summary = await self._try_request(topics.SELF_SUMMARY, {"budget_tokens": 300}) 60: blocks.append(self._block("self_summary", summar |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core mechanism is confirmed: the World Model builds a static SelfModel at start (worldmodel/service.py:97-101), keeps `_restarts = 0` in process memory (line 64), never calls `ledger.rebuild`/replay for any `learn:`/`reflect:` stream, and the module docstring says so (selfmodel.py:16-23). The live SELF.md matches the finding verbatim (limitations none, changes none, restarts 1). The one `reflect:calibration` snapshot (research 0.78 stated / 0.526 empirical, 19 samples) is on disk and absent from the live model, and Reflection's CalibrationTable is rebuilt fresh each process (reflection/service.py:149, snapshot appended at 597-600 but never read back). The author already felt the gap: `_ingest_loader_rollback` (service.py:133-172) is a hand-rolled JSON side-channel to persist exactly one self-fact across boots, which is the fold-that-isn't.

Two parts of the claim are overstated. (1) Competence is not "whatever happened since boot": `learn.competence.updated` carries the cumulative aggregate from the CompetenceTable that Learning rebuilt from `learn:outcomes` at start (outcomes.py:186-191, learning/service.py:74), which is why the live SELF.md shows "unknown 97% (2466)" = 2403+63 lifetime samples. Any task type self-heals on its first post-boot outcome; only the calibration overlay (stated vs empirical) does not. (2) The "44 applied patches absent from change_history" evidence is a misattribution: those are `learn:outcomes` events with task_type 'patch' (competence input), not `learn.self_patch.applied` events. The only publisher of that event is PatchPipeline (learning/pipeline.py:196), which learning/service.py:95-118 documents as UNREACHABLE (no publisher for learn.pipeline.run); grep finds no self_patch-applied record in any ledger stream. So change_history would be empty even with no restarts, and folding `learn:outcomes` through the mutators as recommended would not populate it.

Scale lens: at one laptop/one family the loss is real but small today. The prompt gets a 300-token self summary (cognition/assembler.py:58-60), and the only data actually being lost across restarts is one calibration overlay, the restart counter, and pattern-mined limitations (reflection/service.py:591) when they occur. The fix is proportionate (mutators are pure, a fold-on-boot is tens of lines), but its payoff is bounded until the self-patch producer is wired, which is already known. Right design, implementation undermines it, severity lower than medium.

### evidence

- simorgh/worldmodel/selfmodel.py:16-23 -- docstring: 'mutations here are in-memory only for this session, not yet a fold of a durable `self:model` Ledger stream across restarts'
- simorgh/worldmodel/service.py:64 `self._restarts = 0`; :97-101 `build_static_model(... continuity={"restarts": self._restarts})`; no `ledger.rebuild`/replay anywhere in start() (grep 'rebuild|fold|self:model' in worldmodel/service.py: 0 hits)
- simorgh/worldmodel/service.py:133-172 `_ingest_loader_rollback`: persists one self-fact across boots via `last_rollback.json` + `.last_rollback_ingested` stamp -- a hand-rolled substitute for the missing fold
- ~/.simorgh/worldmodel/self/SELF.md (live, v42 2026-09-18 17:09): '## How well I do it\n- unknown 97% (2466)' / '## What I know I'm bad at\n(none recorded yet)' / '## What I've changed about myself (last 10)\n(none recorded yet)' / 'Restarts recorded: 1.'
- ~/.simorgh/ledger/streams/reflect%3Acalibration.jsonl: 1 line, payload {task_type: research, stated_confidence: 0.78, empirical_accuracy: 0.526, brier: 0.218, samples: 19}; `ls | grep -c reflect%3Aself` -> 0 (no reflect:self stream exists)
- simorgh/reflection/service.py:149 `self._calibration = CalibrationTable(self.config)` (fresh per process); :597-603 appends snapshot to CALIBRATION_STREAM and publishes REFLECT_CALIBRATION_UPDATED, no rebuild from that stream
- simorgh/learning/outcomes.py:186-191 publishes LEARN_COMPETENCE_UPDATED with `self._competence.success_rate/calibration/samples(task_type)` from the table rebuilt at learning/service.py:74 -- cumulative, hence 2466 = 2403 ('unknown',True) + 63 ('unknown',False) in learn:outcomes (python3 Counter over the 2714-line stream)
- learn:outcomes Counter: ('patch', True) 44, ('patch', False) 37 -- task outcomes, not self_patch.applied events
- simorgh/learning/pipeline.py:196 is the sole publisher of LEARN_SELF_PATCH_APPLIED; simorgh/learning/service.py:95-118 UNREACHABLE: 'no publisher for learn.pipeline.run, and draft_candidate is not a registered tool -- PatchPipeline cannot run'; `grep -l self_patch.applied ~/.simorgh/ledger/streams/learn*` -> none
- simorgh/cognition/assembler.py:58-60 requests SELF_SUMMARY with budget_tokens=300; selfmodel.py:251-252 render order identity, substrate, competence, limitations, ...

**severity adjustment:** lower

**corrected claim:** The Self Model is never folded from the Ledger at boot (worldmodel/service.py:97-101, selfmodel.py:16-23), so limitations, the calibration overlay and the restart counter reset on every restart; the author already works around this for one fact with a JSON side-file (_ingest_loader_rollback). However, competence largely self-heals because Learning republishes cumulative, ledger-rebuilt aggregates on each new outcome (outcomes.py:186-191; live SELF.md shows 2466 lifetime samples), and the empty change_history is not a restart artefact: its only producer, learn.self_patch.applied, comes from the PatchPipeline that learning/service.py:95-118 documents as unreachable, so the 44 'patch' outcomes in learn:outcomes were never change-history events. Net: right design, small implementation gap, low practical loss today (one calibration snapshot, restart count); a fold-on-boot of reflect:calibration plus a start-time competence republish is proportionate but low-payoff until self-patching itself is wired.

