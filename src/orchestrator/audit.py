"""Self-modification audit gate.

Per docs/SOUL.md: Simorgh may research, draft, and sandbox-test new code
on its own initiative, but nothing merges into its own running source
without passing this gate *and*, under current policy, explicit creator
approval. AuditGate.review() never merges anything -- it only produces a
verdict for the creator to act on. See docs/EVOLUTION.md, "The Audit Gate
(Immune System)."
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.sandboxing.sandbox import SandboxExecutor, SandboxResult, SubprocessSandbox

# Capabilities no skill should have at all, independent of what a sandboxed
# run happens to do -- these route around the sandbox Directive 1 (Safety)
# and Directive 5 (Restraint) rely on, so they're rejected before
# execution rather than caught after the fact.
_DENYLIST_PATTERNS: dict[str, str] = {
    r"\bos\.system\b": "shells out via os.system instead of the sandbox (Directive 1)",
    r"\bsubprocess\.(Popen|run|call)\b": (
        "spawns its own subprocess instead of using the sandbox (Directive 1)"
    ),
    r"\bsocket\.\b": "opens raw network sockets (Directive 1, Directive 5)",
    r"\beval\s*\(": "uses eval on dynamic input (Directive 1)",
    r"\b__import__\s*\(\s*['\"]os['\"]": (
        "dynamically imports os to route around static checks (Directive 1)"
    ),
    r"\bctypes\b": "loads ctypes, a common sandbox-escape vector (Directive 1)",
}

# Files a proposal may never target -- matches docs/SOUL.md's "no automated
# process may edit them" clause, extended to this gate's own source so it
# can't be asked to approve disabling itself.
_PROTECTED_SUBJECTS = ("soul.py", "SOUL.md", "audit.py")


@dataclass(frozen=True)
class ModificationProposal:
    """A candidate change to Simorgh's own code, awaiting review."""

    subject: str
    code: str
    rationale: str


@dataclass(frozen=True)
class AuditVerdict:
    approved_by_automation: bool
    requires_human_approval: bool
    reasons: list[str] = field(default_factory=list)
    sandbox_result: SandboxResult | None = None


class AuditGate:
    """Runs a ModificationProposal through static and dynamic checks.

    `requires_human_approval` is always True under the current SOUL.md
    policy default -- automation alone never merges a self-modification,
    no matter how clean the verdict. That default can only change by the
    creator editing this file directly (see SOUL.md, "On changing this
    hierarchy").
    """

    def __init__(
        self, sandbox: SandboxExecutor | None = None, timeout: float = 5.0
    ) -> None:
        self._sandbox = sandbox or SubprocessSandbox()
        self._timeout = timeout

    def review(self, proposal: ModificationProposal) -> AuditVerdict:
        if any(protected in proposal.subject for protected in _PROTECTED_SUBJECTS):
            return AuditVerdict(
                approved_by_automation=False,
                requires_human_approval=True,
                reasons=[
                    f"denied: {proposal.subject!r} is a protected file; only the "
                    "creator may edit it directly"
                ],
            )

        reasons = [
            f"denied: {explanation}"
            for pattern, explanation in _DENYLIST_PATTERNS.items()
            if re.search(pattern, proposal.code)
        ]
        if reasons:
            return AuditVerdict(
                approved_by_automation=False,
                requires_human_approval=True,
                reasons=reasons,
            )

        sandbox_result = self._sandbox.run(proposal.code, timeout=self._timeout)
        if not sandbox_result.succeeded:
            reasons.append(
                "sandboxed run did not succeed "
                f"(timed_out={sandbox_result.timed_out}, exit_code={sandbox_result.exit_code})"
            )

        return AuditVerdict(
            approved_by_automation=not reasons,
            requires_human_approval=True,
            reasons=reasons,
            sandbox_result=sandbox_result,
        )
