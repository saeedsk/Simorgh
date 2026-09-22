# verification -- contract

One-line status: layer 3 · 3,153 lines · 18 test files · lock: `verification` in docs/modules/locks.toml

## Purpose

Verification owns the verdict on finished work: for each `verify.requested` it runs the applicable mechanical checks cheapest-first (stopping at the first failure), a model-answered semantic checklist at LIGHT rigor and above, and trajectory metrics from the task's `task:<id>` stream at STANDARD and above, then combines them into `pass`, `fail` or `insufficient_evidence` on `verify.result` (`service.py:135-201`). It also reviews plans (`plan.proposed` to `plan.reviewed`). It must never decide safety itself (it asks Guardian via `guardian.review`), never write its own checklist without Cognition, and never turn a non-answer or a missing sibling into `fail`: every outbound call is bounded and degrades to `insufficient_evidence` or a skipped check (`parsing.py`, `verdict.py`). The shaping design decision is that a verdict is only as good as the evidence it reads, so checks since 2026-09-09 open the files the session actually wrote (`checks/_files.py`) and read its step log, rather than judging the model's prose. It is meant to run no tool itself; the exception is `checks/_baseline.py`, which runs `git` and `pytest` directly (see Known issues).

## Files

| File | For |
|---|---|
| `simorgh/verification/__init__.py` | marks the regular package (empty docstring only) |
| `simorgh/verification/api.py` | internal types: `Rigor`, `VerifyRequest`, `CheckResult`, `CheckContext`, the `Check` protocol |
| `simorgh/verification/checklist.py` | asks Cognition for a checklist and for each item's YES/NO; parses `[optional]` tags |
| `simorgh/verification/checks/__init__.py` | `ALL_CHECKS`, the ordered registry of the eleven mechanical checks |
| `simorgh/verification/checks/_baseline.py` | red-suite attribution: re-runs failing tests at the base revision and quietly on the changed tree |
| `simorgh/verification/checks/_files.py` | `written_paths` / `read_repo_file`: what the session wrote, read from its worktree |
| `simorgh/verification/checks/denylist_immunity.py` | asks Guardian's review for a `candidate`/`code` string (never fires on the real path, P2) |
| `simorgh/verification/checks/didanything.py` | fails a change-producing task whose steps show no successful write tool; `WRITE_TOOLS` |
| `simorgh/verification/checks/docstring.py` | fails a candidate that drops a substantial module docstring (never fires on the real path, P2) |
| `simorgh/verification/checks/fullsuiteran.py` | a code change must have run `run_tests` on the whole suite and passed, or be excused by attribution |
| `simorgh/verification/checks/invariants.py` | substring invariants per path prefix (never fires on the real path, P2) |
| `simorgh/verification/checks/isolated_suite.py` | proposes `run_isolated_test_suite`, FULL rigor only (never fires on the real path, P2) |
| `simorgh/verification/checks/js_syntax.py` | parses written JS/HTML scripts via `run_js_sandboxed` |
| `simorgh/verification/checks/render.py` | opens written HTML via `render_page` and fails on page errors |
| `simorgh/verification/checks/sandbox_smoke.py` | runs a skill candidate via `run_python_sandboxed` (never fires on the real path, P2) |
| `simorgh/verification/checks/syntax.py` | `ast.parse` of written Python files or a candidate |
| `simorgh/verification/checks/trailing_narration.py` | fails a written file with model commentary after the code ends |
| `simorgh/verification/config.py` | `[verification]` dataclass and its nested-table `from_mapping` |
| `simorgh/verification/parsing.py` | `parse_verdict`: YES/NO/None from free text; a non-answer is `None`, never "no" |
| `simorgh/verification/planreview.py` | `review_plan`: ordering, step count, protected target, model-judged goal coverage |
| `simorgh/verification/rigor.py` | `select_rigor`: max(by kind, by reversibility), or the forced override |
| `simorgh/verification/service.py` | `VerificationService`: subscriptions, the pipeline, the three outbound calls |
| `simorgh/verification/trajectory.py` | `compute_trajectory`: steps, wasted, denied, recovered from `task:<id>`; `writes_in_task`: every attempt's write tools (not denied), read for a retry so `did_anything` judges the task rather than standing down (stage 4 item 8) |
| `simorgh/verification/verdict.py` | `combine`: mechanical, then required "no", then denials, then answered fraction |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `verify.requested` | `messages/verify.py::VerifyRequested` | simorgh/verification/service.py | runs one verification (consumer group `verification`); a redelivery re-emits the recorded verdict |
| `plan.proposed` | `messages/plan.py::PlanProposed` | simorgh/verification/service.py | reviews the plan and publishes `plan.reviewed` |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/verification/service.py | `stopping` makes new requests answer `insufficient_evidence`; `paused` holds every new verification until the resume (it never answers early: `insufficient_evidence` is accepted by Orchestration) |
| `action.result` | `messages/action.py::ActionResult` | simorgh/verification/service.py | resolves the future of a check's own proposed action by `action_id`; `error_kind` becomes `api.ActionResult.error_kind` (stage 2 item 8), and `render` / `js_syntax` skip on `unconfigured`, keeping their text markers only for a result with no kind |
| `cognition.think` reply | `messages/cognition.py::CognitionThink` | simorgh/verification/service.py | reply to its own `bus.request_or_error` (not a subscription) |
| `guardian.review` reply | `messages/guardian.py::GuardianReview` | simorgh/verification/service.py | reply to its own `bus.request_or_error` (not a subscription) |

