"""`tasks clear` (planning/service.py::_on_task_clear): every task
forgotten, a running one told to stop, and the wipe survives a
restart. The creator, 2026-09-12: "give me option to clean up and
erase all tasks (queues, performed, pending, all of them)"."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.planning.model import COMPLETED, IN_PROGRESS
from simorgh.planning.service import Service
from simorgh.planning.store import TaskStore
from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class TasksClearTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(self.backend, source="planning", ledger=self.ledger, clock=self.clock)
        await self.bus.start()
        self.other = make_client(self.backend, source="cli", ledger=self.ledger, clock=self.clock)
        await self.other.start()
        self.ctx = Context(name="planning", instance_id="", run_id="test", mode="single", bus=self.bus,
                           ledger=self.ledger, config={}, secrets={}, clock=self.clock, logger=_Logger(),
                           data_dir=Path(self._tmp.name) / "data")
        self.service = Service()
        await self.service.start(self.ctx)

    async def asyncTearDown(self):
        await self.service.stop()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def test_everything_goes_a_running_task_is_told_to_stop_and_it_stays_gone(self):
        store: TaskStore = self.service._store  # noqa: SLF001
        queued = await store.create(kind="research", description="what does memory export", origin="curiosity",
                                    initial_status="available")
        done = await store.create(kind="patch", description="fix the retry loop", origin="human",
                                  initial_status="available")
        await store.claim(done.id, "w0", 60.0)
        await store.transition(done.id, IN_PROGRESS)
        await store.transition(done.id, COMPLETED)
        running = await store.create(kind="patch", description="build the game", origin="human",
                                     initial_status="available")
        await store.claim(running.id, "w1", 60.0)
        await store.transition(running.id, IN_PROGRESS)
        cancels = []

        async def _cancel(message):
            cancels.append(message.payload["task_id"])
        await self.other.subscribe(topics.TASK_CANCEL, _cancel)
        cleared = []

        async def _cleared(message):
            cleared.append(message.payload)
        await self.other.subscribe(topics.TASK_CLEARED, _cleared)

        reply = await self.other.request(Message.new(topics.TASK_CLEAR_REQUEST, source="cli",
                                                     payload={"reason": "cleared by cli"}), timeout=5.0)
        self.assertEqual(reply.payload, {"cleared": 3, "cancelled": 1})
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertEqual(cancels, [running.id], "only the running one had to be told")
        self.assertEqual(cleared[0]["cleared"], 3)
        listing = await self.other.request(Message.new(topics.TASK_LIST_REQUEST, source="cli", payload={}), timeout=5.0)
        self.assertEqual(listing.payload["tasks"], [])
        # A restart rebuilds the index from the ledger: still nothing.
        fresh = TaskStore(self.ledger, self.clock)
        await fresh.rebuild()
        self.assertEqual(fresh.all(), [])
        # The worker's late "failed" for the cancelled task is harmless.
        await self.other.publish(Message.new(topics.TASK_FAILED, source="orchestration", payload={
            "task_id": running.id, "reason": "cancelled", "terminal": True, "attempts": 1}))
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertEqual(fresh.all(), [])


if __name__ == "__main__":
    unittest.main()
