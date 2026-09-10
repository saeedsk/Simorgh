"""A blocked task must come back through the retry rule, not through its
dead worker's lease.

`_retry_or_block` parks a task as BLOCKED, counts the attempt, and lets
`_reconsider_blocked` bring it back once `blocked_retry_delay_seconds`
have passed -- giving up at `max_blocked_retries`. That is the whole
retry policy.

None of it ran. BLOCKED kept the lease of the worker that had just
finished with the task, `Scheduler.scan_leases` expired that lease like
any other abandoned work, and `lease_expired` puts ANY non-terminal task
straight back to `available`. So a blocked task returned to the queue as
soon as its lease ran out, with no delay, no give-up check, and a
`lease_expired` event per round -- the same shape as the 2026-09-07
resurrection bug (which fixed COMPLETED and FAILED and left this one).

Measured 2026-09-10 with a real Kernel, real Planning, 4 workers and 60
tasks that all block, on a 2-second lease, for 45 seconds:

    before:  claims 221 (per-task max 4), lease_expired 211,
             final statuses {available: 50, blocked: 9, claimed: 1},
             ledger appends 2,906
    after:   claims  60 (per-task max 1), lease_expired   0,
             final statuses {blocked: 60},
             ledger appends 1,564

The run is shorter than one retry delay, so the correct number of
re-runs in it is zero.
"""

from __future__ import annotations

import unittest

from simorgh.ledger.factory import make_ledger
from simorgh.planning.model import AVAILABLE, BLOCKED, CLAIMED, IN_PROGRESS
from simorgh.planning.scheduler import Scheduler
from simorgh.planning.store import TaskStore
from tests.simorgh.helpers import FakeClock


class _Bus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, message) -> None:
        self.published.append(message)


class ABlockedTaskKeepsNoLeaseTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.store = TaskStore(self.ledger, self.clock)
        await self.store.rebuild()
        self.scheduler = Scheduler(self.store, _Bus(), self.clock, source="planning", lease_seconds=600.0)

    async def _blocked(self) -> str:
        task = await self.store.create(kind="patch", description="something hard", origin="human")
        await self.store.transition(task.id, AVAILABLE)
        await self.store.claim(task.id, "w1", 600.0)
        await self.store.transition(task.id, IN_PROGRESS)
        await self.store.transition(task.id, BLOCKED, note="verification said no", attempt=True)
        return task.id

    async def test_blocking_releases_the_lease(self):
        task_id = await self._blocked()
        self.assertIsNone((await self.store.get(task_id)).lease)

    async def test_a_lease_scan_does_not_put_it_back_on_the_queue(self):
        task_id = await self._blocked()
        self.clock.advance(1_000.0)  # long past any lease
        await self.scheduler.scan_leases()
        task = await self.store.get(task_id)
        self.assertEqual(task.status, BLOCKED, "an expired lease skipped the retry delay entirely")
        self.assertEqual(task.attempts, 1, "and the attempt was never counted")

    async def test_no_lease_expired_event_is_written_for_it(self):
        """Each bypass round also cost a `lease_expired` append: 211 of
        them for 60 tasks in a 45-second run."""
        task_id = await self._blocked()
        self.clock.advance(1_000.0)
        await self.scheduler.scan_leases()
        types = [e.type for e in await self.ledger.read(f"task:{task_id}")]
        self.assertNotIn("lease_expired", types)

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
