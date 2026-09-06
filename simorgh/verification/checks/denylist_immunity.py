"""`denylist_immunity`: asks Guardian's own static-denylist + adaptive-
immunity check (`guardian.review`) rather than re-implementing it --
Verification never decides safety, only asks the subsystem whose job
that is (docs/blueprint/01 section 4.3). A `deny` whose layer is
`protected` is non-retryable (the target can never pass, no matter how
good the draft); any other deny is retryable feedback. If Guardian never
answers (not built yet, or genuinely down), this defers to
`insufficient` rather than blocking on a question nothing can answer --
the same guaranteed-floor posture as every other check here.
"""

from __future__ import annotations

from ..api import CheckContext, CheckResult, Feedback, VerifyRequest


class DenylistImmunityCheck:
    name = "denylist_immunity"
    cost = "cheap"

    def applies(self, req: VerifyRequest) -> bool:
        return (req.subject.get("candidate") or req.subject.get("code")) is not None

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        code = req.subject.get("candidate") or req.subject.get("code") or ""
        subject_path = req.subject.get("path", req.subject.get("subject", ""))
        reply = await ctx.review(subject_path, code, req.kind)
        if not reply.ok:
            return CheckResult(status="insufficient", detail="guardian did not answer the review request")
        if reply.approved:
            return CheckResult(status="passed", detail="denylist + adaptive immunity: no match", evidence={"layers_run": list(reply.layers_run)})
        retryable = "protected" not in reply.layers_run
        reason = "; ".join(reply.reasons) or "guardian denied the candidate"
        return CheckResult(
            status="failed",
            detail=reason,
            evidence={"layers_run": list(reply.layers_run), "reasons": list(reply.reasons)},
            feedback=Feedback(mechanical_errors=(reason,), revise_hint=reason, retryable=retryable),
        )
