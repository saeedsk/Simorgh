"""Worker-level tests: the claim loop, terminal reporting, and resume on
a second Worker after a simulated crash (S5/S7, 16 section 6/9)."""

import unittest

from simorgh.contracts import topics
from simorgh.orchestration.worker import Worker

from .fakes import FakeCognition, FakeGuardianExecution, FakePlanning
from .harness import Harness, run


class TestWorkerClaimLoop(unittest.TestCase):
    @run
    async def test_claims_a_known_task_and_completes_it(self):
        async with Harness() as h:
            planning = FakePlanning(h.client("planning"))
            planning.add_task("t1", kind="chat", mode="execute", description="hi")
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "hello back"}])
            await planning.start()
            await cognition.start()

            # A tiny assemble timeout: no self/persona/memory subsystem is
            # running in this test, so Assembler.assemble() must degrade via
            # a real asyncio.wait_for timeout (03 section 9) -- keep that
            # real wait short so the test doesn't need to pump for long.
            worker = Worker(
                h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1",
                assemble_timeout_s=0.01,
            )
            await worker.start()

            completed = {}

            async def _on_turn(message):
                completed["turn"] = message

            sub = await h.client("interface").subscribe(topics.TURN_COMPLETED, _on_turn)

            from simorgh.contracts.envelope import Message
            await h.client("planning").publish(Message.new(
                topics.TASK_AVAILABLE, source="planning",
                payload={"task_id": "t1", "kind": "chat", "lease_seconds": 60.0},
                clock=h.clock.now,
            ))
            # The worker's claim + THINK round-trip runs as a detached task
            # (dispatched by the bus, not awaited here) -- real_delay lets
            # its real assemble-timeout waits actually elapse.
            await h.pump(30, real_delay=0.01)

            self.assertIn("turn", completed)
            self.assertEqual(completed["turn"].payload["text"], "hello back")

            await sub.unsubscribe()
            await worker.stop()
            await planning.stop()
            await cognition.stop()

    @run
    async def test_an_unknown_task_id_is_not_granted_and_worker_does_not_crash(self):
        async with Harness() as h:
            planning = FakePlanning(h.client("planning"))  # no tasks registered
            await planning.start()
            worker = Worker(h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1")
            await worker.start()

            from simorgh.contracts.envelope import Message
            await h.client("planning").publish(Message.new(
                topics.TASK_AVAILABLE, source="planning",
                payload={"task_id": "ghost", "kind": "chat", "lease_seconds": 60.0},
                clock=h.clock.now,
            ))
            await h.pump(10)  # must not raise / hang

            await worker.stop()
            await planning.stop()


class TestResumeOnASecondWorker(unittest.TestCase):
    @run
    async def test_a_second_worker_does_not_redo_completed_steps(self):
        """S5/S7: w1 runs one tool-call step and its `task.step` is
        durable; a fresh Worker (simulating a restart) resuming the same
        task_id restores the step count from the Ledger before running,
        so its own budget correctly reflects the work already done."""
        async with Harness() as h:
            gx = FakeGuardianExecution(h.client("guardian"))
            await gx.start()

            cognition1 = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "read_file", "args": {"path": "x"}}]},
            ])
            await cognition1.start()
            w1 = Worker(h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1")
            from simorgh.orchestration import profiles
            from simorgh.orchestration.api import Session
            from simorgh.orchestration.resume import restore_step_count
            from simorgh.orchestration.session import SessionRunner

            session1 = Session(task_id="t9", kind="chat", mode="execute", profile=profiles.CHAT)
            session1.budget.max_steps = 2  # force a stop after exactly one step this "run"
            runner1 = SessionRunner(w1._bus, h.ledger, clock=h.clock.now, worker_id="w1")
            await runner1.run(session1, user_text="hi")  # completes at max_steps with floor/final text
            await cognition1.stop()

            steps_after_first_run = len((await h.ledger.read("task:t9")))
            self.assertGreaterEqual(steps_after_first_run, 1)

            # A fresh session object (simulating a second Worker after a
            # restart) restores its step count from the same stream.
            session2 = Session(task_id="t9", kind="chat", mode="execute", profile=profiles.CHAT)
            restored = await restore_step_count(session2, h.ledger)
            self.assertGreaterEqual(restored, 1)
            self.assertEqual(session2.budget.steps_used, restored)

            await gx.stop()


if __name__ == "__main__":
    unittest.main()
