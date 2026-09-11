"""A paused task must stay paused when its lease runs out.

`_reconsider_awaiting_human` parks a project task as PAUSED once the
human-approval timeout passes, and the plan is marked TIMED_OUT. The
task keeps its lease. PAUSED is not a terminal status, so
`Scheduler.scan_leases` treated that lease like any other abandoned
work and `lease_expired` flipped the task straight back to `available`
-- re-offering a project someone had deliberately not been asked about
again, and re-running plan mode from scratch. Same shape as the
BLOCKED bypass (`test_a_blocked_task_waits_its_retry_delay.py`) and
the 2026-09-07 COMPLETED/FAILED resurrection, one status further along.

Both halves are guarded: the scan skips PAUSED tasks, and `apply` keeps
a PAUSED task paused on `lease_expired` so a ledger that already holds
such an event does not resurrect the task on replay.
"""

from __future__ import annotations

import unittest

from simorgh.ledger.factory import make_ledger
from simorgh.planning.model import AVAILABLE, CLAIMED, IN_PROGRESS, PAUSED
from simorgh.planning.scheduler import Scheduler
from simorgh.planning.store import TaskStore
from tests.simorgh.helpers import FakeClock


class _Bus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, message) -> None:
        self.published.append(message)


class APausedTaskIsNotReopenedByLeaseExpiryTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.store = TaskStore(self.ledger, self.clock)
        await self.store.rebuild()
        self.scheduler = Scheduler(self.store, _Bus(), self.clock, source="planning", lease_seconds=600.0)

    async def _paused(self) -> str:
        task = await self.store.create(kind="project", description="a plan nobody answered", origin="human")
        await self.store.transition(task.id, AVAILABLE)
        await self.store.claim(task.id, "w1", 600.0)
        await self.store.transition(task.id, IN_PROGRESS)
        await self.store.transition(task.id, PAUSED, note="human approval timed out")
        return task.id

    async def test_a_lease_scan_leaves_it_paused(self):
        task_id = await self._paused()
        self.clock.advance(1_000.0)  # long past the lease
        await self.scheduler.scan_leases()
        task = await self.store.get(task_id)
        self.assertEqual(task.status, PAUSED, "an expired lease re-opened a task that was parked on purpose")

    async def test_no_lease_expired_event_is_written_for_it(self):
        task_id = await self._paused()
        self.clock.advance(1_000.0)
        await self.scheduler.scan_leases()
        types = [e.type for e in await self.ledger.read(f"task:{task_id}")]
        self.assertNotIn("lease_expired", types)

    async def test_an_explicit_expiry_still_keeps_it_paused(self):
        """The `apply` guard: a `lease_expired` event already in the
        ledger (written before this fix, or by another path) releases
        the lease but must not change the status."""
        task_id = await self._paused()
        await self.store.expire_lease(task_id)
        task = await self.store.get(task_id)
        self.assertEqual(task.status, PAUSED)
        self.assertIsNone(task.lease)

    async def test_a_claimed_task_whose_worker_died_is_still_recovered(self):
        """The rule this narrows must still do its real job."""
        task = await self.store.create(kind="patch", description="a worker will die on this", origin="human")
        await self.store.transition(task.id, AVAILABLE)
        await self.store.claim(task.id, "w1", 600.0)
        self.assertEqual((await self.store.get(task.id)).status, CLAIMED)
        self.clock.advance(1_000.0)
        await self.scheduler.scan_leases()
        self.assertEqual((await self.store.get(task.id)).status, AVAILABLE)


if __name__ == "__main__":
    unittest.main()
