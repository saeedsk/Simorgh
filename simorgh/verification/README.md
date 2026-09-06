# `simorgh/verification`

Implements `docs/blueprint/subsystems/10-verification.md`. Consumes
`verify.requested` (command, group `verification`) and `plan.proposed`
(event); produces `verify.result` / `plan.reviewed`. Runs mechanical
checks cheapest-first (stopping at the first failure), a model-reviewed
semantic checklist at LIGHT+ rigor, and trajectory metrics at STANDARD+;
combines all three into one verdict. Never decides safety itself (asks
Guardian via `guardian.review`), never generates a checklist itself
without asking Cognition (`cognition.think`), and never runs a tool
itself (proposes `action.proposed` and awaits the matching
`action.result` by `action_id` for the two checks that need real
execution: `isolated_test_suite`, `run_python_sandboxed`).

Every external call (`_act`/`_think`/`_review` in `service.py`) is
bounded by a timeout and degrades honestly to `insufficient`/`floor:true`
rather than hanging or producing a false `fail` -- important since
sibling subsystems (Cognition, Guardian, Execution) may not be running
yet when this package's own tests, or an early boot, exercise it.

## Layout

- `api.py` -- shared dataclasses/`Check` Protocol (`Rigor`, `VerifyRequest`,
  `ActionResult`, `ReviewReply`, `ThinkReply`, `Feedback`, `CheckResult`,
  `CheckContext`).
- `config.py` -- `VerificationConfig`, defaults from the spec's section
  3.5 table (`SIMORGH_VERIFICATION_RIGOR` env var forces a rigor level).
- `parsing.py` -- `parse_verdict`: scans every line for a standalone
  YES/NO token; a non-answer is `None`, never silently `"no"`
  (milestone-92, docs/EVOLUTION.md).
- `rigor.py` -- `select_rigor`: `max(by_kind[kind], by_reversibility[reversibility])`,
  clamped by `forced_rigor`.
- `checks/` -- the six mechanical `Check` plugins (`syntax`, `docstring`,
  `invariants`, `denylist_immunity`, `sandbox_smoke`, `isolated_suite`),
  cheapest-first (`free` < `cheap` < `expensive`); `ALL_CHECKS` in
  `checks/__init__.py`.
- `checklist.py` -- `generate_checklist`/`evaluate_checklist`: a
  separately-prompted semantic review that never sees the generator's
  own conversation.
- `trajectory.py` -- `compute_trajectory`: reads `task:<id>` from the
  Ledger for step/wasted/denied/recovered counts.
- `verdict.py` -- `combine`: mechanical failure > required-item "no" >
  denied-actions-over-max > insufficient-answered-fraction (never
  `fail`) > `pass`; `feedback_to_wire` for the `verify.result.feedback`
  wire shape.
- `planreview.py` -- `review_plan`: mechanical items (dependency
  ordering, protected target, step count) plus model-reviewed goal
  coverage, for `plan.proposed` -> `plan.reviewed`.
- `service.py` -- `VerificationService`, the `Subsystem` wiring
  everything to the bus/ledger.

## Contracts note

The wire schemas (`simorgh/contracts/schema/*.v1.json`) are the source
of truth over this package's own doc comments where the two disagree
(per `simorgh/contracts/README.md`). Notable divergences from an earlier
draft of the spec's own prose, reconciled during this build:

- `verify.requested.kind` is `task | plan | self_patch | skill` only.
- `guardian.review.kind` is `self_patch | skill` only -- every other
  verification `kind` is reviewed the same way `self_patch` is
  (`_guardian_kind` in `service.py`).
- `cognition.think.purpose` has no `"checklist"`/`"plan_review"` value;
  every `think()` call here uses `purpose="review"`.
- `verify.result.checklist[]` and `plan.reviewed.checklist[]` items are
  `{q, answer, evidence}` (not `{question, ...}`), with `answer` a
  required non-null string (`"unanswered"` stands in for "no verdict
  parsed").
- `verify.result.feedback` is `{items: [{what, why, suggested_fix}]}` --
  narrower than this package's own richer `Feedback` dataclass;
  `retryable`/`revise_hint` ride along as additional properties.

## Testing

- `tests/simorgh/verification/` -- unit tests per module (parsing,
  rigor, docstring/invariants ports, checklist aggregation, trajectory,
  verdict combination, plan-review mechanical items, per-`Check`
  `applies`/`run`).
- `tests/simorgh/integration/test_verification_scenarios.py` -- spec
  section 8 acceptance scenarios (S1 self-patch pass, S2 docstring
  regression, S3 reviewer non-answer -> `insufficient_evidence`, S5
  protected target -> non-retryable fail, duplicate-request re-emit)
  over a real `BusClient` + `FakeLedger`
  (`tests/simorgh/bus/harness.py`) with stand-in `cognition`/`guardian`
  subsystems -- not the Kernel, per `simorgh/kernel/registry.py`'s own
  guidance for concurrent subsystem-track forks.

Not yet built against this package: `simorgh/kernel/registry.py`'s
`FACTORIES` entry for `verification` (a one-line addition once merged;
left to whoever integrates the Phase 1/2 subsystems together, since
`registry.py` is shared across every concurrent subsystem build).
