# `simorgh.learning`

Turns recorded task outcomes into procedural memory, and runs the
self-patch / skill-acquisition pipeline as policy-only orchestration —
every actual file read/write/test/commit/relaunch is still just an
`action.proposed` to Guardian → Execution. Spec:
[`docs/blueprint/subsystems/11-learning.md`](../../docs/blueprint/subsystems/11-learning.md);
protocol: `simorgh.contracts.protocols.Subsystem`. Imports only
`simorgh.contracts`, `simorgh.ledger.client`, and the standard library
(enforced by `tests/simorgh/test_module_boundaries.py`).

| Module | What |
|---|---|
| `service.py` | `Service` — the `Subsystem`: wires everything below to the real Bus/Ledger, subscribes `task.*`/`action.result`/`action.denied`/`verify.result`/`learn.pipeline.run`/`learn.strategy.suggest` |
| `outcomes.py` | `OutcomeRecorder` — `task.completed`/`.failed`/`.blocked` → `learn:outcomes` Ledger events → `learn.outcome.recorded` + `learn.competence.updated`; derives `task_type` by reading the task's own `task:<id>` stream (never guessed from the terminal message) |
| `competence.py` | `CompetenceTable` — the projection over `learn:outcomes`: Laplace-smoothed success rate, shrinkage below `min_samples_for_trust`, UCB1-shaped `suggest()` ranking, calibration |
| `strategy.py` | `build_reply()` — answers `learn.strategy.suggest` from `CompetenceTable`; absence of a `strategy` key *is* the floor signal (the real schema has no separate `floor` field) |
| `pipeline.py` | `PatchPipeline` — the self-patch/skill state machine: draft → verify → apply → commit → activate, with bounded retry-with-feedback and revert-on-activation-failure |
| `correlator.py` | `Correlator` — matches independently-published `action.result`/`action.denied`/`verify.result` events back to the pipeline step awaiting them (these are NOT `bus.request()`/`.reply()` pairs in the real system) |
| `config.py`, `models.py` | `Config` (retry/timeout/exploration knobs), plain dataclasses (`Strategy`, `Outcome`, `TaskTypeStats`, ...) |

## Using it

```python
from simorgh.learning.service import Service as LearningService

# registered like any other subsystem (simorgh/kernel/registry.py, layer 4)
```

Drive it over the bus:

```python
await bus.publish(Message.new("learn.pipeline.run", source="orchestration",
    payload={"task_id": "t1", "kind": "patch", "description": "...",
              "subject": "src/memory/retrieval.py"}))
# -> learn.pipeline.completed(outcome: applied|reverted|rejected|floor)

reply = await bus.request(Message.new("learn.strategy.suggest", source="planning",
    payload={"task_type": "patch:src/memory"}))
# -> {"success_rate": 0.7, "samples": 12, "strategy": {...}}  (or no "strategy" key: floor)
```

## Tests

`python3 -m unittest discover -s tests/simorgh/learning -t .` (unit —
competence math, outcome recording/idempotency, strategy replies, the
full pipeline state machine against fake Guardian/Execution/Verification
callbacks). `python3 -m unittest tests.simorgh.integration.test_learning_pipeline_kernel_boot`
(the real `Service` registered with a real booted Kernel via
`mock.patch("simorgh.kernel.service.build_factories", ...)`, driven by
toy Guardian/Verification subsystems answering with real message shapes).

## Build log

- 2026-09-06 — Phase 1: built the outcome/competence/strategy core and
  the full patch/skill pipeline (spec Flow 4) end to end, including
  Kernel-boot integration coverage. **Deliberately not built this
  pass** (spec §5.2/§7, tracked so a later pass has a real punch list,
  not silence): `evolve` batch pipelines (multi-patch, whole-batch
  revert) — `learn.pipeline.run{kind: evolve}` returns an honest
  `floor` outcome rather than a silent no-op; hot-swap A/B experiment
  runner (`learn.experiment.result`); knowledge distillation
  (research/reflection → proposed KB doc writes); crash-mid-pipeline
  resume from `learn:patch:<id>`'s last checkpoint (checkpoints ARE
  written for every transition, for audit and for a future resume
  pass — `Service.start()` does not yet scan for and resume orphaned
  in-flight pipelines on boot).

## Open questions

See spec §12, and these gaps found against the real generated contracts
(`simorgh/contracts/messages/learn.py`, `action.py`) while building:

1. **`learn.strategy.suggest.reply` is a single best strategy, not a
   ranked list with a `floor: bool`.** The prose spec (§3.3) describes
   `suggestions: [...]` + `floor`; the real schema is
   `{success_rate, samples, strategy?}`. This build treats the field's
   *absence* as the floor signal and never fabricates a ranked list the
   wire format doesn't carry.
2. **`ActionResult` has no `metadata` field**, unlike the `ToolResult`
   Python protocol (`contracts/protocols.py`) which does. There is
   therefore no clean channel for Execution to signal "floor" (no
   real provider available) distinctly from an ordinary draft failure
   through the message layer — this build treats every `ok: false` as
   a uniformly retryable failure, feeding `error` back as
   `prior_reasons`. A non-breaking fix would be an optional
   `metadata: Obj()` field on `ActionResult`.
3. `learn.pipeline.run`/`learn.pipeline.completed` were confirmed to
   **already exist** in the real catalog — the spec's own note
   suggesting they might need adding is stale.
4. A `FakeClock` (manual-advance, from `tests/simorgh/helpers.py`)
   raced far ahead of real elapsed time in the Kernel-boot integration
   test — some kernel-side housekeeping loop calls `clock.sleep()`
   internally, and with nothing throttling it against the test's own
   real-time `asyncio.wait_for` calls, simulated time ran far enough
   ahead to spuriously trip `PatchPipeline`'s `max_pipeline_wall_seconds`
   ceiling. Worked around by booting with the real wall clock instead;
   worth a real fix (or at least a documented caution) wherever a
   future test wants both a long-running booted Kernel *and* a
   manually-advanced clock.
