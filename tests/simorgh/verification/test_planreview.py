"""`review_plan` -- mechanical items (planreview.py): ordering vs.
declared dependencies, a protected target via `guardian.review`, step
count. Model-reviewed goal coverage is exercised via the `insufficient`/
S3-style scenario in the integration tests."""

import unittest

from simorgh.verification.api import ReviewReply, ThinkReply
from simorgh.verification.planreview import review_plan


def _plan(steps, goal="ship the feature"):
    return {"goal": goal, "steps": steps}


async def _approve_think(*, purpose, prompt):
    return ThinkReply(text="YES, every step ties back to the goal.")


async def _approve_review(subject, code, kind):
    return ReviewReply(approved=True)


class TestReviewPlanMechanical(unittest.IsolatedAsyncioTestCase):
    async def test_dependency_ordering_violation_is_revise(self):
        steps = [
            {"step_id": "s1", "depends_on": ["s2"], "kind": "task", "description": "d"},
            {"step_id": "s2", "depends_on": [], "kind": "task", "description": "d"},
        ]
        result = await review_plan(_approve_think, _approve_review, _plan(steps), max_steps=8)
        self.assertEqual(result.verdict, "revise")
        self.assertIn("s1 depends on s2", result.feedback)

    async def test_too_many_steps_is_revise(self):
        steps = [{"step_id": f"s{i}", "depends_on": [], "kind": "task", "description": "d"} for i in range(10)]
        result = await review_plan(_approve_think, _approve_review, _plan(steps), max_steps=8)
        self.assertEqual(result.verdict, "revise")
        self.assertIn("10 steps", result.feedback)

    async def test_protected_target_is_reject(self):
        steps = [{"step_id": "s1", "depends_on": [], "kind": "patch", "description": "d", "subject": "src/main.py"}]

        async def review(subject, code, kind):
            return ReviewReply(approved=False, reasons=("protected target",), layers_run=("protected",))

        result = await review_plan(_approve_think, review, _plan(steps), max_steps=8)
        self.assertEqual(result.verdict, "reject")
        self.assertIn("src/main.py", result.feedback)

    async def test_clean_plan_with_goal_coverage_yes_is_approve(self):
        steps = [{"step_id": "s1", "depends_on": [], "kind": "task", "description": "d", "why": "ties to goal"}]
        result = await review_plan(_approve_think, _approve_review, _plan(steps), max_steps=8)
        self.assertEqual(result.verdict, "approve")
        self.assertEqual(result.checklist[-1]["answer"], "yes")

    async def test_goal_coverage_no_is_revise(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="NO, step s1 doesn't address the goal at all.")

        steps = [{"step_id": "s1", "depends_on": [], "kind": "task", "description": "d", "why": "unrelated"}]
        result = await review_plan(think, _approve_review, _plan(steps), max_steps=8)
        self.assertEqual(result.verdict, "revise")

    async def test_reviewer_floor_is_insufficient_evidence_not_reject(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="", floor=True, ok=False)

        steps = [{"step_id": "s1", "depends_on": [], "kind": "task", "description": "d"}]
        result = await review_plan(think, _approve_review, _plan(steps), max_steps=8)
        self.assertEqual(result.verdict, "insufficient_evidence")

    async def test_reviewer_non_answer_is_insufficient_evidence(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="Let me look at each step in turn before deciding.")

        steps = [{"step_id": "s1", "depends_on": [], "kind": "task", "description": "d"}]
        result = await review_plan(think, _approve_review, _plan(steps), max_steps=8)
        self.assertEqual(result.verdict, "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
