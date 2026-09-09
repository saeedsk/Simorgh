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
"""

from __future__ import annotations

from ..api import CheckContext, CheckResult, Feedback, VerifyRequest

# The tools that leave something behind.
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


class DidAnythingCheck:
    name = "did_anything"
    cost = "free"

    def applies(self, req: VerifyRequest) -> bool:
        # Only where a change is the product, and only when we can see
        # the steps -- an empty step list means we were not told, not
        # that nothing happened.
        return req.subject.get("kind") in _CHANGE_KINDS and bool(_steps(req))

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
