"""Session-level integration tests (16 section 6/9): a real SessionRunner
over the real in-memory Bus/Ledger, against fakes for the subsystems
Orchestration depends on (Cognition, Guardian+Execution, Verification).
"""

import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution, FakeVerification
from .harness import Harness, run


class TestChatTurnWithOneToolCall(unittest.TestCase):
    """S1 (16 section 6): a tool_calls reply, then a final text reply."""

    @run
    async def test_gather_think_act_gather_think_final(self):
        async with Harness() as h:
            bus = h.client("orchestration")
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "read_file", "args": {"path": "src/orchestrator/audit.py"}}]},
                {"text": "audit.py protects self-modification via a denylist and adaptive immunity."},
            ])
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start()
            await gx.start()

            runner = SessionRunner(bus, h.ledger, clock=h.clock.now)
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT)
            outcome = await runner.run(session, user_text="what does audit.py protect?")

            self.assertEqual(outcome.kind, "completed")
            self.assertIn("denylist", outcome.result_summary)
            self.assertEqual(len(gx.proposals), 1)
            self.assertEqual(gx.proposals[0].payload["tool"], "read_file")
            self.assertEqual(len(session.steps), 2)
            self.assertTrue(session.steps[0].ok)

            events = await h.ledger.read("task:t1")
            step_events = [e for e in events if e.type == topics.TASK_STEP]
            self.assertEqual(len(step_events), 2)

            await cognition.stop()
            await gx.stop()

    @run
    async def test_denied_action_is_fed_back_not_a_crash(self):
        """S6 (16 section 6)."""
        async with Harness() as h:
            bus = h.client("orchestration")
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "web_fetch", "args": {"path": "http://169.254.169.254/"}}]},
                {"text": "I couldn't fetch that; it looks like a blocked address."},
            ])
            gx = FakeGuardianExecution(h.client("guardian"), deny=True)
            await cognition.start()
            await gx.start()

            runner = SessionRunner(bus, h.ledger, clock=h.clock.now)
            session = Session(task_id="t2", kind="chat", mode="execute", profile=profiles.CHAT)
            outcome = await runner.run(session, user_text="fetch the metadata endpoint")

            self.assertEqual(outcome.kind, "completed")
            self.assertFalse(session.steps[0].ok)
            self.assertIn("denied", session.steps[0].summary)

            await cognition.stop()
            await gx.stop()

    @run
    async def test_no_cognition_available_degrades_to_the_honest_floor(self):
        async with Harness() as h:
            bus = h.client("orchestration")
            runner = SessionRunner(bus, h.ledger, clock=h.clock.now, think_timeout_s=0.05)
            session = Session(task_id="t3", kind="chat", mode="execute", profile=profiles.CHAT)
            outcome = await runner.run(session, user_text="hello")

            self.assertEqual(outcome.kind, "completed")
            self.assertTrue(outcome.floor)


class TestPatchTaskWithOneRevision(unittest.TestCase):
    """S2 (16 section 6): the evaluator-optimizer bound."""

    @run
    async def test_fail_then_pass_completes_with_a_revision(self):
        async with Harness() as h:
            bus = h.client("orchestration")
            cognition = FakeCognition(h.client("cognition"), script=[
                {"text": "VALUE = 1\n"},
                {"text": "\"\"\"Restored docstring.\"\"\"\nVALUE = 1\n"},
            ])
            verification = FakeVerification(h.client("verification"), verdicts=["fail", "pass"])
            await cognition.start()
            await verification.start()

            runner = SessionRunner(bus, h.ledger, clock=h.clock.now)
            session = Session(task_id="t4", kind="patch", mode="execute", profile=profiles.PATCH)
            session.budget.max_revisions = profiles.PATCH.max_revisions
            outcome = await runner.run(session)

            self.assertEqual(outcome.kind, "completed")
            self.assertIsNotNone(outcome.verification_ref)
            self.assertEqual(session.budget.revisions_used, 1)
            self.assertEqual(len(verification.requests), 2)

            await cognition.stop()
            await verification.stop()

    @run
    async def test_repeated_failure_blocks_after_max_revisions(self):
        async with Harness() as h:
            bus = h.client("orchestration")
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "bad draft\n"}])
            verification = FakeVerification(h.client("verification"), verdicts=["fail"])
            await cognition.start()
            await verification.start()

            runner = SessionRunner(bus, h.ledger, clock=h.clock.now)
            session = Session(task_id="t5", kind="patch", mode="execute", profile=profiles.PATCH)
            session.budget.max_revisions = 1
            outcome = await runner.run(session)

            self.assertEqual(outcome.kind, "blocked")
            self.assertIn("verification failed", outcome.reason)

            await cognition.stop()
            await verification.stop()

    @run
    async def test_no_verification_subsystem_still_completes_honestly(self):
        async with Harness() as h:
            bus = h.client("orchestration")
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "done\n"}])
            await cognition.start()

            runner = SessionRunner(bus, h.ledger, clock=h.clock.now, verify_timeout_s=0.05)
            session = Session(task_id="t6", kind="patch", mode="execute", profile=profiles.PATCH)
            outcome = await runner.run(session)

            self.assertEqual(outcome.kind, "completed")
            self.assertIsNone(outcome.verification_ref)

            await cognition.stop()


class TestPauseMidSession(unittest.TestCase):
    """S5 half (16 section 6): the paused flag is checked between steps."""

    @run
    async def test_paused_flag_produces_task_paused_not_a_crash(self):
        async with Harness() as h:
            bus = h.client("orchestration")
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "read_file", "args": {"path": "x"}}]},
                {"text": "should never get here"},
            ])
            paused = {"v": False}

            class _PausingGuardianExecution(FakeGuardianExecution):
                async def _on(self, message):
                    # Flip pause the instant the action is proposed, before
                    # the result round-trips -- deterministic (no real race,
                    # single event loop) rather than a timing-based flip.
                    paused["v"] = True
                    await super()._on(message)

            gx = _PausingGuardianExecution(h.client("guardian"))
            await cognition.start()
            await gx.start()

            runner = SessionRunner(bus, h.ledger, clock=h.clock.now, is_paused=lambda: paused["v"])
            session = Session(task_id="t7", kind="chat", mode="execute", profile=profiles.CHAT)
            outcome = await runner.run(session, user_text="hi")

            self.assertEqual(outcome.kind, "paused")
            self.assertEqual(len(cognition.calls), 1)  # never reached the second THINK
            events = await h.ledger.read("task:t7")
            self.assertTrue(any(e.type == topics.TASK_PAUSED for e in events))

            await cognition.stop()
            await gx.stop()


if __name__ == "__main__":
    unittest.main()
