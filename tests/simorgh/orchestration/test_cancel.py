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

import asyncio
import time
import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.orchestration.session import CANCELLED_REASON
from simorgh.orchestration.worker import Worker, _CANCEL_MEMORY

from tests.simorgh.orchestration.fakes import FakeCognition, FakePlanning
from tests.simorgh.orchestration.harness import Harness


class _SlowExecution:
    """A real bus subscriber that only answers `action.proposed` after a
    real wall-clock delay -- standing in for a `web_fetch`/
    `run_python_sandboxed` call that is genuinely still running when a
    cancel arrives, unlike `FakeGuardianExecution`'s instant reply."""

    def __init__(self, bus, delay_s: float) -> None:
        self._bus = bus
        self._delay = delay_s
        self._sub = None

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(topics.ACTION_PROPOSED, self._on)

    async def _on(self, message: Message) -> None:
        await asyncio.sleep(self._delay)
        result = message.caused(topics.ACTION_RESULT, {
            "action_id": message.payload["action_id"], "ok": True,
            "output_ref": "", "stdout_preview": "done", "duration_ms": int(self._delay * 1000),
            "side_effects": [],
        }, source="execution")
        await self._bus.publish(result)


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


class TestCancelDuringAReadOnlyToolCall(unittest.IsolatedAsyncioTestCase):
    """A cancel arriving mid-`web_fetch` (or any `read_only`-tagged tool)
    must not sit unnoticed for the tool's whole remaining timeout.

    Live-measured, 2026-09-08: `_EventWaiter.wait` only ever looked at
    the bus, never at the cancel flag, while a single `asyncio.wait_for`
    ran -- so a cancel sent 0.3s into a 3s `web_fetch` was not noticed
    until the full 3s elapsed (a real `web_fetch`'s own timeout is 45s,
    `run_tests`'s is 330s). `apply_source_patch`/`git_commit` and other
    non-`read_only` tools still ride out the real result, since only
    the arrival of `action.result` tells the session what side effect
    (if any) `session.uncommitted` needs to track for cleanup.
    """

    async def test_a_cancel_is_noticed_well_before_a_slow_web_fetch_returns(self) -> None:
        async with Harness() as h:
            planning = FakePlanning(h.client("planning"))
            planning.add_task("t1", kind="chat", mode="execute", description="fetch a slow page")
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "web_fetch", "args": {"url": "http://example.com"}}]},
                {"text": "done"},
            ])
            slow_exec = _SlowExecution(h.client("execution"), delay_s=3.0)
            await planning.start()
            await cognition.start()
            await slow_exec.start()

            worker = Worker(h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1",
                            assemble_timeout_s=0.01)
            await worker.start()

            failed: list[Message] = []
            await h.client("watcher").subscribe(topics.TASK_FAILED, lambda m: failed.append(m) or _noop())
            await h.client("planning").publish(Message.new(
                topics.TASK_AVAILABLE, source="planning",
                payload={"task_id": "t1", "kind": "chat", "lease_seconds": 60.0}, clock=h.clock.now))

            # Let the session actually reach the tool call (action.proposed
            # published, `_SlowExecution` now sitting in its 3s sleep).
            await asyncio.sleep(0.3)
            cancel_sent = time.monotonic()
            await worker._on_cancel(Message.new(  # noqa: SLF001
                topics.TASK_CANCEL, source="benchmark", payload={"task_id": "t1", "reason": "gave up"},
                clock=h.clock.now))

            for _ in range(200):
                if failed:
                    break
                await asyncio.sleep(0.01)
            delay = time.monotonic() - cancel_sent

            self.assertTrue(failed, "a cancelled task must still report an outcome")
            self.assertEqual(failed[0].payload["reason"], CANCELLED_REASON)
            self.assertLess(delay, 1.0,
                            f"cancel took {delay:.2f}s to take effect against a 3s tool call -- "
                            "it must not wait out the tool's own timeout")


async def _noop() -> None:
    return None


if __name__ == "__main__":
    unittest.main()


class TestAPreemptedTaskSurvives(unittest.IsolatedAsyncioTestCase):
    """Preemption must postpone work, not destroy it.

    Observed 2026-09-08, hours after preemption shipped: a curiosity
    task ran 14 real steps, was preempted, was correctly requeued, was
    claimed again 7 seconds later -- and died at step zero in 0.01s,
    terminally failed. `Worker._on_cancel` remembered the id and nothing
    ever removed it, so with a single worker the requeued task always
    came back to the same worker and its own stale cancel killed it.
    Preemption destroyed exactly the work it was meant to postpone.
    """

    async def _worker(self, h: Harness) -> Worker:
        return Worker(h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1")

    async def _cancel(self, h: Harness, worker: Worker, task_id: str, *, requeue: bool) -> None:
        await worker._on_cancel(Message.new(  # noqa: SLF001
            topics.TASK_CANCEL, source="planning",
            payload={"task_id": task_id, "reason": "preempted", "requeue": requeue},
            clock=h.clock.now))

    async def test_a_spent_cancel_is_forgotten_so_the_task_can_run_again(self) -> None:
        async with Harness() as h:
            worker = await self._worker(h)
            await self._cancel(h, worker, "t1", requeue=True)
            self.assertTrue(worker._is_cancelled("t1"))  # noqa: SLF001

            worker._forget_cancel("t1")  # noqa: SLF001 -- what `_on_available` does when the session ends
            self.assertFalse(worker._is_cancelled("t1"),
                             "a requeued task comes back to this same worker and must be allowed to run")

    async def test_a_preemption_is_distinguished_from_a_rejection(self) -> None:
        """Planning has already moved a preempted task back to
        `available`. Reporting an outcome for it would transition it to
        a terminal status instead -- and `available -> failed` is not
        even legal, so it raised, was swallowed, and the record survived
        by accident."""
        async with Harness() as h:
            worker = await self._worker(h)
            await self._cancel(h, worker, "preempted", requeue=True)
            await self._cancel(h, worker, "rejected", requeue=False)
            self.assertTrue(worker._requeued("preempted"))  # noqa: SLF001
            self.assertFalse(worker._requeued("rejected"))  # noqa: SLF001
            self.assertFalse(worker._requeued("never-cancelled"))  # noqa: SLF001
