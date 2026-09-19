"""A chat turn's tool calls carry the turn's trace (stage 1 item 2)."""

import unittest

from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run


class ATurnCarriesItsTrace(unittest.TestCase):
    @run
    async def test_think_and_proposal_use_the_turn_trace_not_the_conversation_id(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "read_file", "args": {"path": "x.py"}}]}, {"text": "done"},
            ])
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start()
            await gx.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            session = Session(task_id="conversation-1", kind="chat", mode="execute", profile=profiles.CHAT,
                              trace_id="turn-7")
            await runner.run(session, user_text="read x.py")
            self.assertEqual({m.trace_id for m in cognition.calls}, {"turn-7"})
            self.assertEqual(gx.proposals[0].trace_id, "turn-7")
            await cognition.stop()
            await gx.stop()

    def test_a_task_without_one_uses_its_task_id(self):
        session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
        self.assertEqual(session.trace, "t1")
