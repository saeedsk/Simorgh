"""Stage 4 item 6: an attempt's budget in tokens, dollars and time."""

import unittest

from simorgh.orchestration import profiles
from simorgh.orchestration.api import Budget, Session
from simorgh.orchestration.session import BUDGET_REASON, CONTINUATION_REASON, SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run


class TheRule(unittest.TestCase):
    def test_which_budget_ran_out(self):
        self.assertEqual(Budget(max_steps=10).over(tokens=10**9, usd=99.0, wall_s=1e6), "")
        self.assertTrue(Budget(max_steps=10, max_tokens=100).over(tokens=100, usd=0, wall_s=0).startswith("tokens"))
        self.assertTrue(Budget(max_steps=10, max_usd=0.5).over(tokens=0, usd=0.6, wall_s=0).startswith("usd"))
        self.assertTrue(Budget(max_steps=10, max_wall_s=60).over(tokens=0, usd=0, wall_s=61).startswith("wall"))

    def test_it_is_not_a_continuation(self):
        self.assertFalse(BUDGET_REASON.startswith(CONTINUATION_REASON))


class AnAttemptStopsWhenItsMoneyIsSpent(unittest.TestCase):
    @run
    async def test_blocked_naming_the_budget(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "read_file", "args": {"path": "a.py"}}]}])
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start()
            await gx.start()
            session = Session(task_id="t1", kind="research", mode="execute", profile=profiles.RESEARCH)
            session.budget.max_steps = 20
            session.budget.max_usd = 0.01
            session.spent_usd = 0.02       # already over, as if earlier steps had spent it
            outcome = await SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now).run(session, user_text="x")
            self.assertEqual(outcome.kind, "blocked")
            self.assertTrue(outcome.reason.startswith(f"{BUDGET_REASON}: usd"), outcome.reason)
            await cognition.stop()
            await gx.stop()
