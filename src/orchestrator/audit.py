"""Self-modification audit gate.

Per docs/SOUL.md ("Self-Improvement Philosophy"): Simorgh may research,
draft, and sandbox-test new code on its own initiative. As of the
creator's explicit, logged policy change (docs/SOUL.md, dated), a
proposal that passes this gate -- the static denylist, adaptive-immunity
memory, and a real sandboxed run -- now applies automatically for the
narrow class this gate covers (new skill files; see
src/orchestrator/apply.py), with no separate human-approval step. This
gate's own checks are unchanged; only the human-approval gate *on top of*
those checks was removed, and only for this narrow class. Protected
subjects (soul.py, SOUL.md, audit.py) remain permanently blocked
regardless -- that boundary did not move. See docs/EVOLUTION.md, "The
Audit Gate (Immune System)," and docs/BIOMIMICRY.md, "Proposed: adaptive
immunity for the audit gate."

Two layers of defense, as in biological immunity: a fixed, fast, innate
layer (the denylist and protected-subject list below, which never change
based on experience), and an adaptive layer (when `memory` is given,
every rejection is remembered, and a new proposal that closely resembles
one already rejected is denied on that resemblance alone -- even if it
doesn't match any static pattern).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from src.memory.long_term import MemoryStore
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
    r"\burllib\.request\b": (
        "makes network requests directly via urllib.request instead of the "
        "reviewed web-fetch tool (Directive 1, Directive 5) -- see "
        "src/tools/web_fetch.py"
    ),
    r"\bhttp\.client\b": (
        "makes raw HTTP requests via http.client instead of the reviewed "
        "web-fetch tool (Directive 1, Directive 5) -- see "
        "src/tools/web_fetch.py"
    ),
    r"\brequests\.(get|post|put|delete|patch|head)\s*\(": (
        "makes network requests via the requests library instead of the "
        "reviewed web-fetch tool (Directive 1, Directive 5) -- see "
        "src/tools/web_fetch.py"
    ),
    r"\bftplib\b": "opens FTP connections (Directive 1, Directive 5)",
    r"\bsmtplib\b": "sends email (Directive 1, Directive 5)",
    r"\beval\s*\(": "uses eval on dynamic input (Directive 1)",
    r"\b__import__\s*\(\s*['\"]os['\"]": (
        "dynamically imports os to route around static checks (Directive 1)"
    ),
    r"\bctypes\b": "loads ctypes, a common sandbox-escape vector (Directive 1)",
}

# Files a proposal may never target -- matches docs/SOUL.md's "no automated
# process may edit them" clause, extended to this gate's own source, the
# apply pipeline's (src/orchestrator/apply.py), and the self-patch
# pipeline's (src/orchestrator/self_patch.py) so none of them can be asked
# to approve disabling itself. This list is what actually enforces that
# boundary for BOTH the skills pipeline and the self-patch pipeline --
# both call the same AuditGate.review(), so widening self-patch's target
# scope (see src/orchestrator/self_patch.py) never widened what's
# reachable here. Public (not `_`-prefixed) since main.py's
# discover_creative_improvements also needs it -- to filter an
# impossible target out before ever creating a task for it, not to
# re-decide what's allowed; AuditGate.review() below remains the one
# real enforcement point regardless of what a caller pre-filters.
PROTECTED_SUBJECTS = ("soul.py", "SOUL.md", "audit.py", "apply.py", "self_patch.py")

REJECTED_KIND = "rejected_proposal"
DEFAULT_SIMILARITY_THRESHOLD = 0.9


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
    """Runs a ModificationProposal through static, adaptive, and dynamic
    checks.

    `requires_human_approval` is False under the current SOUL.md policy:
    the creator has explicitly authorized auto-merge for proposals that
    pass every check here, for the narrow class this gate covers. This
    constant can only change by the creator editing this file directly
    (see SOUL.md, "On changing this hierarchy") -- it is never something
    Simorgh grants itself.
    """

    def __init__(
        self,
        sandbox: SandboxExecutor | None = None,
        timeout: float = 5.0,
        memory: MemoryStore | None = None,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> None:
        self._sandbox = sandbox or SubprocessSandbox()
        self._timeout = timeout
        self._memory = memory
        self._similarity_threshold = similarity_threshold

    def review(self, proposal: ModificationProposal) -> AuditVerdict:
        if any(protected in proposal.subject for protected in PROTECTED_SUBJECTS):
            return self._deny(
                proposal,
                [
                    f"denied: {proposal.subject!r} is a protected file; only the "
                    "creator may edit it directly"
                ],
            )

        similarity_reason = self._check_adaptive_immunity(proposal.code)
        if similarity_reason is not None:
            return self._deny(proposal, [similarity_reason])

        reasons = [
            f"denied: {explanation}"
            for pattern, explanation in _DENYLIST_PATTERNS.items()
            if re.search(pattern, proposal.code)
        ]
        if reasons:
            return self._deny(proposal, reasons)

        sandbox_result = self._sandbox.run(proposal.code, timeout=self._timeout)
        if not sandbox_result.succeeded:
            reasons.append(
                "sandboxed run did not succeed "
                f"(timed_out={sandbox_result.timed_out}, exit_code={sandbox_result.exit_code})"
            )
            self._remember_rejection(proposal, reasons)

        return AuditVerdict(
            approved_by_automation=not reasons,
            requires_human_approval=False,
            reasons=reasons,
            sandbox_result=sandbox_result,
        )

    def _check_adaptive_immunity(self, code: str) -> str | None:
        """Compare `code` against every previously rejected proposal's code.
        A close match is denied on resemblance alone, without running the
        sandbox -- the point of remembering a threat is responding to it
        faster the second time, not re-deriving it from scratch.
        """
        if self._memory is None:
            return None
        for record in self._memory.query(kind=REJECTED_KIND):
            ratio = difflib.SequenceMatcher(None, code, record.content).ratio()
            if ratio >= self._similarity_threshold:
                return (
                    f"denied: {ratio:.0%} similar to a previously rejected "
                    "proposal (adaptive immunity)"
                )
        return None

    def _deny(self, proposal: ModificationProposal, reasons: list[str]) -> AuditVerdict:
        self._remember_rejection(proposal, reasons)
        return AuditVerdict(
            approved_by_automation=False, requires_human_approval=False, reasons=reasons
        )

    def _remember_rejection(
        self, proposal: ModificationProposal, reasons: list[str]
    ) -> None:
        if self._memory is None:
            return
        self._memory.remember(
            REJECTED_KIND, proposal.code, subject=proposal.subject, reasons=reasons
        )
