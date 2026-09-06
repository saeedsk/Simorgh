"""`isolated_suite`: `run_isolated_test_suite` moved to Execution as a
tool; this check proposes it and consumes the result -- v1's rule
verbatim: the patched run must pass, and the patched count must be
`>= baseline` and `> 0`, so a patch can't dodge a failure by deleting or
skipping the very test that would have caught it. FULL rigor only --
this is the expensive check, ordered last.
"""

from __future__ import annotations

from ..api import CheckContext, CheckResult, Feedback, VerifyRequest


class IsolatedSuiteCheck:
    name = "isolated_suite"
    cost = "expensive"

    def applies(self, req: VerifyRequest) -> bool:
        return req.kind != "skill" and (req.subject.get("candidate") or req.subject.get("code")) is not None

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        path = req.subject.get("path", req.subject.get("subject", ""))
        code = req.subject.get("candidate") or req.subject.get("code") or ""
        result = await ctx.act(
            "isolated_test_suite", {"subject": path, "code": code},
            timeout=ctx.config.isolated_suite_timeout_seconds,
        )
        if not result.ok and result.error == "timeout":
            return CheckResult(status="insufficient", detail="execution did not answer the isolated-suite request in time")
        meta = result.metadata or {}
        baseline = meta.get("baseline", 0)
        patched = meta.get("patched", 0)
        passed = meta.get("passed", result.ok)
        require = ctx.config.test_suite_require_count_not_below_baseline
        ok = bool(passed) and patched > 0 and (patched >= baseline if require else True)
        evidence = {"baseline": baseline, "patched": patched, "passed": bool(passed), "tail": result.output[-2000:]}
        if ok:
            return CheckResult(status="passed", detail=f"isolated suite: {patched} tests (was {baseline})", evidence=evidence)
        reason = f"isolated test suite did not pass: baseline {baseline}, patched {patched}, passed={passed}"
        return CheckResult(
            status="failed",
            detail=reason,
            evidence=evidence,
            feedback=Feedback(mechanical_errors=(reason, result.output[-500:]), revise_hint=reason, retryable=True),
        )
