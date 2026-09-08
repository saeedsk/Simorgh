"""A task nobody is waiting for any more has to be able to stop.

Nothing in the system could cancel anything before 2026-09-08. The
benchmark runner made the cost visible: the Worker takes one task at a
time, so a case that timed out kept its worker, and every later case
queued behind a run whose answer would be discarded -- each then timing
out in turn, for a reason that never appeared in the result.

Cancellation is cooperative and checked between steps. Tearing down the
coroutine mid-step would abandon an applied-but-uncommitted edit in the
working tree, which is exactly the shape of the 2026-09-07 false
completion; stopping at a boundary lets `SessionRunner`'s own cleanup
run.
"""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.orchestration.session import CANCELLED_REASON
from simorgh.orchestration.worker import Worker, _CANCEL_MEMORY

from tests.simorgh.orchestration.fakes import FakeCognition, FakePlanning
from tests.simorgh.orchestration.harness import Harness


class TestCancellingARunningTask(unittest.IsolatedAsyncioTestCase):
    async def test_a_cancelled_session_stops_and_reports_failed(self) -> None:
        async with Harness() as h:
            planning = FakePlanning(h.client("planning"))
            planning.add_task("t1", kind="chat", mode="execute", description="a long question")
            # More replies than the cancel should ever let it consume.
            cognition = FakeCognition(h.client("cognition"), script=[{"text": f"turn {n}"} for n in range(8)])
            await planning.start()
            await cognition.start()

            worker = Worker(h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1",
                            assemble_timeout_s=0.01)
            await worker.start()
            await worker._on_cancel(Message.new(  # noqa: SLF001
                topics.TASK_CANCEL, source="benchmark", payload={"task_id": "t1", "reason": "gave up"},
                clock=h.clock.now))

            failed: list[Message] = []
            await h.client("watcher").subscribe(topics.TASK_FAILED, lambda m: failed.append(m) or _noop())
            await h.client("planning").publish(Message.new(
                topics.TASK_AVAILABLE, source="planning",
                payload={"task_id": "t1", "kind": "chat", "lease_seconds": 60.0}, clock=h.clock.now))
            await h.pump(40, real_delay=0.01)

            self.assertTrue(failed, "a cancelled task must still report an outcome")
            self.assertEqual(failed[0].payload["reason"], CANCELLED_REASON)
            self.assertTrue(failed[0].payload["terminal"],
                            "a cancelled task must not be retried; that is the resurrection loop")

    async def test_a_cancel_for_a_different_task_does_not_stop_this_one(self) -> None:
        async with Harness() as h:
            planning = FakePlanning(h.client("planning"))
            planning.add_task("t1", kind="chat", mode="execute", description="hi")
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "hello back"}])
            await planning.start()
            await cognition.start()

            worker = Worker(h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1",
                            assemble_timeout_s=0.01)
            await worker.start()
            await worker._on_cancel(Message.new(  # noqa: SLF001
                topics.TASK_CANCEL, source="benchmark", payload={"task_id": "somebody-else"}, clock=h.clock.now))

            completed: list[Message] = []
            await h.client("watcher").subscribe(topics.TURN_COMPLETED, lambda m: completed.append(m) or _noop())
            await h.client("planning").publish(Message.new(
                topics.TASK_AVAILABLE, source="planning",
                payload={"task_id": "t1", "kind": "chat", "lease_seconds": 60.0}, clock=h.clock.now))
            await h.pump(40, real_delay=0.01)
            self.assertTrue(completed, "an unrelated cancel must not stop this task")


class TestTheWorkersCancelMemory(unittest.IsolatedAsyncioTestCase):
    async def _worker(self, h: Harness) -> Worker:
        return Worker(h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1")

    async def _cancel(self, h: Harness, worker: Worker, task_id: str) -> None:
        await worker._on_cancel(Message.new(  # noqa: SLF001
            topics.TASK_CANCEL, source="test", payload={"task_id": task_id}, clock=h.clock.now))

    async def test_an_empty_id_is_not_remembered(self) -> None:
        async with Harness() as h:
            worker = await self._worker(h)
            await self._cancel(h, worker, "")
            self.assertFalse(worker._is_cancelled(""))  # noqa: SLF001

    async def test_the_memory_is_bounded(self) -> None:
        """A cancel for a task this worker never had would otherwise
        accumulate for the life of the process."""
        async with Harness() as h:
            worker = await self._worker(h)
            for n in range(_CANCEL_MEMORY + 50):
                await self._cancel(h, worker, f"t{n}")
            self.assertLessEqual(len(worker._cancelled), _CANCEL_MEMORY)  # noqa: SLF001
            self.assertTrue(worker._is_cancelled(f"t{_CANCEL_MEMORY + 49}"), "the newest survives")  # noqa: SLF001
            self.assertFalse(worker._is_cancelled("t0"), "the oldest is forgotten first")  # noqa: SLF001


async def _noop() -> None:
    return None


if __name__ == "__main__":
    unittest.main()
