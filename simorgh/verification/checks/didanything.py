"""`did_anything`: a patch task that wrote nothing did not patch anything.

Observed 2026-09-08, in a real project run. Child task `6d7b8ed1cf6c`
was asked to add an `__all__` list to `simorgh/interface/activity.py`.
All ten of its steps were `read_file` and `search_code`; no write tool
ever ran. It then answered "The patch is applied with __all__ placed
right after the imports ... Next step: run the tests", and verification
PASSED it. `git status` was clean and the file was untouched. The
project's rollup counted it as one of the three steps done.

The semantic checklist cannot catch this, because it is judging the
answer's prose and the prose says the work was done. That is what a
mechanical check is for: it looks at what happened, costs nothing, and
runs before anyone is asked to form an opinion.

Deliberately narrow. It fires only for a task whose whole purpose is to
change a file, and only when NO write tool ran at all -- not when a
write ran and failed, which is a different and already-visible problem.
A session that correctly refused to write (a protected path, a task
that turned out to need no change) says so in its answer and is
failed here; that is the known cost, and `verdict.combine` already
treats a refusal as an answer rather than a defect, so the shape of the
remedy exists.

Also narrow the other way: `req.subject.get("steps")` is only ever the
CURRENT attempt's steps. `session.py` already knew this about a sibling
check -- `unsupported_claims` (`orchestration/claims.py`) takes a
`complete_log` flag and skips itself entirely when the step log is a
retry's own partial view, because a claim unsupported by *this*
attempt's steps may have been made true by a *previous* one. This check
had the identical blind spot with a worse failure mode: attempt 1 can
apply a patch and run out of steps before committing; attempt 2 inherits
the uncommitted edit, and if it just runs the tests and reports (no
`apply_source_patch`, no explicit "already applied" in the answer, and
-- unlike the trial that surfaced this -- no `git_commit` call either,
say because the edit was committed by a still-later attempt or by a
human), this check would fail a legitimate continuation for a write
that genuinely happened, just not in the steps it can see. `session.py`
now sends the same `complete_log` signal it computes for
`unsupported_claims` (`session.attempt <= 1 and not session.carried`)
on the verify subject, and `applies()` returns False when it is False,
handing the question to the semantic checklist instead of failing on
mechanical grounds it cannot actually support (2026-09-08, observer).
"""

from __future__ import annotations

from ..api import CheckContext, CheckResult, Feedback, VerifyRequest

# The tools that leave something behind.
#
# `run_shell` is unconditionally in here, and that is broader than it
# should be in principle: a session whose only `run_shell` calls were
# `git status` and `grep` did not write anything, and this check would
# still pass it. Left as a known limitation rather than "fixed" with a
# command-line heuristic (`sed -i`, `>`, `rm`, ...), because the data
# this check can see does not support one reliably: `session.py` never
# threads the actual command text into a step's summary (it holds the
# tool's *output*, e.g. stdout, not its input), and the one piece of
# the command that does survive to here -- `run_shell`'s side effect is
# `f"run_shell:{program_name}"`, e.g. "run_shell:git" -- is just the
# program, not the arguments. "git" alone cannot distinguish `git
# status` from `git commit`. Building a real heuristic means plumbing
# the full command line through `execution/service.py` and
# `session.py` into the step record, which is more surface than this
# fix warrants; a false "no write ran" from an over-eager pattern would
# fail a legitimate session, which is the more expensive mistake.
WRITE_TOOLS = frozenset({"apply_source_patch", "apply_skill", "git_commit", "git_revert", "run_shell"})
# Task kinds whose entire product is a change to a file.
_CHANGE_KINDS = frozenset({"patch", "skill", "self_patch"})
# Phrases that mean "I deliberately did not write anything", so the
# answer is honest about it and the checklist can judge it on merit.
_DECLINED = (
    "no change", "no changes", "already", "not needed", "no edit",
    "denied", "protected", "refused", "declined", "cannot",
)


