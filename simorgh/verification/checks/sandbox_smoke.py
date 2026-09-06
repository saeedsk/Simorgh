"""`sandbox_smoke`: `run_python_sandboxed` for `kind=skill` only -- kept
exactly per milestone 84 in docs/EVOLUTION.md. `SubprocessSandbox` runs
with an empty environment in a bare temp dir, which is correct isolation
for a brand-new, standalone skill file (never supposed to import project
internals) but structurally impossible to pass for a self-patch to an
existing file, which normally and legitimately imports sibling modules
(`ModuleNotFoundError: No module named 'src'`, every time, regardless of
code quality). Scoping this check to skills only is not a weaker gate --
`isolated_suite` verifies self-patches instead, against a full repo copy
with the package genuinely intact, a strictly *stronger* real-execution
check for that case.
"""

from __future__ import annotations

from ..api import CheckContext, CheckResult, Feedback, VerifyRequest


class SandboxSmokeCheck:
    name = "sandbox_smoke"
    cost = "cheap"

    def applies(self, req: VerifyRequest) -> bool:
        # `Check.applies` has no config access; this mirrors the default
        # `sandbox_smoke_kinds` -- `run()` re-checks against the real
        # config and reports `skipped` if a caller overrode it away from
        # the default, so a non-default config is still authoritative.
        return req.kind == "skill"

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        if req.kind not in ctx.config.sandbox_smoke_kinds:
            return CheckResult(status="skipped", detail=f"sandbox_smoke does not run for kind={req.kind}")
        code = req.subject.get("candidate") or req.subject.get("code") or ""
        result = await ctx.act("run_python_sandboxed", {"code": code})
        if result.ok:
            return CheckResult(status="passed", detail="sandboxed smoke run succeeded", evidence={"output": result.output[:500]})
        if result.error == "timeout":
            return CheckResult(status="insufficient", detail="execution did not answer the sandbox request in time")
        reason = result.error or "sandboxed smoke run failed"
        return CheckResult(
            status="failed",
            detail=reason,
            evidence={"output": result.output[:500]},
            feedback=Feedback(mechanical_errors=(reason,), revise_hint=reason, retryable=True),
        )
