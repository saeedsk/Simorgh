"""The bus's per-handler timeout is a hang guard, not a task budget.

`Worker._on_available` runs a whole task session inside the handler on
purpose -- an unacked delivery is what lets a crashed worker's task be
redelivered -- so the memory backend's 300s default was, silently, the
wall-clock budget of every task Sim ran. Live, 2026-09-10, in the
creator's terminal:

    [bus] handler for task.available raised TimeoutError
      ... session.py, line 1024, in _verify_then_finish
      ... session.py, line 747, in _think
    asyncio.exceptions.CancelledError

seconds from done, on a task that had already produced its answer.
`api.UNBOUNDED` says "this handler's bound is its own"; the backends
honour it; the worker uses it.
"""

from __future__ import annotations

import asyncio
import time
import unittest

from simorgh.bus.api import UNBOUNDED
from simorgh.bus.backends.memory import InMemoryBackend, _handler_timeout
from simorgh.bus.client import BusClient


class HandlerTimeoutTestCase(unittest.TestCase):
    def test_none_and_zero_mean_the_backend_default(self):
        self.assertEqual(_handler_timeout(None, 300.0), 300.0)
        self.assertEqual(_handler_timeout(0, 300.0), 300.0)

    def test_a_number_is_that_number(self):
        self.assertEqual(_handler_timeout(12.5, 300.0), 12.5)

    def test_unbounded_is_no_timeout_at_all(self):
        self.assertIsNone(_handler_timeout(UNBOUNDED, 300.0))


class _RealClock:
    """The backend wants `.now()`; `Message.new` wants a callable."""

    def now(self) -> float:
        return time.time()

    __call__ = now


class LongHandlerTestCase(unittest.IsolatedAsyncioTestCase):
    async def _deliver(self, spec_seconds, *, handler_seconds: float, backend_default: float):
        backend = InMemoryBackend(clock=_RealClock(), handler_timeout=backend_default)
        client = BusClient(backend, source="test", clock=_RealClock())
        await backend.start()
        await client.start()
        finished = asyncio.Event()
        cancelled = asyncio.Event()

        async def handler(message):
            try:
                await asyncio.sleep(handler_seconds)
                finished.set()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        await client.subscribe("task.available", handler, group="workers", max_inflight=1,
                               max_handler_seconds=spec_seconds)
        # The real shape: the client validates against the contract.
        await client.publish(client.new("task.available", {"task_id": "t", "kind": "chat", "lease_seconds": 60.0}))
        waiters = [asyncio.create_task(finished.wait()), asyncio.create_task(cancelled.wait())]
        try:
            await asyncio.wait_for(asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED), timeout=5)
        finally:
            for w in waiters:
                w.cancel()
            await client.stop(drain_seconds=0)
            await backend.stop()
        return finished.is_set(), cancelled.is_set()

    async def test_the_default_still_guards_a_hung_handler(self):
        finished, cancelled = await self._deliver(None, handler_seconds=1.0, backend_default=0.1)
        self.assertTrue(cancelled)
        self.assertFalse(finished)

    async def test_an_unbounded_handler_outlives_the_default(self):
        finished, cancelled = await self._deliver(UNBOUNDED, handler_seconds=0.5, backend_default=0.1)
        self.assertTrue(finished, "the session ran to its own end")
        self.assertFalse(cancelled)


class TheWorkerSubscribesUnboundedTestCase(unittest.TestCase):
    def test_the_worker_asks_for_no_bus_timeout(self):
        import inspect

        from simorgh.orchestration import worker

        source = inspect.getsource(worker.Worker.start)
        self.assertIn("max_handler_seconds=UNBOUNDED", source)


if __name__ == "__main__":
    unittest.main()
