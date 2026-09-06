"""Checklist generation + per-item evaluation (checklist.py). Uses a fake
`think` callable rather than the real cognition.think wire call -- these
are unit tests of the parsing/aggregation logic, not the bus."""

import unittest

from simorgh.verification.api import ThinkReply, VerifyRequest
from simorgh.verification.checklist import AnsweredItem, ChecklistItem, evaluate_checklist, generate_checklist
from simorgh.verification.config import VerificationConfig


def _req(checklist_hint=None) -> VerifyRequest:
    return VerifyRequest(
        verification_id="v1", task_id="t1", kind="task",
        subject={"description": "add empty-list handling", "result": "added a guard clause"},
        checklist_hint=checklist_hint,
    )


class TestGenerateChecklist(unittest.IsolatedAsyncioTestCase):
    async def test_checklist_hint_short_circuits_generation(self):
        items = await generate_checklist(None, _req(checklist_hint="does it work?"), VerificationConfig())
        self.assertEqual(items, [ChecklistItem(question="does it work?", required=True)])

    async def test_parses_numbered_required_and_optional_items(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="1. [required] handles empty list?\n2. [optional] has a test?\n")

        items = await generate_checklist(think, _req(), VerificationConfig())
        self.assertEqual(items, [
            ChecklistItem(question="handles empty list?", required=True),
            ChecklistItem(question="has a test?", required=False),
        ])

    async def test_unmarked_item_defaults_to_required(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="1. handles empty list?\n")

        items = await generate_checklist(think, _req(), VerificationConfig())
        self.assertTrue(items[0].required)

    async def test_floor_reply_yields_no_items(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="", floor=True, ok=False)

        items = await generate_checklist(think, _req(), VerificationConfig())
        self.assertEqual(items, [])

    async def test_respects_max_items(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="\n".join(f"{i}. q{i}" for i in range(1, 10)))

        config = VerificationConfig(checklist_max_items=3)
        items = await generate_checklist(think, _req(), config)
        self.assertEqual(len(items), 3)


class TestEvaluateChecklist(unittest.IsolatedAsyncioTestCase):
    async def test_yes_and_no_answers_parsed(self):
        replies = iter([ThinkReply(text="YES, it does."), ThinkReply(text="NO, missing a case.")])

        async def think(*, purpose, prompt):
            return next(replies)

        items = [ChecklistItem(question="q1", required=True), ChecklistItem(question="q2", required=False)]
        answered = await evaluate_checklist(think, _req(), items)
        self.assertEqual([a.answer for a in answered], ["yes", "no"])

    async def test_non_answer_becomes_none_not_no(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="I'll look at the file first.")

        answered = await evaluate_checklist(think, _req(), [ChecklistItem(question="q1", required=True)])
        self.assertIsNone(answered[0].answer)

    async def test_floor_reply_becomes_none(self):
        async def think(*, purpose, prompt):
            return ThinkReply(text="", floor=True, ok=False)

        answered = await evaluate_checklist(think, _req(), [ChecklistItem(question="q1", required=True)])
        self.assertIsNone(answered[0].answer)


if __name__ == "__main__":
    unittest.main()
