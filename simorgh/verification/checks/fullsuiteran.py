"""`full_suite_ran`: a patch that changes code has to be checked against
the WHOLE suite, not whatever slice the model chose to run.

`IsolatedSuiteCheck` was supposed to be this gate. It never fires for a
real orchestration-driven patch task: `applies()` requires
`req.subject.get("candidate")`/`.get("code")`, and
`orchestration/session.py::_put_verify_subject` never populates either
-- only Learning's `PatchPipeline` does, and that pipeline has never
been reachable from a real task (its drafting tools were never built;
see `simorgh/learning/README.md`'s own open question). So the one check
built to answer "does the patched suite still pass" has been silently
absent from every real patch verification since it was written.

Two trials found the practical consequence on 2026-09-08, the same day
sandbox trials got fast enough to actually run to completion instead of
timing out first: `breaks-the-suite` and `already-done` both committed
a change after `run_tests` on a NARROWED target -- one file, or a
single test -- satisfied "run the tests" literally, without the change
having been checked against anything it might have broken elsewhere.

This is not a resurrection of `IsolatedSuiteCheck` or the Learning
pipeline -- that needs real Cognition-backed drafting tools that do not
exist yet, and forcing a cutover now would break every real patch task
(2026-09-08 investigation, wave 6). This is the narrow, free, mechanical
half of the same guarantee: before a patch/self_patch task's answer is
trusted, at least one `run_tests` step in its log must have targeted
the WHOLE suite (not a subdirectory or file) and passed.
"""

from __future__ import annotations

from ..api import CheckContext, CheckResult, Feedback, VerifyRequest
from .didanything import WRITE_TOOLS

# Kinds whose product is a change to real source. `skill` is excluded --
# a skill's own test is `apply_skill`'s sandbox smoke run, a different
# and already-real gate; a `research` task changes nothing to break.
_CHANGE_KINDS = frozenset({"patch", "self_patch"})
# What `orchestration/session.py::_propose_and_await` prefixes onto a
# `run_tests` step's own summary/detail.
_TARGET_MARKER = "[ran target="
# A target string that means "the whole suite," matched loosely: the
# default (empty, becomes "tests"), the literal "tests" directory, or a
# leading "tests/" is still the whole tree if nothing narrower follows
# -- but "tests/simorgh/guardian" or "tests/x/test_y.py" is a slice.
_WHOLE_SUITE_TARGETS = frozenset({"tests", "tests/", "'tests'", "'tests/'"})


def _steps(req: VerifyRequest) -> list[dict]:
    steps = req.subject.get("steps")
    return (
        [s for s in steps if isinstance(s, dict) and s.get("phase") == "act"]
        if isinstance(steps, list) else []
    )


def _ran_whole_suite_and_passed(steps: list[dict]) -> bool:
    for step in steps:
        if step.get("tool") != "run_tests" or not step.get("ok"):
            continue
        summary = str(step.get("summary") or "")
        if not summary.startswith(_TARGET_MARKER):
            # A run_tests step recorded before this fix, or truncated
            # past the marker -- cannot tell what it ran. Treated as NOT
            # the whole suite, the safer direction: this check only ever
            # costs a revision it should not have, never lets a real
            # regression through silently.
            continue
        target = summary[len(_TARGET_MARKER):].split("]", 1)[0].strip()
        if target in _WHOLE_SUITE_TARGETS:
            return True
    return False


class FullSuiteRanCheck:
    name = "full_suite_ran"
    cost = "free"

    def applies(self, req: VerifyRequest) -> bool:
        steps = _steps(req)
        # Same completeness gate as `DidAnythingCheck`: a retry's own
        # step log is not the whole session's history, and a task whose
        # earlier attempt already ran the whole suite must not be failed
        # here for an attempt that only commits.
        #
        # And the same "nothing to test" exemption `DidAnythingCheck`
        # already grants an honest no-op: if no write tool ran ANYWHERE
        # in the (complete) log, there is nothing this task could have
        # broken, and `DidAnythingCheck` is the one that owns judging
        # whether skipping the write was correct. Without this, a
        # legitimate "the file already has what was asked for; no
        # change needed" answer would be told to go run a suite it had
        # no reason to run.
        return (
            req.subject.get("kind") in _CHANGE_KINDS
            and bool(steps)
            and req.subject.get("complete_log", True)
            and any(s.get("tool") in WRITE_TOOLS for s in steps)
        )

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        steps = _steps(req)
        if _ran_whole_suite_and_passed(steps):
            return CheckResult(status="passed", detail="the whole suite ran and passed")
        ran_something = any(s.get("tool") == "run_tests" for s in steps)
        detail = (
            "run_tests was called on a narrower target than the whole suite, or never called at all -- "
            "this change was never checked against anything it might have broken elsewhere"
            if ran_something else
            "no run_tests call in this session at all -- this change was never checked against anything"
        )
        return CheckResult(
            status="failed", detail=detail,
            evidence={"steps_with_run_tests": sum(1 for s in steps if s.get("tool") == "run_tests")},
            feedback=Feedback(
                mechanical_errors=(detail,),
                revise_hint="call run_tests with no target (or target='tests') to run the whole suite, "
                            "confirm it passes, then commit",
                retryable=True,
            ),
        )