def _steps(req: VerifyRequest) -> list[dict]:
    """Only steps that represent a real action attempt.

    A "verify" phase entry -- the bookkeeping record `session.py` writes
    for a rejected verdict, before a revision -- has no tool and is not
    an attempt at anything; it is a note about what verification said.
    Counting it as "we were told about a step" was wrong the same way
    counting NO steps as "nothing happened" would be: a scripted
    integration test whose session never calls a real tool at all
    picked up exactly one such bookkeeping entry between its first and
    second verification, and this check failed BOTH verdicts (the
    second should have passed), which exhausted `max_revisions` and
    blocked a task the test expected to complete -- a TimeoutError two
    layers away from the actual cause (2026-09-08).
    """
    steps = req.subject.get("steps")
    return (
        [s for s in steps if isinstance(s, dict) and s.get("phase") == "act"]
        if isinstance(steps, list) else []
    )


# KNOWN GAP, deliberately not closed here (wave-21 observer W21-08,
# 2026-09-09). A session whose FIRST reply is a bare final with no tool
# call records one step, and `session.py` tags a step_no==1 final
# `"gather"`, not `"act"` -- so a `patch` task that did literally
# nothing has zero act steps, `applies` below says no, and it completes
# unverified. Confirmed live: a weather-chart task "completed" in 30s
# having written no file.
#
# The obvious fix -- also judge a session whose only steps are `gather`
# -- was tried and reverted the same day, because it reintroduces the
# 2026-09-08 bug `TestABookkeepingStepIsNotAnAction` below records: a
# legitimate scripted session in the evaluator-optimizer revision loop
# produces exactly the same step shape (tool_calls: [], one gather
# step), so this check failed BOTH its verdicts, exhausted
# max_revisions, and hung a task the test expected to complete. The two
# cases are indistinguishable from the step log alone; trading a missed
# no-op for a hung revision loop is the worse bug.
#
# A real fix lives elsewhere and is a design decision, not a patch
# here: either `session.py` stops tagging a lone final `"gather"` (it
# is not gathering -- it is finishing), or the phase gains a value that
# says "answered without acting". `unsupported_claims` already catches
# the dangerous half of this whenever the answer claims work it did not
# do, which is how the 2026-09-09 acceptance trial was correctly
# blocked.


class DidAnythingCheck:
    name = "did_anything"
    cost = "free"

    def applies(self, req: VerifyRequest) -> bool:
        # Only where a change is the product, and only when we can see
        # the steps -- an empty step list means we were not told, not
        # that nothing happened.
        #
        # And only when the log we can see is the WHOLE session, not
        # just this attempt's. `session.py` sends `complete_log=False`
        # (the same flag it already passes to `unsupported_claims`,
        # `session.attempt <= 1 and not session.carried`) on a retry
        # that carried an edit forward from an earlier attempt: attempt
        # 1 can apply the patch and run out of steps, and attempt 2's
        # own step list -- the only one this check ever sees -- may
        # legitimately have no write tool in it at all (e.g. it just
        # re-runs the tests and reports, with the patch already
        # committed by attempt 1). Judging that attempt in isolation
        # would fail a legitimate continuation. Default to True (a
        # complete log) so producers that do not send the field --
        # tests, other callers -- keep today's behaviour.
        return (
            req.subject.get("kind") in _CHANGE_KINDS
            and bool(_steps(req))
            and req.subject.get("complete_log", True)
        )

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        used = {str(s.get("tool") or "") for s in _steps(req)}
        if used & WRITE_TOOLS:
            return CheckResult(status="passed", detail="the session used a write tool")

        answer = str(req.subject.get("result") or "").lower()
        if any(phrase in answer for phrase in _DECLINED):
            # It says it chose not to write. That may be exactly right,
            # and it is the checklist's job to say whether it was.
            return CheckResult(
                status="passed",
                detail="no write tool ran, and the answer says the change was not made",
            )

        detail = ("this task's product is a change to a file, and no write tool ran in the whole "
                  "session -- the answer describes work that did not happen")
        return CheckResult(
            status="failed", detail=detail,
            evidence={"tools_used": sorted(t for t in used if t)},
            feedback=Feedback(
                mechanical_errors=(detail,),
                revise_hint="apply the change with apply_source_patch, then commit it",
                retryable=True,
            ),
        )
