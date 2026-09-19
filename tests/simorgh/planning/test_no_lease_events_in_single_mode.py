"""Stage 4 item 10: in single mode a lease renewal is not written down."""

import unittest

from simorgh.ledger.factory import make_ledger
from simorgh.planning.model import AVAILABLE
from simorgh.planning.store import TaskStore
from tests.simorgh.helpers import FakeClock


class NoLeaseEventsInSingleMode(unittest.IsolatedAsyncioTestCase):
    async def _claimed(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        store = TaskStore(self.ledger, self.clock)
        await store.rebuild()
        task = await store.create(kind="patch", description="x", origin="human", initial_status=AVAILABLE)
        await store.claim(task.id, "w0", 600.0)
        return store, task.id

    async def test_an_in_memory_renewal_moves_the_lease_and_writes_nothing(self):
        store, task_id = await self._claimed()
        before = len(await self.ledger.read(f"task:{task_id}"))
        until = (await store.get(task_id)).lease.until
        self.clock.advance(100.0)
        await store.refresh_lease(task_id, 600.0, durable=False)
        self.assertEqual(len(await self.ledger.read(f"task:{task_id}")), before)
        self.assertGreater((await store.get(task_id)).lease.until, until)

    async def test_a_durable_renewal_is_still_written(self):
        store, task_id = await self._claimed()
        await store.refresh_lease(task_id, 600.0)
        self.assertEqual((await self.ledger.read(f"task:{task_id}"))[-1].type, "lease_refreshed")
