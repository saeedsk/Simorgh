# refute:correctness:The Self Model is volatile: a restart fo

*Workflow: review · Phase: Refute · Agent id: `a3f1959c2d2dddb4d` · Tool calls: 10*

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
| 1 | Bash | Read Self Model header and line counts | """The Self Model. Identity is real, loaded and hashed from `docs/SOUL.md`. As of Phase 4 Wave 2 the other sections (competence, limitations, change_history, ca |
| 2 | Bash | Grep worldmodel service for fold/rebuild/subscriptions | 68: async def start(self, ctx: Context) -> None: 110: await ctx.bus.subscribe(topics.WORLD_ENV_QUERY, self._on_env_query), 111: await ctx.bus.subscribe(topics.S |
| 3 | Bash | Read worldmodel start, _apply, and system.started handler |  self._config_from_caller = config self.config = config or Config() self._ctx: Context \| None = None self._subs: list = [] self._restarts = 0 self._model = None |
| 4 | Bash | Read _apply, ledger use in worldmodel, and live SELF.md | ----_apply 167: await self._apply( 242: It goes through `_apply` like every other change to the model, 257: return model # `_apply` treats an unchanged model as |
| 5 | Bash | Read learning and reflection rebuild-at-start code | ----learning/service # Config dataclass with a `from_mapping` -- and nothing ever # called it, so changing the file changed nothing. The dominant # bug shape in |
| 6 | Bash | Check publish sites, calibration rebuild, ledger streams, and prior reviews | ----publish-competence simorgh/learning/outcomes.py:186: await self._publish(topics.LEARN_COMPETENCE_UPDATED, { simorgh/learning/service.py:38: topics.LEARN_OUT |
| 7 | Bash | Confirm publish timing, calibration publish loop, ledger stream sizes, and prior-review coverage | ----outcomes180 if self._publish is not None: recorded: dict[str, Any] = { "task_id": task_id, "task_type": task_type, "succeeded": succeeded, "verdict": verdic |
| 8 | Bash | Check ledger stream contents and whether prior review covers Self Model volatility | reflect%3Acalibration: 1 lines learn%3Aoutcomes: 2714 lines reflect%3Aself: missing self%3Amodel: missing ----calibration {"causation_id":null,"idempotency_key" |
| 9 | Bash | Check who publishes the self-patch and observation events the Self Model folds | ----self_patch_applied publishers (eval):1: no matches found: --include=*.py ----calibration-publisher-condition return set() def _record_calibration(self, task |
| 10 | Bash | Check publishers of self-patch and observation events, and patch stream count | ----self_patch_applied publishers simorgh/learning/service.py:39: topics.LEARN_STRATEGY_SUGGEST_REPLY, topics.LEARN_SELF_PATCH_APPLIED, topics.LEARN_SELF_PATCH_ |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** The claim is true of the code today and is not in the known-findings list (the known Self Model item is the never-populated capabilities["tools"]; the prior HTML review mentions selfmodel.py once, only for that, and contains zero hits for "restart", "fold", "volatile" or "SELF.md"). WorldModelService.start() (simorgh/worldmodel/service.py:99-102) builds the model with build_static_model(...) and never reads the Ledger: `grep -rn "ledger\|rebuild" simorgh/worldmodel/*.py` returns nothing. Every change goes through _apply (service.py:238-260), which mutates self._model in memory, rewrites SELF.md and publishes self.model.updated, but appends nothing to any stream; there is no `self:model` or `reflect:self` stream in ~/.simorgh/ledger/streams. The restart counter is a plain instance attribute (self._restarts, service.py:64, bumped at service.py:360-361). The wires the model folds ARE connected in-session (learning/pipeline.py:196 publishes learn.self_patch.applied; reflection/service.py:282,448 publish self.observation; outcomes.py:186 publishes learn.competence.updated; reflection/service.py:592-603 publishes reflect.calibration.updated), so this is genuinely a right-design-undermined case, not an unconnected wire: the information reaches the model, then dies with the process. Learning does rebuild its CompetenceTable from `learn:outcomes` at start (learning/service.py:74) but only publishes learn.competence.updated inside _record on a new outcome (outcomes.py:176-191), so the World Model only hears about task types that complete after boot; Reflection's CalibrationTable is constructed fresh (reflection/service.py:149, again at :169) with no rebuild, and its snapshot only reaches the Ledger at reflect time. The live evidence matches: ~/.simorgh/worldmodel/self/SELF.md (v42, 2026-09-18 17:09) shows "bad at: (none recorded yet)", "changed: (none recorded yet)", "Restarts recorded: 1", competence "unknown 97% (2466)" only, while the Ledger holds reflect:calibration with one snapshot for research (stated 0.78 vs empirical 0.526, 19 samples) and learn:outcomes with 2,714 events including 44 ('patch', True), 60 ('research', True), 65 ('research', False). Minor nits that do not change the verdict: the recommendation names a `reflect:self` stream that does not exist (self.observation events are not durably streamed under that name), and "44 applied patches" are patch-type task outcomes rather than learn.self_patch.applied events, but change_history being empty after a restart holds either way. Severity medium is right for one laptop/one family: it undermines the subsystem whose stated purpose is continuity, and the fix is small because the mutators are already pure.

### evidence

- simorgh/worldmodel/selfmodel.py:16-23 -- module docstring: 'mutations here are in-memory only for this session, not yet a fold of a durable `self:model` Ledger stream across restarts'
- simorgh/worldmodel/service.py:99-102 -- start() does `self._model = build_static_model(soul_path=..., areas=..., continuity={"restarts": self._restarts})`; no ledger read. `grep -rn "ledger\|rebuild" simorgh/worldmodel/*.py` -> no output
- simorgh/worldmodel/service.py:238-260 -- _apply() mutates self._model in memory, rewrites SELF.md, publishes self.model.updated; appends to no ledger stream
- simorgh/worldmodel/service.py:64,360-361 -- self._restarts = 0 in __init__; _on_system_started does self._restarts += 1 (in-process counter)
- ls ~/.simorgh/ledger/streams -> reflect%3Aself and self%3Amodel both missing; reflect%3Acalibration.jsonl = 1 line; learn%3Aoutcomes.jsonl = 2714 lines
- reflect:calibration snapshot payload: {"brier": 0.2179, "empirical_accuracy": 0.5263, "samples": 19, "stated_confidence": 0.78, "task_type": "research"}
- learn:outcomes counts by (task_type, succeeded): ('unknown', True) 2403; ('research', False) 65; ('unknown', False) 63; ('research', True) 60; ('patch', True) 44; ('patch', False) 37
- ~/.simorgh/worldmodel/self/SELF.md (v42, 2026-09-18 17:09): '## How well I do it\n- unknown 97% (2466)' / '## What I know I'm bad at\n(none recorded yet)' / '## What I've changed about myself (last 10)\n(none recorded yet)' / 'Restarts recorded: 1.'
- simorgh/learning/service.py:74 -- `await ctx.ledger.rebuild(self._competence, "learn:outcomes")` at Learning start (the fold pattern exists elsewhere)
- simorgh/learning/outcomes.py:176-191 -- learn.competence.updated is published only inside _record on a new outcome
- simorgh/reflection/service.py:149,169 -- `self._calibration = CalibrationTable(self.config)` built fresh; no rebuild from reflect:calibration; snapshot appended and published only in the reflect pass at :592-603
- In-session wires are connected (so this is not an unconnected wire): learning/pipeline.py:196 publishes LEARN_SELF_PATCH_APPLIED; reflection/service.py:282,448 publish SELF_OBSERVATION; worldmodel/service.py:117-124 subscribes to all of them
- Not already known: docs/architecture-audit-2026.md mentions the Self Model only for capabilities['tools'] (lines 17,32-34); docs/architecture-review-2026-09-18.html has 1 'selfmodel' hit (the tools key) and 0 hits for 'restart', 'fold', 'volatile', 'SELF.md'

**severity adjustment:** keep

**corrected claim:** The Self Model is built static at every start (worldmodel/service.py:99-102) and mutated in memory only (_apply, :238-260); neither it nor its inputs are folded from the Ledger on boot, so competence, limitations, change history and restart count reflect only events since the current process started. The Ledger holds a reflect:calibration snapshot (research: stated 0.78 vs empirical 0.53, n=19) and 2,714 learn:outcomes (44 successful patch-type tasks among them), yet the live SELF.md after one restart shows no limitations, no changes, one restart and a single 'unknown' competence row. Note: no `reflect:self` stream exists to fold from; limitations would need self.observation events to be streamed durably first.

