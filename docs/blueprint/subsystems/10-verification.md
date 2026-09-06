# 10 — Verification (`simorgh/verification/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). A spec may refine those documents; it
> may not contradict them. If you find a contradiction, fix the governing
> document and note it in `00-README.md`'s changelog.

**Layer:** 2 Agency
**Owner (build):** unassigned
**Status:** draft
**Depends on (contracts only):** `verify.requested`, `plan.proposed`, `action.result`, `cognition.think.reply`, `guardian.review.reply`, `system.state.changed`
**v1 code that migrates here:** `src/orchestrator/verification.py` (`verify_task_completion`, YES/NO line scan), from `src/orchestrator/self_patch.py`: `_docstring_regression_reason`, `check_main_py_invariants`, the use of `run_isolated_test_suite` (the runner itself moves to Execution), from `src/orchestrator/audit.py`: the sandboxed smoke run for new skills (as a check, not a gate)

## 1. Purpose and responsibilities

Verification answers one question the rest of the system cannot answer
about itself: *did this actually achieve what it was for?* It is
separate from Guardian (is it safe) and from Execution (did it run). It
runs mechanical checks whose answers are facts (does the file parse, did
the test suite regress, did a docstring vanish, is the candidate similar
to a known-bad one) and then an independent, separately-prompted
semantic review against a task-specific checklist and the task's
trajectory — returning `pass`, `fail` with structured feedback that the
generator can act on, or `insufficient_evidence` when it genuinely
cannot tell. It reviews plans before they execute. It never blocks a
non-answer as a rejection, and it never grades work with the same
context that produced it.

