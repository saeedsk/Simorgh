"""Escalation signals: a THINK asks for the strong tier (design section 7)."""

from __future__ import annotations

import unittest
from dataclasses import replace

from simorgh.orchestration import profiles
from simorgh.orchestration.api import Budget, Session, Step
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition
from .harness import Harness, run


def _session(attempt=1):
    s = Session(task_id="t-esc", kind="research", mode="execute", user_text="q",
                profile=replace(profiles.RESEARCH, verify=False, max_steps=4), budget=Budget(max_steps=4))
    s.attempt = attempt
    return s


class Tier(unittest.TestCase):
    def test_signals(self):
        runner = SessionRunner(None, None, escalate_from_attempt=2)
        self.assertEqual(runner._tier(_session(attempt=1)), {})
        self.assertEqual(runner._tier(_session(attempt=2))["tier"], "strong")
        failed_helper = _session()
        failed_helper.record(Step(1, "act", "Helper t-h1 (blocked, 3 steps): no report", tool="delegate", ok=False))
        self.assertEqual(runner._tier(failed_helper)["tier_reason"], "a helper came back without an answer")
        self.assertEqual(SessionRunner(None, None)._tier(_session(attempt=5)), {}, "off by default")

    @run
    async def test_the_tier_reaches_cognition(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "done"}])
            await cognition.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                                   escalate_from_attempt=2)
            await runner.run(_session(attempt=3), user_text="q")
            self.assertEqual(cognition.calls[0].payload.get("tier"), "strong")
            await cognition.stop()


if __name__ == "__main__":
    unittest.main()
