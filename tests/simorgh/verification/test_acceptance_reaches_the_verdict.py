"""A plan node's acceptance criteria are judged by the final verdict
(stage 7 item 4).

They reached only the checkpoint critic, which decides whether to keep
going. The verdict that marks the node done never saw them, so a child
could complete without anyone asking whether its "done when" was met.
"""

import asyncio
import unittest

from simorgh.verification.api import ThinkReply, VerifyRequest
from simorgh.verification.checklist import acceptance_items, evaluate_checklist, generate_checklist
from simorgh.verification.config import VerificationConfig
from simorgh.verification.trajectory import TrajectoryMetrics
from simorgh.verification.verdict import combine


def _req(acceptance):
    return VerifyRequest(verification_id="v", task_id="t", kind="task", subject={
        "kind": "research", "description": "find the year", "result": "2009", "acceptance": acceptance})


class Acceptance(unittest.TestCase):
    def test_each_criterion_is_a_required_item(self):
        items = acceptance_items({"acceptance": ["done when: the year is cited from a source", "a link is given"]})
        self.assertEqual(len(items), 2)
        self.assertTrue(all(i.required for i in items))
        self.assertIn("the year is cited from a source", items[0].question)
        self.assertNotIn("done when", items[0].question)

    def test_they_lead_the_checklist_even_when_the_model_offers_none(self):
        async def think(**_):
            return ThinkReply(text="", floor=True)

        items = asyncio.run(generate_checklist(think, _req(["a link is given"]), VerificationConfig()))
        self.assertEqual([i.required for i in items], [True])

    def test_a_criterion_answered_no_fails_the_verdict(self):
        async def think(prompt="", **_):
            return ThinkReply(text="NO -- no link anywhere" if "acceptance criterion" in prompt else "YES")

        req = _req(["a link is given"])
        items = asyncio.run(generate_checklist(think, req, VerificationConfig()))
        answered = asyncio.run(evaluate_checklist(think, req, items))
        verdict = combine([], answered, TrajectoryMetrics(available=False), VerificationConfig()).verdict
        self.assertEqual(verdict, "fail")

    def test_no_criteria_no_items(self):
        self.assertEqual(acceptance_items({}), [])


if __name__ == "__main__":
    unittest.main()