**Responsibilities (owns):**
- The `Check` framework and the mechanical checks: `denylist_immunity`
  (via `guardian.review`), `docstring_regression`, `invariants`,
  `sandbox_smoke` (new skills only), `isolated_test_suite` (via
  Execution's tool), `syntax`.
- Checklist generation and independent semantic evaluation
  (`pass | fail | insufficient_evidence`), with the v1 line-scan and
  "non-answer defers" rules.
- Trajectory evaluation from `task.step` and `action.*` events.
- Structured feedback for the evaluator-optimizer loop that
  Orchestration runs.
- Plan review (`plan.reviewed`) for coverage, ordering vs. dependencies,
  risk, scope, and size.
- Reversibility- and kind-weighted rigor: how much verification a given
  request gets.
- The `verify:<id>` audit stream and per-task-type verdict statistics
  (consumed by Reflection for calibration).

**Explicit non-responsibilities (belongs elsewhere):**
- Approving actions or issuing tokens — **Guardian** (Verification
  *requests* `guardian.review`; it does not decide safety).
- Running the test suite, the sandbox, or reading files — **Execution**
  (Verification proposes those as actions and consumes their results).
- Deciding what to do with a verdict (retry, block, mark done) —
  **Orchestration** and **Planning**.
- Learning from verdicts over time — **Learning**/**Reflection**
  (Verification emits; they aggregate).

**Principles this subsystem is the primary enforcer of** (`01` §4):
4.8 (verify intent, iterate with feedback), 4.5 (a non-answer is never a
failure), and the reversibility-weighted rigor half of 4.10.

## 2. Position in the architecture

Layer 2. Participates in flows 2 (task verification, evaluator-optimizer
support), 3 (plan review), 4 (self-patch gates: denylist/immunity,
docstring, invariants, isolated suite), 6 (research finding review), 8
(none directly; Reflection reads `verify:*` statistics). Imports only
`simorgh.contracts`, bus/ledger clients, stdlib. Verification reads the
Ledger directly for a task's `task.step`/`action:*` history (trajectory)
— reading the log is not a side effect.

## 3. Interfaces

### 3.1 Messages consumed

| Type | Pattern | Semantics | What Verification does with it |
|---|---|---|---|
| `verify.requested` | command (group `verification`) | work | build a `Plan of checks` by `kind`/rigor; run; emit `verify.result` |
| `plan.proposed` | event | fact | run plan review; emit `plan.reviewed` |
| `action.result` | event (on the verification's own trace) | rep-like | results of the checks it proposed (`isolated_test_suite`, `run_python_sandboxed`, `read_file`) |
| `guardian.review.reply` | reply | rep | static/immunity verdict for candidate code |
| `cognition.think.reply` | reply | rep | checklist generation, semantic review, plan review |
| `system.state.changed` | event | fact | `paused`: finish current; do not start new; `stopping`: abandon in-flight with `insufficient_evidence{reason: stopping}` |

### 3.2 Messages produced

| Type | Semantics | Payload summary | Consumers |
|---|---|---|---|
| `verify.result` | event | `{verification_id, verdict, checklist[], trajectory{}, feedback?, mechanical{}}` | orchestration, learning, planning, reflection, interface |
| `plan.reviewed` | event | `{plan_id, verdict: approve\|revise\|reject\|insufficient_evidence, checklist[], feedback?}` | planning, interface |
| `action.proposed` | command→guardian | `isolated_test_suite`, `run_python_sandboxed`, `read_file` requests (read-only / temp-copy tools; Guardian approves them in any mode) | guardian |
| `guardian.review` | request | `{subject, code, rationale}` | guardian |
| `cognition.think` | request | `purpose: checklist\|review\|plan_review` | cognition |
| `ui.notice` | event | verdict summaries for autonomous work | interface |

### 3.3 Request/reply APIs served

None. `verify.requested` is a command whose answer is the `verify.result`
event on the same `partition_key` (`task:<id>`), so Orchestration awaits
it by correlation without a synchronous dependency — a verification that
runs the full test suite can take minutes.

### 3.4 Python protocol (`api.py`)

```python
class Check(Protocol):
    name: str
    cost: Literal["free", "cheap", "expensive"]      # for rigor selection and ordering
    def applies(self, req: VerifyRequest) -> bool
    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult
    # CheckResult(status: passed|failed|skipped|insufficient, detail: str, evidence: dict, feedback: Feedback | None)

@dataclass(frozen=True)
class CheckContext:
    ledger: LedgerClient; act: Callable[[str, dict], Awaitable[ActionResult]]   # propose → await action.result
    think: Callable[..., Awaitable[ThinkReply]]; review: Callable[[str, str], Awaitable[ReviewReply]]
    clock: Clock; config: VerificationConfig; blobs: BlobStore

@dataclass(frozen=True)
class Feedback:                                    # the evaluator-optimizer payload
    failed_items: tuple[FailedItem, ...]            # {question, evidence, suggestion}
    mechanical_errors: tuple[str, ...]              # e.g. "docstring shrank 1,204 → 40 chars"
    revise_hint: str                                # one paragraph the generator can act on
    retryable: bool                                 # False for e.g. protected subject

class Rigor(Enum): NONE, LIGHT, STANDARD, FULL
def select_rigor(req: VerifyRequest) -> Rigor       # §5.2

def parse_verdict(text: str) -> Literal["yes","no",None]      # port: scan every line for a standalone YES/NO
def docstring_regression_reason(original: str, new: str) -> str | None   # port
def invariant_violations(subject: str, new: str, table: dict[str, list[str]]) -> list[str]  # generalized main.py check
```

### 3.5 Configuration (`[verification]`)

| Key | Type | Default | Controls |
|---|---|---|---|
| `rigor.by_kind` | table | `{chat: NONE, research: LIGHT, skill: FULL, patch: FULL, self_patch: FULL, project_child_readonly: LIGHT}` | default rigor per kind |
| `rigor.by_reversibility` | table | `{read_only: LIGHT, reversible: STANDARD, irreversible: FULL}` | max(rigor by kind, by reversibility) |
| `checklist.max_items` | int | 6 | binary questions per review |
| `checklist.min_answered_fraction` | float | 0.67 | below → `insufficient_evidence` |
| `docstring.min_chars_to_protect` | int | 80 | v1 `_MIN_DOCSTRING_CHARS_TO_PROTECT` |
| `docstring.shrink_threshold` | float | 0.3 | v1 `_DOCSTRING_SHRINK_THRESHOLD` |
| `invariants` | table `path_prefix → [required substrings]` | `{"src/main.py": ["AuditGate(", "audit_gate.review(", "apply_proposal("], "simorgh/execution/": ["verifier.verify("], "simorgh/guardian/": ["Pipeline("]}` | generalized `check_main_py_invariants` |
| `test_suite.require_count_not_below_baseline` | bool | true | v1 rule: patched count ≥ baseline and > 0 |
| `sandbox_smoke.kinds` | list | `["skill"]` | never self-patches (milestone 84) |
| `trajectory.wasted_step_ratio_warn` | float | 0.5 | flag but do not fail |
| `review.require_real_provider` | bool | true | floor → `insufficient_evidence`, never fail |
| `plan_review.max_steps` | int | 8 | more → `revise` |
| `SIMORGH_VERIFICATION_RIGOR` | env | — | force a rigor level (e.g. `FULL` in CI) |

## 4. Data model and Ledger streams

- `verify:<verification_id>` — `requested {kind, rigor, subject_ref}`,
  one `check {name, status, detail, evidence_ref}` per check, `reviewed
  {checklist, raw_ref}`, `trajectory {steps, wasted, recovered_errors}`,
  `verdict {verdict, feedback_ref}`.
- `verification:stats` — per `task_type`: counts of pass/fail/insufficient
  and mechanical-vs-semantic failure split, appended as `stat {…}` after
  each verdict; projection `VerdictStats` (Reflection's calibration input).
- Blob refs for raw model reviews, test logs (from Execution), diffs.

Nothing else is stateful; an in-flight verification is a coroutine that
can be abandoned and re-run from `verify.requested` redelivery.

## 5. Internal design

```
verification/
  service.py        subscribe; dispatch by kind; correlate action.result/replies; health
  rigor.py          select_rigor; check ordering by cost
  checks/
    syntax.py  docstring.py  invariants.py  denylist_immunity.py
    sandbox_smoke.py  isolated_suite.py
  checklist.py      generate checklist (cognition) → evaluate each item → aggregate
  trajectory.py     read task:<id> + action:* → metrics
  verdict.py        combine mechanical + semantic + trajectory → verdict + Feedback
  planreview.py     plan.proposed → checklist over coverage/order/risk/scope → plan.reviewed
  parsing.py        parse_verdict (line scan), checklist answer parsing
```

### 5.1 One verification, end to end

```
verify.requested{kind, subject_ref, task_id}
  ─▶ rigor = select_rigor(req)                       (NONE → verify.result{pass, mechanical:{skipped:true}})
  ─▶ mechanical checks, cheapest first, stop at first failed unless config.continue_on_fail:
        syntax → denylist_immunity (guardian.review) → docstring → invariants → sandbox_smoke (skills) → isolated_suite (FULL only; via act("isolated_test_suite", …))
  ─▶ any failed → verdict fail; Feedback.mechanical_errors from details; retryable per check (protected/denylist ⇒ retryable=false)
  ─▶ semantic review (LIGHT+): checklist = think(purpose=checklist, task, result) → ≤ max_items binary questions
        each item → think(purpose=review, item, evidence) → parse_verdict → yes/no/None
  ─▶ trajectory (STANDARD+): metrics from ledger; never fails alone (warnings only)
  ─▶ verdict.combine:
        any required item "no" → fail (Feedback.failed_items with evidence + suggestion)
        answered fraction < min_answered_fraction, or review on floor → insufficient_evidence
        else → pass
  ─▶ verify.result ; verify:<id> verdict ; verification:stats
```

The semantic review uses the *result and task description*, plus the
diff/finding blob — never the generator's conversation. A `None` from
`parse_verdict` is "the reviewer didn't answer," not "no"
(milestone 92): it counts as unanswered, and enough unanswered items
yield `insufficient_evidence`, which Orchestration treats as "mechanical
gates decide" (`harness-04`).

### 5.2 Rigor selection

`rigor = max(by_kind[kind], by_reversibility[max reversibility among the
task's actions])`, clamped by env override. `NONE` for chat turns;
`LIGHT` = syntax + checklist (no trajectory, no suite) for research
findings and read-only children; `STANDARD` adds trajectory; `FULL` adds
`isolated_test_suite` (and `sandbox_smoke` for skills). This is
`harness-05` §4's reversibility-weighted verification effort.

### 5.3 Checks (ported behavior)

- `syntax`: `ast.parse` for Python subjects; skipped otherwise.
- `denylist_immunity`: `guardian.review{subject, code}`; a `deny` fails
  with `retryable=false` if `layer ∈ {protected}`, else `true`.
- `docstring`: port of `_docstring_regression_reason` (substantial
  original docstring missing or < 30% of original length → failed,
  feedback "preserve the existing documentation unless the change
  requires updating it").
- `invariants`: for each `path_prefix` matching the subject, every
  required substring must be present in the new content (v1's
  `check_main_py_invariants`, generalized; the v2 entries protect the
  token check and the pipeline from being edited out even if the files
  were somehow not protected).
- `sandbox_smoke`: `act("run_python_sandboxed", {code})` for `kind=skill`
  only — the isolated sandbox cannot import project internals, so it is
  structurally unwinnable for a self-patch (milestone 84).
- `isolated_suite`: `act("isolated_test_suite", {subject, code})` →
  `{baseline, patched, passed, tail}`; failed if `!passed` or
  `patched < baseline` or `patched == 0`; the tail (bounded) becomes
  `mechanical_errors` so the reviser sees the actual failure.

### 5.4 Trajectory

From `task:<id>` (`task.step` events) and the task's `action:*` streams:
`steps`, `tool_calls`, `denied_actions`, `wasted` (reads of the same
path more than twice, denied proposals, steps with no resulting action),
`recovered_errors` (a failed `action.result` followed by a successful
retry). Produces warnings in `verify.result.trajectory`; only
`denied_actions ≥ config.max_denied` contributes to `fail` (a task that
kept proposing disallowed actions did not understand its constraints).
Reflection uses this to tell "worked well" from "worked by luck"
(`harness-04`, "Evaluate the trajectory").

### 5.5 Plan review

For `plan.proposed`: checklist over (a) every goal facet is covered by
some step, (b) each step has a `why` tied to the goal, (c) `depends_on`
is consistent with the steps' stated order and a research step precedes
patches that assume it, (d) no step targets a protected subject
(`guardian.review` per patch subject with empty code), (e) step count ≤
`plan_review.max_steps`, (f) risk label plausible for the tools implied.
Mechanical items (c, d, e) are computed; (a, b, f) are model-reviewed.
Verdict: any mechanical failure or "no" on (a) → `revise` with feedback;
protected target → `reject`; unanswered → `insufficient_evidence`
(Planning treats as one `revise`, then human); else `approve`.

### 5.6 Concurrency, start, stop, health

Each `verify.requested` is an asyncio task; the isolated-suite check
serializes naturally through Execution's `per_tool_concurrency`. In-flight
verifications are abandoned on `system.stop` with
`insufficient_evidence{reason: stopping}` so no Worker waits forever.
`health()` is `degraded` when the semantic reviewer has returned floor
for the last N reviews (verification is silently falling back to
mechanical-only).

## 6. Key behaviors — worked scenarios

**S1 — Self-patch passes (Flow 4).** `verify.requested{kind:self_patch,
subject_ref:blob(candidate for simorgh/memory/retrieval.py)}` → rigor FULL
→ syntax ✓ → `guardian.review` pass → docstring ✓ (1,180 → 1,240 chars)
→ invariants n/a → `action.proposed{isolated_test_suite}` → approved →
`action.result{baseline:889, patched:891, passed:true}` ✓ → checklist
(4 items: "does it implement the described retrieval change", "does it
keep existing lookup behavior", "are new paths tested", "did it avoid
unrelated changes") → 4× YES → trajectory: 7 steps, 1 wasted →
`verify.result{pass}`.

**S2 — Docstring regression, revised in-attempt (evaluator-optimizer).**
Same request; docstring check finds the module docstring shrank from
1,204 to 40 chars → `verify.result{fail, feedback:{mechanical_errors:
["the original file's module docstring (1,204 chars) is missing or
drastically shortened (40 chars) …"], retryable:true, revise_hint:"…"}}`.
Orchestration re-drafts with the feedback and issues a second
`verify.requested` (bounded); the suite never ran for the bad draft —
cheapest-first saved a 40-second run.

**S3 — Reviewer narrates, doesn't answer (the milestone 92 case).**
Task result verified at STANDARD; all mechanical checks pass; the
checklist reviewer replies "I'll check the actual file that was modified
to verify the claim.\n\n{}" to every item → `parse_verdict` → `None` ×4
→ answered fraction 0 < 0.67 → `verify.result{insufficient_evidence,
mechanical:{…all passed}}`. Orchestration marks the task done-with-flag;
nothing is blocked because the reviewer didn't review.

**S4 — Plan needs revision (Flow 3).** `plan.proposed{steps:[A(patch),
B(research), C(patch depends_on:[B])]}` → mechanical (c): A precedes the
research step B but its description assumes B's conclusion → `plan.reviewed{
revise, feedback:"step 1 assumes the finding of step 2; make step 1
depend on step 2 or move it after"}`.

**S5 — Protected target (failure, non-retryable).** Skill candidate
whose `subject` is `src/orchestrator/audit.py` → `guardian.review{deny,
layer:protected}` → `verify.result{fail, feedback:{retryable:false}}` →
Orchestration blocks the task without retrying.

## 7. Design considerations and tradeoffs

- **Separate reviewer context.** The checklist review never sees the
  generator's conversation, only the task, the result, and evidence —
  a model grading its own immediately-prior output rationalizes
  (`harness-04`, "Verification as a separate, independently-prompted pass").
  Cost: one to `max_items`+1 extra calls per verified task; rigor
  selection keeps that off cheap, reversible work (`harness-05` §4).
- **Checklist over holistic judgment.** Binary, task-specific items make
  an easy-to-miss gap visible (`harness-04`, "Checklist-based verification");
  the third outcome (`insufficient_evidence`) exists so a forced binary
  never adds confident noise.
- **Mechanical first, cheapest first.** A failing docstring check costs
  nothing; the isolated suite costs ~40 s and real CPU; ordering by cost
  makes the evaluator-optimizer loop affordable (`harness-06` gap #5).
- **Feedback is structured, not prose.** `Feedback.failed_items` with
  evidence and a suggestion is what lets Orchestration revise *in the
  same attempt* instead of parking the task for a cold retry.
- **Trajectory informs, rarely fails.** A lucky success is still a
  success; the signal goes to Reflection/Learning to decide what to
  reinforce (`harness-04`, "Evaluate the trajectory").
- **Sandbox only for skills.** Kept exactly per milestone 84 — an
  unwinnable check is friction, not safety.

Alternatives rejected: a single "is this good?" call (misses gaps, no
evidence); running the test suite inside Verification's process (would
create a second executor outside Guardian's path); failing on any
unanswered item (re-creates the milestone 92 false block).

## 8. Safety, degradation, and failure modes

- **Provider down / budget exhausted:** mechanical checks still run;
  semantic review returns `insufficient_evidence` (never `fail`), with
  `mechanical` populated so callers can decide.
- **Malformed request:** schema failure → `verify.result{insufficient_evidence,
  feedback:{retryable:false, revise_hint:"malformed verification request"}}`.
- **Check crash:** that check reports `insufficient`, others continue;
  `system.health{degraded}` names the check.
- **Execution never answers (`isolated_test_suite` interrupted):** the
  awaited `action.result` arrives with `error:interrupted` on restart →
  the check is `insufficient` → verdict `insufficient_evidence{reason}`;
  Orchestration may re-request.
- **Restart mid-verification:** redelivered `verify.requested` re-runs
  from scratch; `verify:<id>` shows both attempts.
- **Duplicate request:** if a `verdict` already exists on `verify:<id>`,
  re-emit it.
- **Ledger unavailable:** trajectory is `skipped`; mechanical and
  semantic proceed; the verdict is emitted with `mechanical.ledger:false`
  so Reflection knows the trajectory was unavailable.
- **Corrigibility:** `system.pause` → no new verifications; `system.stop`
  → in-flight abandoned as `insufficient_evidence{stopping}`.
- **Floor:** syntax, docstring, invariants, and (via Execution) the test
  suite are fully deterministic — the floor is "mechanical gates only,
  honestly labeled."

## 9. Testing strategy

- Contract tests: `verify.result`, `plan.reviewed`, produced
  `action.proposed`/`guardian.review`/`cognition.think`; consumed types
  valid/invalid.
- Unit: `parse_verdict` (ported: YES first line, yes with punctuation,
  narrated non-answer → None, verdict after narration honored);
  `docstring_regression_reason` (ported 7 cases); `invariant_violations`
  (ported main.py cases + a v2 prefix); `select_rigor` matrix; checklist
  aggregation (all yes; one required no; unanswered fraction);
  `Feedback` construction; trajectory metrics from a scripted stream;
  plan review mechanical items (order vs deps, protected target, too
  many steps); duplicate request re-emits verdict.
- Integration: `test_flow_4_self_patch_gates.py` (S1, S2 with a fake
  Execution that returns suite counts), `test_verification_non_answer_defers.py`
  (S3), `test_flow_3_plan_review.py` (S4), `test_verification_protected_not_retryable.py` (S5).
- Invariants: `verdict == fail` ⇒ non-empty `feedback`; `insufficient_evidence`
  never produced when all items answered and all mechanical passed;
  `sandbox_smoke` never runs for `kind ∈ {patch, self_patch}`.
- Mocks: `FakeCognition` (scripted per `purpose`), `FakeGuardianReview`,
  `FakeExecution` for suite/sandbox results, in-memory Ledger with a
  scripted `task:<id>` stream.

## 10. Build steps (an agent picks this up here)

Size: **M**. Parallelizable after step 2: each check is a file.

1. Skeleton; `Service` consuming `verify.requested`/`plan.proposed`;
   contracts + boundary tests. *Accept:* boots; NONE-rigor request →
   immediate `pass`.
2. `parsing.py` (port `parse_verdict`), `rigor.py`, `verdict.py` +
   `Feedback`. *Accept:* ported line-scan tests; rigor matrix.
3. Checks: `syntax`, `docstring` (port), `invariants` (port +
   generalize). *Accept:* ported tests; S2 unit.
4. `denylist_immunity` via `guardian.review`; `isolated_suite` and
   `sandbox_smoke` via `act()`. *Accept:* S1/S5 with fakes; skills-only invariant.
5. `checklist.py` (generation + per-item review + aggregation).
   *Accept:* S3.
6. `trajectory.py`. *Accept:* scripted-stream metrics; denied-actions rule.
7. `planreview.py`. *Accept:* S4.
8. `verification:stats` + health; pause/stop behavior. *Accept:* stop
   abandons in-flight with `insufficient_evidence`.
9. v1 adapter: `src/orchestrator/verification.py` re-exports;
   `self_patch._docstring_regression_reason`/`check_main_py_invariants`
   re-export from `simorgh.verification.checks`. Both suites green. Docs
   + EVOLUTION milestone.

## 11. Migration notes

- `verify_task_completion(cognition, task, result)` → `checklist.py`'s
  single-item degenerate case is kept as a compatibility path
  (`kind=task`, `checklist.max_items=1` yields the v1 shape); the
  YES/NO scan and "no verdict → pass/defer" behavior are preserved
  verbatim, except that v2 reports `insufficient_evidence` explicitly
  instead of `passed=True` with an explanation string — Orchestration
  maps it to the same downstream behavior (mechanical gates decide).
- `_docstring_regression_reason`, `_MIN_DOCSTRING_CHARS_TO_PROTECT`,
  `_DOCSTRING_SHRINK_THRESHOLD` → `checks/docstring.py` + config.
- `check_main_py_invariants` → `checks/invariants.py` with the table in
  config; v1's `_MAIN_PY_REQUIRED_SUBSTRINGS` becomes the `src/main.py` entry.
- `run_isolated_test_suite` moves to Execution; Verification's
  `isolated_suite` check consumes its `action.result`.
- `AuditGate`'s sandboxed run → `checks/sandbox_smoke.py`, skills only.
- v1 tests: `tests/test_verification.py` (all), `TestDocstringRegressionReason`,
  `TestCheckMainPyInvariants`, and the sandbox-scoping tests from
  `tests/test_audit.py` move under `tests/simorgh/verification/`.

## 12. Open questions

1. **Does Verification await `action.result` by correlation on the
   verification's own trace, or on the task's partition?** *Default:*
   Verification proposes with `partition_key = verification:<id>` and
   `correlation_id = verification_id`, so Execution's result routes back
   unambiguously even when the task's Worker is also acting.
2. **Required vs. optional checklist items.** *Default:* the generator
   marks each item `required: bool`; a "no" on an optional item is
   feedback, not failure.
3. **`guardian.*` domain** — needed for `guardian.review`; see
   `09-guardian.md` Q1.
4. **Chat-turn verification.** *Default:* NONE; Persona/Reflection handle
   conversational quality through outcome records, not this gate.
