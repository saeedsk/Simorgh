"""A finished task must never be handed back to a worker.

Live-caught 2026-09-07, from the creator's own ledger. Completion left
the worker's lease in place; `Scheduler.scan_leases` expired that lease
`lease_seconds` later like any other; and `lease_expired` reset the
status to `available`. So every completed task came back to life ten
minutes after finishing and was worked again, forever.

The evidence: 101 real tasks had produced 1,305 `claimed` events, 1,414
`task.started`, 1,218 `task.completed` and 1,204 `lease_expired`. One
project task carried sixteen rounds of claimed -> started -> completed ->
lease_expired -> claimed in a single stream. It is also the best
explanation for the LLM budget disappearing overnight and for 192,332
trace streams in one day: the same finished work, on a loop.
"""

from __future__ import annotations

import tempfile
import unittest

from simorgh.ledger.factory import make_ledger
from simorgh.planning.model import AVAILABLE, CLAIMED, COMPLETED, FAILED, IN_PROGRESS
from simorgh.planning.scheduler import Scheduler
from simorgh.planning.store import TaskStore
from tests.simorgh.helpers import FakeClock


class _Bus:
    def __init__(self) -> None:
        self.published = []

    async def publish(self, message) -> None:
        self.published.append(message)

    async def subscribe(self, *a, **kw): ...

    async def request(self, *a, **kw): ...

    async def reply(self, *a, **kw): ...


class LeaseExpiryTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.store = TaskStore(self.ledger, self.clock)
        await self.store.rebuild()

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def _claimed(self):
        """A task in the state a worker leaves it in: created, offered,
        claimed. `pending -> available -> claimed` is the real path
        (`model.py`'s transition table); skipping a step is rejected."""
        task = await self.store.create(kind="patch", description="do a thing", origin="human")
        if task.status != AVAILABLE:
            await self.store.transition(task.id, AVAILABLE)
        await self.store.claim(task.id, "w1", 600.0)
        return await self.store.get(task.id)

    # -- the model ---------------------------------------------------------
    async def test_completing_a_task_releases_its_lease(self):
        task = await self._claimed()
        self.assertIsNotNone(task.lease)
        await self.store.transition(task.id, IN_PROGRESS)
        await self.store.transition(task.id, COMPLETED)
        self.assertIsNone((await self.store.get(task.id)).lease)

    async def test_failing_a_task_releases_its_lease_too(self):
        task = await self._claimed()
        await self.store.transition(task.id, IN_PROGRESS)
        await self.store.transition(task.id, FAILED)
        self.assertIsNone((await self.store.get(task.id)).lease)

    async def test_an_in_progress_task_keeps_its_lease(self):
        """Only a *finished* task gives the lease up -- work in flight
        still holds its claim, or another worker could take it."""
        task = await self._claimed()
        await self.store.transition(task.id, IN_PROGRESS)
        self.assertIsNotNone((await self.store.get(task.id)).lease)

    # -- expiry ------------------------------------------------------------
    async def test_expiring_a_lease_on_a_completed_task_leaves_it_completed(self):
        """The replay-side guard: a ledger already holding 1,204 of these
        events must not resurrect every completed task on the next boot."""
        task = await self._claimed()
        await self.store.transition(task.id, IN_PROGRESS)
        await self.store.transition(task.id, COMPLETED)
        await self.store.expire_lease(task.id)
        self.assertEqual((await self.store.get(task.id)).status, COMPLETED)

    async def test_expiring_a_lease_on_abandoned_work_does_return_it_to_the_queue(self):
        """The behaviour that was right all along, and must survive the
        fix: a worker that died mid-task frees its work."""
        task = await self._claimed()
        await self.store.expire_lease(task.id)
        refreshed = await self.store.get(task.id)
        self.assertEqual(refreshed.status, AVAILABLE)
        self.assertIsNone(refreshed.lease)

    async def test_the_scan_skips_finished_tasks_entirely(self):
        done = await self._claimed()
        await self.store.transition(done.id, IN_PROGRESS)
        await self.store.transition(done.id, COMPLETED)
        abandoned = await self._claimed()

        scheduler = Scheduler(self.store, _Bus(), self.clock, source="planning", lease_seconds=600.0)
        self.clock.advance(10_000.0)  # every lease is now long past
        await scheduler.scan_leases()

        self.assertEqual((await self.store.get(done.id)).status, COMPLETED)
        self.assertEqual((await self.store.get(abandoned.id)).status, AVAILABLE)

    async def test_a_completed_task_is_never_offered_as_ready_again(self):
        task = await self._claimed()
        await self.store.transition(task.id, IN_PROGRESS)
        await self.store.transition(task.id, COMPLETED)
        await self.store.expire_lease(task.id)
        self.assertEqual([t.id for t in self.store.ready(limit=50)], [])

    async def test_the_whole_loop_cannot_run_twice(self):
        """The exact sixteen-round cycle seen in the real ledger:
        claimed -> started -> completed -> lease_expired -> claimed."""
        task = await self._claimed()
        await self.store.transition(task.id, IN_PROGRESS)
        await self.store.transition(task.id, COMPLETED)

        scheduler = Scheduler(self.store, _Bus(), self.clock, source="planning", lease_seconds=600.0)
        for _ in range(16):
            self.clock.advance(700.0)
            await scheduler.scan_leases()
            await scheduler.dispatch_ready()

        self.assertEqual((await self.store.get(task.id)).status, COMPLETED)
        claims = [e for e in await self.ledger.read(f"task:{task.id}") if e.type == "claimed"]
        self.assertEqual(len(claims), 1, "the task was claimed more than once after finishing")


if __name__ == "__main__":
    unittest.main()
