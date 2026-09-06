"""Runs `rules.DEFAULT_PIPELINE` in order and folds the per-rule
Decisions into one Verdict (09-guardian.md section 5.1): the first deny
wins outright; otherwise an escalate is remembered but evaluation
continues (a later rule might still deny); anything left over at the end
is approved. This is the one place pipeline *control flow* lives --
every rule itself is a pure, order-independent function of the same
snapshot.
"""

from __future__ import annotations

from .api import DecisionContext, Proposal, Rule, Verdict


class Pipeline:
    def __init__(self, rules: tuple[Rule, ...]) -> None:
        self.rules = rules

    async def decide(self, proposal: Proposal, ctx: DecisionContext) -> Verdict:
        escalation: tuple[str, tuple[str, ...]] | None = None  # (layer, reasons)
        for rule in self.rules:
            decision = await rule.evaluate(proposal, ctx)
            if decision.kind == "deny":
                return Verdict("denied", decision.layer, decision.reasons)
            if decision.kind == "escalate" and escalation is None:
                escalation = (decision.layer, decision.reasons)
            # allow/abstain: keep going -- an allow from one rule never
            # short-circuits the rest (deny always wins over allow).

        if escalation is not None:
            layer, reasons = escalation
            if ctx.config.classifier_enabled and ctx.classify is not None:
                verdict = await ctx.classify(proposal)
                if verdict == "ALLOW":
                    return Verdict("approved", layer)
                if verdict == "DENY":
                    return Verdict("denied", "classifier", reasons)
                # None (floor) or "ASK": fall through to needs_human.
            return Verdict("needs_human", layer, reasons)

        return Verdict("approved")