The generated rows for `ui.notice` and a subscription to `verify.result` were wrong and are deleted.

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `verify.result` | `messages/verify.py::VerifyResult` | simorgh/verification/service.py | once per request (partition key `task:<id>`); Orchestration and Growth (estimate, monitors) consume it |
| `plan.reviewed` | `messages/plan.py::PlanReviewed` | simorgh/verification/service.py | after each `plan.proposed`; Planning consumes it |
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/verification/service.py | when a check needs a tool (`render_page`, `run_js_sandboxed`, `run_python_sandboxed`, `run_isolated_test_suite`), `proposed_by="verification"`, labelled `read_only` |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/verification/service.py | checklist generation, per-item answers, plan goal coverage (`purpose` review) |
| `guardian.review` | `messages/guardian.py::GuardianReview` | simorgh/verification/service.py | `denylist_immunity` and plan review of a `patch` step's subject |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `verify:{verification_id}` | simorgh/verification/service.py (append `verdict`, read for dedup) | simorgh/orchestration/api.py, simorgh/orchestration/session.py | 90d (`verify:` in `DEFAULT_RETENTION`) |
| `task:{task_id}` | simorgh/verification/trajectory.py (read only) | written by Planning/Orchestration | forever |

Deleted rows: `denied:`, `error:`, `no:cacheprovider`, `run_shell:git`, `run_shell:{program_name}` are string literals (evidence phrases, a pytest flag, a step-summary prefix), not streams; `verification:{action_id}` is a partition key on the proposal, not a stream. Subject blobs are read with `ledger.get_blob(subject_ref)`, and `_review` writes the reviewed code as a blob (`put_blob`).

## Config

`[verification]` in simorgh.toml; dataclass in `simorgh/verification/config.py`. `from_mapping` reads nested tables (`[verification.rigor] by_kind`, `[verification.checklist] max_items`, `[verification.review] require_real_provider`, ...) for most fields; four fields are flat top-level keys under their own names (`action_timeout_seconds`, `think_timeout_seconds`, `isolated_suite_timeout_seconds`, `max_denied_actions`, settable since 2026-09-19); the env var `SIMORGH_VERIFICATION_RIGOR` sets `forced_rigor`.

| Key | Default | Read in the package |
|---|---|---|
| `rigor_by_kind` | chat NONE, research LIGHT, skill/patch/self_patch FULL, plan STANDARD | yes (`rigor.py`); the wire kind is always `task`, which is not in the table, so it falls to STANDARD |
| `rigor_by_reversibility` | read_only LIGHT, reversible STANDARD, irreversible FULL | yes (`rigor.py`) |
| `checklist_max_items` | `6` | yes |
| `checklist_min_answered_fraction` | `0.67` | yes |
| `docstring_min_chars_to_protect` | `80` | yes |
| `docstring_shrink_threshold` | `0.3` | yes |
| `invariants` | `{"simorgh/execution/": ["verifier.verify("], "simorgh/guardian/": ["Pipeline("]}` | yes |
| `test_suite_require_count_not_below_baseline` | `True` | yes |
| `sandbox_smoke_kinds` | `('skill',)` | yes |
| `trajectory_wasted_step_ratio_warn` | `0.5` | NO (declared, never read) |
| `review_require_real_provider` | `True` | yes (`service.py::_think` sends it as `require_real_provider` on every `cognition.think`; with it on, Cognition answers an error rather than a floor reply, which every caller already treats as no answer) |
| `plan_review_max_steps` | `8` | yes |
| `action_timeout_seconds` | `5.0` | yes (flat key) |
| `think_timeout_seconds` | `200.0` | yes (flat key) |
| `isolated_suite_timeout_seconds` | `120.0` | yes (flat key) |
| `max_denied_actions` | `2` | yes (flat key) |
| `forced_rigor` | `None` | yes; set only by `SIMORGH_VERIFICATION_RIGOR` |

