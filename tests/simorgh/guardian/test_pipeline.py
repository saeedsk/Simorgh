"""`Pipeline.decide`'s own control flow (09-guardian.md section 5.1):
deny always wins and short-circuits; an escalate is remembered but
evaluation continues; classifier interprets ALLOW/DENY/other when
enabled, else escalations fall through to needs_human."""

import unittest

from simorgh.guardian.api import Decision, DecisionContext, Proposal
from simorgh.guardian.config import Config
from simorgh.guardian.pipeline import Pipeline
from simorgh.guardian.posture import Posture


def _proposal() -> Proposal:
    return Proposal(
        action_id="a1", tool="read_file", args={}, scope={}, reversibility="read_only",
        rationale="test", proposed_by="test",
    )


def _ctx(**overrides) -> DecisionContext:
    base = dict(
        now=0.0, system_state="running", posture=Posture(level="guarded", baseline="guarded"),
        config=Config(),
    )
    base.update(overrides)
    return DecisionContext(**base)


class _FixedRule:
    def __init__(self, name: str, kind: str, layer: str | None = None, reasons=()) -> None:
        self.name = name
        self.layer = layer or name
        self._kind = kind
        self._reasons = reasons
        self.called = False

    async def evaluate(self, proposal, ctx) -> Decision:
        self.called = True
        return Decision(self._kind, self.layer, self._reasons)


class TestPipelineOrdering(unittest.IsolatedAsyncioTestCase):
    async def test_all_abstain_is_approved(self):
        pipeline = Pipeline((_FixedRule("a", "abstain"), _FixedRule("b", "abstain")))
        verdict = await pipeline.decide(_proposal(), _ctx())
        self.assertEqual(verdict.kind, "approved")

    async def test_first_deny_short_circuits_later_rules(self):
        deny = _FixedRule("deny", "deny", reasons=("nope",))
        never_reached = _FixedRule("later", "deny")
        pipeline = Pipeline((deny, never_reached))
        verdict = await pipeline.decide(_proposal(), _ctx())
        self.assertEqual(verdict.kind, "denied")
        self.assertEqual(verdict.layer, "deny")
        self.assertFalse(never_reached.called)

    async def test_deny_wins_over_an_earlier_allow(self):
        pipeline = Pipeline((_FixedRule("allow", "allow"), _FixedRule("deny", "deny")))
        verdict = await pipeline.decide(_proposal(), _ctx())
        self.assertEqual(verdict.kind, "denied")

    async def test_escalate_without_a_later_deny_becomes_needs_human(self):
        pipeline = Pipeline((_FixedRule("esc", "escalate", reasons=("irreversible",)),))
        verdict = await pipeline.decide(_proposal(), _ctx())
        self.assertEqual(verdict.kind, "needs_human")
        self.assertEqual(verdict.reasons, ("irreversible",))

    async def test_a_later_deny_still_wins_after_an_earlier_escalate(self):
        pipeline = Pipeline((_FixedRule("esc", "escalate"), _FixedRule("deny", "deny")))
        verdict = await pipeline.decide(_proposal(), _ctx())
        self.assertEqual(verdict.kind, "denied")

    async def test_only_the_first_escalation_is_remembered(self):
        first = _FixedRule("first", "escalate", reasons=("first reason",))
        second = _FixedRule("second", "escalate", reasons=("second reason",))
        pipeline = Pipeline((first, second))
        verdict = await pipeline.decide(_proposal(), _ctx())
        self.assertEqual(verdict.layer, "first")
        self.assertEqual(verdict.reasons, ("first reason",))


class TestPipelineClassifier(unittest.IsolatedAsyncioTestCase):
    async def test_classifier_allow_approves(self):
        async def classify(proposal):
            return "ALLOW"

        pipeline = Pipeline((_FixedRule("esc", "escalate"),))
        ctx = _ctx(config=Config(classifier_enabled=True), classify=classify)
        verdict = await pipeline.decide(_proposal(), ctx)
        self.assertEqual(verdict.kind, "approved")

    async def test_classifier_deny_denies_with_classifier_layer(self):
        async def classify(proposal):
            return "DENY"

        pipeline = Pipeline((_FixedRule("esc", "escalate", reasons=("r",)),))
        ctx = _ctx(config=Config(classifier_enabled=True), classify=classify)
        verdict = await pipeline.decide(_proposal(), ctx)
        self.assertEqual(verdict.kind, "denied")
        self.assertEqual(verdict.layer, "classifier")

    async def test_classifier_ask_or_none_falls_through_to_needs_human(self):
        async def classify(proposal):
            return None

        pipeline = Pipeline((_FixedRule("esc", "escalate"),))
        ctx = _ctx(config=Config(classifier_enabled=True), classify=classify)
        verdict = await pipeline.decide(_proposal(), ctx)
        self.assertEqual(verdict.kind, "needs_human")

    async def test_classifier_disabled_skips_straight_to_needs_human(self):
        called = False

        async def classify(proposal):
            nonlocal called
            called = True
            return "ALLOW"

        pipeline = Pipeline((_FixedRule("esc", "escalate"),))
        ctx = _ctx(config=Config(classifier_enabled=False), classify=classify)
        verdict = await pipeline.decide(_proposal(), ctx)
        self.assertEqual(verdict.kind, "needs_human")
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
