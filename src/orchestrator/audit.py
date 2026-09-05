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

The sandboxed-execution check specifically is scoped to NEW skill
proposals (subject under src/agents/skills/), not self-patches to
existing core files. The creator's own explicit call, after this was
found live: the sandbox runs code with an empty environment in a bare
temp dir -- correct for a standalone skill file (never supposed to
import project internals), but structurally impossible to pass for a
self-patch's normal cross-module imports, regardless of code quality.
A self-patch's real correctness is already verified downstream by
run_isolated_test_suite (src/orchestrator/self_patch.py), which
actually runs the patched code as part of the whole real test suite
against a full repo copy with the package intact -- so this scoping
routes self-patches to the check that can actually pass a legitimate
import, rather than skipping verification. Every OTHER check here
(denylist, protected-subjects, adaptive-immunity) applies identically
to both classes, unchanged.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from src.agents.skills.registry import SKILLS_DIR
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

# Bounds how much of a failed sandboxed run's real stderr/stdout gets
# folded into the rejection reason -- enough to actually be useful
# feedback for a retry, not so much that one bad run floods the next
# drafting prompt.
_MAX_SANDBOX_DETAIL_CHARS = 500


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

        # The sandbox runs code with an EMPTY environment (`env={}`,
        # `python -I`) in a bare temp dir -- correct isolation for a new,
        # standalone skill file (src/agents/skills/, never supposed to
        # import project internals), but structurally impossible to pass
        # for a self-patch to an existing core file: any normal
        # cross-module import ("from src.orchestrator.console_style
        # import style") fails with `ModuleNotFoundError: No module
        # named 'src'`, regardless of code quality. Verified live: a
        # deliberately tiny, well-scoped self-patch still failed this
        # exact way every attempt. Real correctness/behavior for a
        # self-patch is already verified downstream by
        # run_isolated_test_suite (self_patch.py) -- it actually runs
        # the patched code for real, as part of the whole real test
        # suite, against a full repo copy with the package intact -- so
        # skipping this one check for self-patch subjects doesn't skip
        # verification, it routes to the check that can actually pass a
        # legitimate cross-module import. Every other check above and
        # below (denylist, protected-files, adaptive-immunity) applies
        # identically regardless of subject -- only this one, structurally
        # skill-specific check is scoped to skill subjects.
        sandbox_result: SandboxResult | None = None
        is_new_skill = proposal.subject.startswith(f"{SKILLS_DIR}/")
        if is_new_skill:
            sandbox_result = self._sandbox.run(proposal.code, timeout=self._timeout)
            if not sandbox_result.succeeded:
                # The generic (timed_out=.., exit_code=..) summary alone
                # gives a retry loop nothing to actually act on -- caught
                # live watching a real self-patch task fail this exact same
                # generic way across multiple attempts and reconsideration
                # rounds with zero improvement, because prior_reasons never
                # carried the real error. sandbox_result.stderr/stdout has
                # the actual traceback; folding a bounded excerpt of it in
                # gives the next drafting attempt something concrete to fix
                # instead of guessing blind.
                detail = (sandbox_result.stderr or sandbox_result.stdout or "").strip()
                if len(detail) > _MAX_SANDBOX_DETAIL_CHARS:
                    detail = detail[:_MAX_SANDBOX_DETAIL_CHARS] + "…(truncated)"
                reasons.append(
                    "sandboxed run did not succeed "
                    f"(timed_out={sandbox_result.timed_out}, exit_code={sandbox_result.exit_code})"
                    + (f": {detail}" if detail else "")
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