## Public Python surface

- `simorgh.verification.service.VerificationService` (`name = "verification"`, layer 3): `start(ctx)`, `stop()`, `health()`. `consumes = (verify.requested, plan.proposed, system.state.changed, action.result)` and `produces = (verify.result, plan.reviewed, action.proposed, guardian.review, cognition.think)` are exact (pinned by `tests/simorgh/test_manifests_match_the_code.py`). `health()` is `degraded` after 5 verifications in a row whose checklist the model never answered.
- `api.py` types (`Rigor`, `VerifyRequest`, `Check`, `CheckContext`, `CheckResult`, `Feedback`) are internal; no other package imports them. The wire shapes are `contracts/messages/verify.py` and `plan.py`.
- `checks.didanything.WRITE_TOOLS` is a hand-kept list of Execution's file-writing tool names; `tests/simorgh/verification/test_replace_in_file_is_a_write.py` fails when a registered write tool is missing from it.
- Module-level state: `ALL_CHECKS` is a list of shared check instances (stateless today); `checks/_files.py::REPO_ROOT` is fixed at import from `__file__`, used when the subject carries no `repo_root`. The service's `_pending_actions` and `_floor_streak` are per instance.

## Invariants

- The checkpoint critic (stage 7 item 6, 2026-09-19): `verify.checkpoint.request{goal, acceptance, trajectory}` is answered on the cheap tier with `on_track | drifting | blocked | insufficient_evidence`, plus what is unmet and the one thing to do next. A reply that cannot be read as that JSON is `insufficient_evidence`, never approval: reading prose as a verdict is how a checker becomes a stamp. The vote (2026-09-20): a verdict that would END the attempt -- `drifting` or `blocked`, `checkpoint.ACTIONABLE` -- is confirmed by two more cheap samples and decided by `checkpoint.majority`, which reports `votes` ("2/3") on the reply. `on_track` and `insufficient_evidence` both mean carry on, so confirming them buys nothing and would cost three calls at every note of every long task. No verdict survives without a strict majority, in either direction: three samples with three different answers is `insufficient_evidence`, because a plurality of one is the single sample the vote exists to stop trusting.

