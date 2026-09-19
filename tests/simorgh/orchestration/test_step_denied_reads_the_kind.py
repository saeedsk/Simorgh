"""A step's `denied` flag comes from the outcome's kind, not its words
(stage 2 item 8).

`denied` means the Guardian refused the call before it ran
(`api.Step.denied`); Verification reads it to tell a write that never
started from one that ran and failed. It used to be worked out of the
detail text's "denied: " prefix, so a tool whose own error happened to
start with those words read as a Guardian denial.
"""

import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import DENIED_KIND, Detail, SessionRunner, was_denied

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run


class TestWasDenied(unittest.TestCase):
    def test_the_kind_decides(self):
        self.assertTrue(was_denied(Detail("anything", DENIED_KIND)))
        self.assertFalse(was_denied(Detail("denied: the words say so", "refused")))
        self.assertFalse(was_denied(Detail("", "")))

    def test_a_plain_string_falls_back_to_the_prefix(self):
        # A step read back from an older record has no kind.
        self.assertTrue(was_denied("denied: policy"))
        self.assertFalse(was_denied("refused: not a Guardian denial"))
        self.assertFalse(was_denied(""))

    def test_a_detail_is_still_a_string(self):
        detail = Detail("denied: x", DENIED_KIND)
        self.assertEqual(detail, "denied: x")
        self.assertIsInstance(detail, str)


class _FailingExecution(FakeGuardianExecution):
    """Approves, then reports a failed result with a given kind."""

    def __init__(self, bus, *, error: str, error_kind: str) -> None:
        super().__init__(bus)
        self._error, self._kind = error, error_kind

    async def _on(self, message):
        self.proposals.append(message)
        await self._bus.publish(message.caused(topics.ACTION_RESULT, {
            "action_id": message.payload["action_id"], "ok": False, "output_ref": "", "stdout_preview": "",
            "duration_ms": 1, "side_effects": [], "error": self._error, "error_kind": self._kind,
        }, source="execution"))


class TestTheStepFlag(unittest.TestCase):
    async def _one_step(self, gx_factory):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "web_fetch", "args": {"path": "http://example.com/"}}]},
                {"text": "done"},
            ])
            gx = gx_factory(h.client("guardian"))
            await cognition.start()
            await gx.start()
            try:
                runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
                session = Session(task_id="t-kind", kind="chat", mode="execute", profile=profiles.CHAT)
                await runner.run(session, user_text="fetch it")
                return session.steps[0]
            finally:
                await cognition.stop()
                await gx.stop()

    @run
    async def test_a_guardian_denial_is_denied(self):
        step = await self._one_step(lambda bus: FakeGuardianExecution(bus, deny=True))
        self.assertFalse(step.ok)
        self.assertTrue(step.denied)

    @run
    async def test_a_tool_refusal_worded_like_a_denial_is_not(self):
        step = await self._one_step(
            lambda bus: _FailingExecution(bus, error="denied: the site said no", error_kind="refused"))
        self.assertFalse(step.ok)
        self.assertFalse(step.denied)


if __name__ == "__main__":
    unittest.main()
