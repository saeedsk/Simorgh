"""A task whose action needs a person waits for the answer.

2026-09-19, the write-a-skill trial: the session recorded "needs human"
as a failed step and moved on. The person's yes then ran apply_skill
after the session had ended, and the landing was refused over the file
it wrote. A chat turn still does not wait: the person is right there.
"""

import unittest

from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution, FakeVerification
from .harness import Harness, run


class ATaskWaitsForThePerson(unittest.TestCase):
    async def _one_call(self, profile, kind):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "read_file", "args": {"path": "x.py"}}]},
                {"text": "done"},
            ])
            gx = FakeGuardianExecution(h.client("guardian"), ask_first=True)
            verification = FakeVerification(h.client("verification"))
            for fake in (cognition, gx, verification):
                await fake.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            session = Session(task_id="t1", kind=kind, mode="execute", profile=profile)
            await runner.run(session, user_text="read x.py")
            for fake in (cognition, gx, verification):
                await fake.stop()
            return session.steps[0]

    @run
    async def test_a_task_step_gets_the_result_after_the_question(self):
        step = await self._one_call(profiles.PATCH, "patch")
        self.assertTrue(step.ok, step.summary)
        self.assertNotIn("needs human", step.summary)

    @run
    async def test_a_chat_turn_hears_the_question_and_moves_on(self):
        step = await self._one_call(profiles.CHAT, "chat")
        self.assertFalse(step.ok)
        self.assertIn("needs human", step.summary)
