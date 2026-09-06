"""`invariants`: a generalization of `check_main_py_invariants` from
`src/orchestrator/self_patch.py`. A narrow, cheap substring check, not a
real static-invariant prover -- it catches a patch that obviously
deletes or routes around the safety wiring for a protected-adjacent
subject; a sufficiently deliberate rewrite could still evade it. Flagged
here rather than presented as a stronger guarantee than it is (same
honesty the v1 docstring already commits to).
"""

from __future__ import annotations

from ..api import CheckContext, CheckResult, Feedback, VerifyRequest
from ..config import VerificationConfig


def invariant_violations(subject_path: str, new_content: str, table: dict[str, list[str]]) -> list[str]:
    missing: list[str] = []
    for prefix, required in table.items():
        if subject_path.startswith(prefix):
            missing.extend(s for s in required if s not in new_content)
    return missing


class InvariantsCheck:
    name = "invariants"
    cost = "free"

    def applies(self, req: VerifyRequest) -> bool:
        return bool(req.subject.get("path")) and (
            req.subject.get("candidate") or req.subject.get("code")
        ) is not None

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        path = req.subject.get("path", "")
        candidate = req.subject.get("candidate") or req.subject.get("code") or ""
        missing = invariant_violations(path, candidate, ctx.config.invariants)
        if not missing:
            return CheckResult(status="passed", detail="no invariant table entry matched, or all present")
        reason = (
            f"refusing: the new {path} no longer visibly wires {', '.join(missing)} -- "
            "this looks like it would weaken or remove safety wiring rather than "
            "improve something else"
        )
        return CheckResult(
            status="failed",
            detail=reason,
            evidence={"missing": missing, "path": path},
            feedback=Feedback(mechanical_errors=(reason,), revise_hint=reason, retryable=True),
        )
