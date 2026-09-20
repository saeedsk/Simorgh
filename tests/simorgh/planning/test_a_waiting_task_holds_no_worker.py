"""Stage 7 item 5: a task that waits holds no worker.

Sleeping inside the session was the obvious way to wait, and it costs a
worker and a model context for the whole wait -- ten minutes of waiting
is ten minutes in which nothing else runs. A waiting task is parked
instead: its lease goes, and it comes back when its moment or its event
arrives, with everything it had."""

import unittest

from simorgh.ledger.backends.memory import InMemoryBackend as LedgerMemoryBackend
from simorgh.ledger.client import LedgerClient
from simorgh.planning.model import AVAILABLE, COMPLETED, WAITING
from simorgh.planning.store import TaskStore

from tests.simorgh.helpers import FakeClock
from tests.simorgh.orchestration.harness import run


async def _store():
    clock = FakeClock()
    ledger = LedgerClient(LedgerMemoryBackend(), clock=clock)
    await ledger.start()
    return TaskStore(ledger, clock), clock


class AWaitingTask(unittest.TestCase):
    @run
    async def test_it_keeps_no_lease_and_comes_back_when_woken(self):
        store, clock = await _store()
        task = await store.create(kind="research", description="watch for the delivery", origin="human")
        await store.transition(task.id, AVAILABLE)
        claimed = await store.claim(task.id, "w1", 60.0)
        self.assertIsNotNone(claimed.task.lease)

        parked = await store.wait(task.id, until=clock.now() + 600.0, why="the van is not here yet")
        self.assertEqual(parked.status, WAITING)
        self.assertIsNone(parked.lease, "a waiting task holds no worker")
        self.assertEqual(store.waiting()[0].id, task.id)

        woken = await store.wake(task.id, why="the time came")
        self.assertEqual(woken.status, AVAILABLE)
        self.assertIsNone(woken.wake_at)
        self.assertEqual(store.waiting(), [])

    @run
    async def test_waking_something_that_is_not_waiting_does_nothing(self):
        store, _ = await _store()
        task = await store.create(kind="research", description="d", origin="human")
        self.assertIsNone(await store.wake(task.id))

    @run
    async def test_a_finished_task_never_waits(self):
        store, _ = await _store()
        task = await store.create(kind="research", description="d", origin="human")
        await store.transition(task.id, AVAILABLE)
        await store.transition(task.id, COMPLETED)
        self.assertIsNone(await store.wait(task.id, until=1.0))

    @run
    async def test_an_event_wait_remembers_what_it_is_waiting_for(self):
        store, _ = await _store()
        task = await store.create(kind="research", description="d", origin="human")
        await store.transition(task.id, AVAILABLE)
        parked = await store.wait(task.id, event="world.home.situation_changed")
        self.assertEqual(parked.wake_on, "world.home.situation_changed")
        self.assertIsNone(parked.wake_at, "an event wait has no deadline of its own")


if __name__ == "__main__":
    unittest.main()
