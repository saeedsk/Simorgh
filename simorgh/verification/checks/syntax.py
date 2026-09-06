"""`syntax`: `ast.parse` for a Python candidate. Free, runs first, applies
whenever the subject carries a `candidate`/`code` string.
"""

from __future__ import annotations

import ast

from ..api import CheckContext, CheckResult, VerifyRequest


def _candidate_source(req: VerifyRequest) -> str | None:
    return req.subject.get("candidate") or req.subject.get("code")


class SyntaxCheck:
    name = "syntax"
    cost = "free"

    def applies(self, req: VerifyRequest) -> bool:
        return _candidate_source(req) is not None

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        source = _candidate_source(req) or ""
        try:
            ast.parse(source)
        except SyntaxError as exc:
            return CheckResult(
                status="failed",
                detail=f"candidate is not valid Python: {exc}",
                evidence={"error": str(exc)},
            )
        return CheckResult(status="passed", detail="candidate parses as valid Python")
