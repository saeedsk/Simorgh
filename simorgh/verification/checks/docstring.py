"""`docstring`: a verbatim port of `_docstring_regression_reason` from
`src/orchestrator/self_patch.py`. Live-caught watching real self-patches
succeed for the first time: five real, autonomous self-patches to three
different files all silently deleted the target's entire module
docstring while otherwise passing every other check. Only flags a REAL
loss -- a substantial original docstring now missing or reduced to a
small fraction of its original length; a file with no/trivial docstring,
or a genuine same-length rewrite, triggers nothing.
"""

from __future__ import annotations

import ast

from ..api import CheckContext, CheckResult, Feedback, VerifyRequest
from ..config import VerificationConfig


def docstring_regression_reason(original_content: str, new_content: str, config: VerificationConfig) -> str | None:
    try:
        original_doc = ast.get_docstring(ast.parse(original_content)) or ""
    except SyntaxError:
        return None
    if len(original_doc) < config.docstring_min_chars_to_protect:
        return None
    try:
        new_doc = ast.get_docstring(ast.parse(new_content)) or ""
    except SyntaxError:
        return None
    if len(new_doc) < len(original_doc) * config.docstring_shrink_threshold:
        return (
            f"the original file's module docstring ({len(original_doc)} chars, "
            "explaining the file's own rationale) is missing or drastically "
            f"shortened in your draft ({len(new_doc)} chars) -- preserve the "
            "existing documentation unless the change specifically requires "
            "updating it; revise it to reflect a real change, don't just drop it"
        )
    return None


class DocstringCheck:
    name = "docstring"
    cost = "free"

    def applies(self, req: VerifyRequest) -> bool:
        return req.subject.get("original") is not None and (
            req.subject.get("candidate") or req.subject.get("code")
        ) is not None

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        original = req.subject.get("original") or ""
        candidate = req.subject.get("candidate") or req.subject.get("code") or ""
        reason = docstring_regression_reason(original, candidate, ctx.config)
        if reason is None:
            return CheckResult(status="passed", detail="module docstring preserved (or none to protect)")
        return CheckResult(
            status="failed",
            detail=reason,
            evidence={"original_chars": len(original), "candidate_chars": len(candidate)},
            feedback=Feedback(mechanical_errors=(reason,), revise_hint=reason, retryable=True),
        )
