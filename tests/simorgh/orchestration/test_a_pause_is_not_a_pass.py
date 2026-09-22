"""A pause during verification parks the task; it never accepts it
unverified (stage 0 item 32).

Verification now waits a pause out instead of running tests through
it, so Orchestration's verify wait can run out while the system is
paused. That silence used to read "accepted unverified" -- the false
pass. It is the pause, and the resumed attempt asks again.
"""

import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition
from .harness import Harness, run


class APauseDuringVerification(unittest.TestCase):
    @run
    async def test_the_task_is_parked_not_accepted(self):
        async with Harness() as h:
            bus = h.client("orchestration")
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "VALUE = 1\n"}])
            paused = {"v": False}
            seen = []

            async def _verification_pauses(message):
                seen.append(message)
                paused["v"] = True        # paused while Verification has it; it never answers

            sub = await h.client("verification").subscribe(topics.VERIFY_REQUESTED, _verification_pauses)
            await cognition.start()
            runner = SessionRunner(bus, h.ledger, clock=h.clock.now, verify_timeout_s=0.05,
                                   is_paused=lambda: paused["v"])
            session = Session(task_id="tp", kind="patch", mode="execute", profile=profiles.PATCH)
            outcome = await runner.run(session)

            self.assertEqual(len(seen), 1)
            self.assertEqual(outcome.kind, "paused")
            self.assertFalse(any("accepted unverified" in s.summary for s in session.steps))
            await cognition.stop()
            await sub.unsubscribe()

    @run
    async def test_no_request_is_sent_while_paused(self):
        async with Harness() as h:
            bus = h.client("orchestration")
            paused = {"v": False}

            class _PausesOnReply(FakeCognition):
                async def _on(self, message):
                    await super()._on(message)
                    paused["v"] = True

            cognition = _PausesOnReply(h.client("cognition"), script=[{"text": "VALUE = 1\n"}])
            seen = []

            async def _record(message):
                seen.append(message)

            sub = await h.client("verification").subscribe(topics.VERIFY_REQUESTED, _record)
            await cognition.start()
            runner = SessionRunner(bus, h.ledger, clock=h.clock.now, verify_timeout_s=0.05,
                                   is_paused=lambda: paused["v"])
            session = Session(task_id="tq", kind="patch", mode="execute", profile=profiles.PATCH)
            outcome = await runner.run(session)

            self.assertEqual(outcome.kind, "paused")
            self.assertEqual(seen, [])
            await cognition.stop()
            await sub.unsubscribe()


if __name__ == "__main__":
    unittest.main()
