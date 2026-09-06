"""The pipeline's rules, in the fixed order 09-guardian.md section 5.1
specifies. Each rule returns `Decision(kind=allow|deny|escalate|abstain,
...)`; `abstain` means "this rule has nothing to say," letting the
pipeline move on. Deny always wins (harness-01) -- the pipeline (in
`pipeline.py`) stops at the first deny and never lets a later rule
override it.
"""

from __future__ import annotations

import difflib
import re

from .api import Decision, DecisionContext, Proposal

# Tools whose subject argument names a file this proposal would touch --
# used by the protected/scope rules to find "the path" in an otherwise
# tool-specific args dict without hardcoding every tool's exact schema.
_SUBJECT_ARG_KEYS = ("subject", "path")


def _subject_paths(proposal: Proposal) -> list[str]:
    paths = list(proposal.scope.get("paths") or [])
    for key in _SUBJECT_ARG_KEYS:
        value = proposal.args.get(key)
        if isinstance(value, str) and value not in paths:
            paths.append(value)
    return paths


class PausedRule:
    name = "paused"
    layer = "paused"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        if ctx.system_state in ("paused", "stopping"):
            return Decision("deny", self.layer, (f"system is {ctx.system_state}",))
        return Decision("abstain", self.layer)


class ModeRule:
    name = "mode"
    layer = "mode"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        effective_mode = ctx.config.mode
        # Posture=locked narrows the effective mode for autonomous
        # origins only -- a human-originated proposal still gets the
        # configured mode (09 section 5.2).
        if ctx.posture.level == "locked" and proposal.origin in ctx.config.autonomous_origins:
            effective_mode = "locked"

        read_only = bool(ctx.tool and ctx.tool.read_only)

        if effective_mode == "observe":
            return Decision("deny", self.layer, ("mode=observe: nothing is auto-approved",))
        if effective_mode == "locked":
            if proposal.origin in ctx.config.autonomous_origins and not read_only:
                return Decision("deny", self.layer, ("mode=locked: autonomous non-read-only work is denied",))
            if proposal.origin not in ctx.config.autonomous_origins and not read_only:
                return Decision("deny", self.layer, ("mode=locked: only read-only actions are allowed",))
            return Decision("abstain", self.layer)
        if proposal.task_mode == "plan" and not read_only:
            return Decision("deny", self.layer, ("plan mode: only read-only tools",))
        return Decision("abstain", self.layer)


class ProtectedRule:
    name = "protected"
    layer = "protected"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        for path in _subject_paths(proposal):
            for protected in ctx.config.protected_subjects:
                if protected in path:
                    return Decision(
                        "deny", self.layer,
                        (f"{path!r} is protected ({protected!r}); only the creator may edit it directly",),
                    )
        return Decision("abstain", self.layer)


class ScopeRule:
    name = "scope"
    layer = "scope"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        # A full task-vs-proposal scope comparison needs task.created's
        # own `scope` (Planning, not built this phase -- 07-planning.md
        # section 12 Q1). Until that lands there is no independent task
        # scope to compare against, so this rule always abstains rather
        # than fabricate a boundary; ProtectedRule and tool-level scope
        # checks in Execution remain the real enforcement in the
        # meantime (defense in depth is still two layers, not zero).
        return Decision("abstain", self.layer)


class DenylistRule:
    name = "denylist"
    layer = "denylist"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        code = proposal.args.get("code")
        if not isinstance(code, str):
            return Decision("abstain", self.layer)
        reasons = tuple(
            f"denied: {explanation}"
            for pattern, explanation in ctx.config.denylist.items()
            if re.search(pattern, code)
        )
        if reasons:
            return Decision("deny", self.layer, reasons)
        return Decision("abstain", self.layer)


class ImmunityRule:
    name = "immunity"
    layer = "immunity"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        code = proposal.args.get("code")
        if not isinstance(code, str) or not code:
            return Decision("abstain", self.layer)
        found = ctx.rejected_similarity(code)
        if found is not None:
            ratio, _ = found
            return Decision(
                "deny", self.layer,
                (f"{ratio:.0%} similar to a previously rejected proposal (adaptive immunity)",),
            )
        return Decision("abstain", self.layer)


def similarity(code: str, excerpts: list[str], threshold: float) -> tuple[float, str] | None:
    """Shared by `ImmunityRule` and `review.py`: the highest-similarity
    match at or above `threshold`, or None. Pure so it's trivially unit
    testable without a Ledger."""
    best: tuple[float, str] | None = None
    for excerpt in excerpts:
        ratio = difflib.SequenceMatcher(None, code, excerpt).ratio()
        if ratio >= threshold and (best is None or ratio > best[0]):
            best = (ratio, excerpt)
    return best


class BudgetRule:
    name = "budget"
    layer = "budget"

    # Tools whose args plausibly cause a model call (drafting); anything
    # else never checks the budget table at all -- a read_file proposal
    # is not slowed down by budget bookkeeping it has no bearing on.
    MODEL_COSTING_TOOLS = frozenset({"draft_patch", "draft_skill", "review"})

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        if proposal.tool not in self.MODEL_COSTING_TOOLS:
            return Decision("abstain", self.layer)
        if not ctx.budgets:
            # No cognition.provider.status has ever arrived -- degrade
            # gracefully (09 section 8: "budget exhausted" is the only
            # failure mode named; "no data" is not the same as
            # "exhausted" and must not block on missing information).
            return Decision("abstain", self.layer)
        for status in ctx.budgets.values():
            if status.fraction_used >= 1.0:
                return Decision("deny", self.layer, (f"{status.provider} budget exhausted for this window",))
        return Decision("abstain", self.layer)


class ReversibilityRule:
    name = "reversibility"
    layer = "reversibility"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        r = proposal.reversibility
        mode = ctx.config.mode if ctx.posture.level != "locked" else "locked"
        if r == "read_only":
            return Decision("allow", self.layer)
        if r == "reversible":
            if mode == "locked":
                return Decision("deny", self.layer, ("locked: only read-only actions are allowed",))
            return Decision("allow", self.layer)
        # irreversible
        if mode == "trusted":
            return Decision("allow", self.layer)
        if mode == "locked":
            return Decision("deny", self.layer, ("locked: irreversible actions are denied",))
        if ctx.config.irreversible_requires_human:
            return Decision("escalate", self.layer, ("irreversible action requires human approval",))
        return Decision("allow", self.layer)


DEFAULT_PIPELINE: tuple = (
    PausedRule(),
    ModeRule(),
    ProtectedRule(),
    ScopeRule(),
    DenylistRule(),
    ImmunityRule(),
    BudgetRule(),
    ReversibilityRule(),
)
