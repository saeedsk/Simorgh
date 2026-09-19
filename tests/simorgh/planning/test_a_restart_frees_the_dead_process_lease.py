"""A restart in single mode frees the lease the dead process held.

2026-09-19, the kill-and-resume drill: after SIGKILL the new process sat
idle until the old 600 s lease ran out, because nothing knew its holder
was gone. In single mode Planning boots before any worker, so every lease
it finds belongs to a dead process.
"""
import unittest
from types import SimpleNamespace

from simorgh.ledger.factory import make_ledger
from simorgh.planning.model import AVAILABLE, IN_PROGRESS
from simorgh.planning.service import Service
from simorgh.planning.store import TaskStore
from tests.simorgh.helpers import FakeClock


class _Log:
    def info(self, *a, **k):
        pass


class ARestartFreesTheDeadLease(unittest.IsolatedAsyncioTestCase):
    async def _held_task(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        store = TaskStore(self.ledger, self.clock)
        await store.rebuild()
        task = await store.create(kind="patch", description="write notes.py", origin="human", initial_status=AVAILABLE)
        await store.claim(task.id, "orchestration-0", 600.0)
        await store.transition(task.id, IN_PROGRESS)
        return task.id

    async def _reboot(self, mode: str):
        store = TaskStore(self.ledger, self.clock)
        await store.rebuild()
        svc = Service()
        svc._store = store  # noqa: SLF001
        released = await svc._release_dead_leases(SimpleNamespace(mode=mode, logger=_Log()))  # noqa: SLF001
        return store, released

    async def test_single_mode_offers_the_task_again_at_once(self):
        task_id = await self._held_task()
        store, released = await self._reboot("single")
        self.assertEqual(released, 1)
        task = await store.get(task_id)
        self.assertEqual(task.status, AVAILABLE)
        self.assertIsNone(task.lease)

    async def test_local_multi_leaves_a_live_worker_alone(self):
        task_id = await self._held_task()
        store, released = await self._reboot("local-multi")
        self.assertEqual(released, 0)
        self.assertEqual((await store.get(task_id)).status, IN_PROGRESS)


if __name__ == "__main__":
    unittest.main()