- One `verify.result` per `verification_id`: a redelivered `verify.requested` re-publishes the verdict stored on `verify:<id>` and runs nothing (`service.py:143-152`).
- A non-answer is never `fail`: an unanswered checklist item is `"unanswered"`, and too few answered items give `insufficient_evidence` (`verdict.py::combine`); a timeout from Cognition or Guardian becomes `floor`/`ok=False`, never an exception.
- Mechanical checks run in cost order `free < cheap < expensive` and stop at the first `failed`; `isolated_suite` runs only at FULL rigor.
- A required "no" whose evidence names a refuser or protected target (`_REFUSAL_EVIDENCE`) does not fail the task; a generic `refused:` from a tool does not count as such evidence.
- `full_suite_ran` excuses a red whole suite only for tests that were red at `base_ref`, are not owned by files the task wrote, or passed a quiet re-run (`_baseline.attribute`). When attribution cannot run at all it now records WHICH unknown stopped it -- no `base_ref`, no written paths, no parseable failure ids, or the suite could not be re-run at the base -- on the result's evidence and in its detail line (2026-09-20). Without that, the fallback reads "the whole suite was run and it FAILED", which in a repo whose suite is already red is an impossible bar and says nothing about whether attribution was skipped or attempted: the kill-and-resume drill burned 23 steps against it.
- Every tool a check needs goes out as `action.proposed` with `proposed_by="verification"` and waits at most `action_timeout_seconds` (or the check's own timeout); Verification never subscribes to `action.proposed` or `action.approved` (`contracts/topics.py` `SUBSCRIBE_ONLY_BY`: only guardian / execution) and never publishes `action.approved`, `action.denied` or `plan.proposed` (`PUBLISH_ONLY_BY`). No topics.py entry names `verification` directly.
- Verification imports only `simorgh.contracts` and the standard library (it reaches the Ledger through `ctx.ledger`) (`tests/simorgh/test_module_boundaries.py`).

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract verification`.

- `tests/simorgh/integration/test_verification_scenarios.py` -- the service over a real `BusClient`: pass, mechanical fail with retryable feedback, protected path non-retryable, narration gives `insufficient_evidence`.
- `tests/simorgh/verification/test_verdict.py` -- `combine`'s precedence and the `verify.result` payload shape.
- `tests/simorgh/verification/test_rigor.py` -- `select_rigor` and the forced override.
- `tests/simorgh/verification/test_parsing.py` -- a non-answer parses as `None`, never "no".
- `tests/simorgh/verification/test_did_anything.py` -- a change task with no successful write fails.
- `tests/simorgh/verification/test_both_copies_agree_on_workspace.py` -- the quiet re-run's copy and Execution's isolated copy keep `workspace/` and its tracked README (the base run's `git archive` has them); dropping the directory made two tests fail "because of" every change and blocked every patch task that ran the whole suite, 2026-09-20 to 09-22.
- `tests/simorgh/verification/test_acceptance_reaches_the_verdict.py` -- a plan node's acceptance criteria (verify subject `acceptance`) lead the checklist as required items; one answered no fails the verdict (stage 7 item 4).
- `tests/simorgh/verification/test_a_retry_is_judged_on_the_whole_task.py` -- a retry (`complete_log=False`) passes when an earlier attempt wrote and fails when none ever did.
- `tests/simorgh/verification/test_full_suite_ran.py` -- the whole-suite requirement on a code change.
- `tests/simorgh/verification/test_red_suite_attribution.py` -- the base-revision and quiet-rerun excuse rules.
- `tests/simorgh/verification/test_planreview.py` -- `plan.reviewed` verdicts: ordering, step count, protected target.
- `tests/simorgh/verification/test_config_reaches_the_code.py` -- `review.require_real_provider` reaches `cognition.think`; the four flat keys are settable.

## Known issues (2026-09-18 evaluation)

- P2 (high): five of eleven checks never run on the real path (`denylist_immunity`, `docstring`, `invariants`, `isolated_suite`, `sandbox_smoke`): `orchestration/session.py::_put_verify_subject` never sends `candidate`/`code`/`original`, and the wire kind is always `task`, so the rigor table is inert. Open.
- P3 (medium): `full_suite_ran` fails most rounds, mostly correctly; "the whole suite" is the wrong unit inside a task. Open; stage 4/7.
- P5 (medium): one invariant guarded the retired v1 tree. The `src/` invariant was removed with v1 on 2026-09-18 (commit `a4bf8d1`); the other half of P5 is outside this package.
- T9 (low): tool errors are free text; `checks/render.py:32, 50` sniffs `result.error` for "no `node` executable" and "timeout", and `verdict.py::_REFUSAL_EVIDENCE` matches refusal phrases. Open; stage 2 item 8.
- L8 (medium): claim-policing lives in `orchestration/session.py`; the plan moves it into a Verification trajectory check. Open; stage 4 item 8.
- The manifest declared `ui.notice` and omitted `action.result`; fixed 2026-09-18 (commit `8b7e4dd`).
- Not in the catalogue: `checks/_baseline.py` runs `git` and `pytest` with `subprocess.run` directly, outside `action.proposed` and Guardian, on a copy of the task's worktree. Since 2026-09-19 with a scrubbed environment and rlimits; since 2026-09-22 (stage 0 item 32) its three pytest runs go through `_confined`: on macOS `sandbox-exec` denies outbound network and every write outside the run's own temp directory (`TMPDIR` points there); elsewhere the run is as before. Closed 2026-09-22: `_paused` is read (see `system.state.changed`).

## Planned changes (roadmap)

- Stage 1 item 4 (`docs/plan/stage-1-telemetry-out-of-the-decision-log.md`): a `verify` span on the daily path.
- Stage 2 item 8 (`docs/plan/stage-2-native-tool-use.md`): `ToolResult.error_kind` replaces the error-text sniffing in `render.py` and `js_syntax.py`. Done 2026-09-19 (text markers kept as the fallback when no kind arrives). Still text: `error == "timeout"` in `render`, `js_syntax`, `isolated_suite`, `sandbox_smoke` (verification's own `act` timeout writes that string).
- Stage 4 item 8 (`docs/plan/stage-4-session-stream-context-compaction-evals.md`): one Stop hook plus a Verification trajectory check over the session stream replace `claimed_to_commit`, `claimed_tv_act` and the other claim guards in `session.py`.
- Stage 7 item 6 (`docs/plan/stage-7-long-horizon.md`): the checkpoint critic, `verify.checkpoint.request/reply`, scoring a trajectory against a node's acceptance criteria (`on_track | drifting | blocked`); two `drifting` verdicts re-plan the subtree. Stage 7 item 2 adds `agents/verify.md`.

## Working on this module

Lock it first (`python tools/modlock.py claim verification --by <you> --task "..."`), commit the lock, edit only `simorgh/verification/`, `tests/simorgh/verification/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py verification` before committing; commit subject `verification: <what changed>`.

- Telemetry (stage 1 item 4, 2026-09-19): each verification is a span `verification.verify`, parented to the `verify.requested` message.
