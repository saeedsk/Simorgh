"""Stage 8 item 5's acceptance: a planted lesson that fixes a held-out
case is adopted; one that regresses another case is refused -- even
when the mean does not move; and the file it would be adopted into is
protected, so the loop cannot put it there itself."""

import asyncio
import unittest

from simorgh.growth.evaluate import evaluate, measure_and_decide
from simorgh.growth.policies import PolicyStore

LESSON = "Run the whole suite before committing."


def _cases(with_rule: dict, without: dict):
    async def run(rules):
        return dict(with_rule if rules else without)
    return run


def _decide(run, repeats=3):
    store = PolicyStore(clock=lambda: 1000.0)

    async def go():
        policy = await store.propose(kind="rule", task_type="patch", body=LESSON, evidence_refs=("task:1",))
        return await measure_and_decide(store, policy.id, run, repeats=repeats)
    return asyncio.run(go())


class ThePlantedLesson(unittest.TestCase):
    def test_one_that_fixes_a_held_out_case_is_adopted(self):
        policy, ev = _decide(_cases({"a": True, "b": True}, {"a": True, "b": False}))
        self.assertEqual(policy.status, "adopted")
        self.assertEqual(ev.fixed, ("b",))
        self.assertEqual((policy.baseline, policy.result, policy.evaluated_on), (0.5, 1.0, 2))

    def test_one_that_breaks_another_case_is_refused_though_the_mean_is_flat(self):
        policy, ev = _decide(_cases({"a": False, "b": True}, {"a": True, "b": False}))
        self.assertEqual(ev.baseline, ev.result)
        self.assertEqual(policy.status, "refused")
        self.assertIn("regressed a", policy.why)

    def test_one_that_changes_nothing_is_refused(self):
        policy, _ = _decide(_cases({"a": True}, {"a": True}))
        self.assertEqual(policy.status, "refused")
        self.assertIn("fixed none", policy.why)

    def test_one_lucky_run_is_not_a_fix(self):
        runs = iter([{"a": False}, {"a": True}, {"a": False}, {"a": False}, {"a": False}, {"a": False}])

        async def run(_rules):
            return next(runs)
        ev = asyncio.run(evaluate(LESSON, run, repeats=3))
        self.assertEqual(ev.fixed, ())


class WhereItLands(unittest.TestCase):
    def test_an_adopted_rule_is_proposed_as_policy_adopt_and_a_refused_one_is_not(self):
        landed = []

        async def land(payload):
            landed.append(payload)

        store = PolicyStore(clock=lambda: 1000.0)

        async def go():
            good = await store.propose(kind="rule", task_type="patch", body=LESSON)
            await measure_and_decide(store, good.id, _cases({"a": True}, {"a": False}), land=land)
            bad = await store.propose(kind="rule", task_type="patch", body="Skip the tests.")
            await measure_and_decide(store, bad.id, _cases({"a": False}, {"a": True}), land=land)
        asyncio.run(go())
        self.assertEqual(len(landed), 1)
        self.assertEqual(landed[0]["tool"], "policy_adopt")
        self.assertEqual(landed[0]["args"]["path"], "rules/patch.md")
        self.assertEqual(landed[0]["args"]["rule"], LESSON)

    def test_guardian_asks_a_person_before_it_lands(self):
        from simorgh.guardian.api import DecisionContext, Proposal
        from simorgh.guardian.config import Config
        from simorgh.guardian.posture import Posture
        from simorgh.guardian.rules import ProtectedRule
        from simorgh.growth.evaluate import adoption_action
        from simorgh.growth.policies import Policy

        p = adoption_action(Policy(id="p1", kind="rule", task_type="patch", body=LESSON, status="adopted"))
        proposal = Proposal(action_id=p["action_id"], tool=p["tool"], args=p["args"], scope=p["scope"],
                            reversibility=p["reversibility"], rationale=p["rationale"], proposed_by=p["proposed_by"])
        ctx = DecisionContext(now=0.0, system_state="running", posture=Posture(level="trusted"), config=Config())
        self.assertEqual(asyncio.run(ProtectedRule().evaluate(proposal, ctx)).kind, "escalate")


if __name__ == "__main__":
    unittest.main()
