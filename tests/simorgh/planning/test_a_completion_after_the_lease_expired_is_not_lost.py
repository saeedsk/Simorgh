"""Work that really finished must be recorded, even if its lease ran out
first.

The counterpart to `test_completed_tasks_stay_completed.py`: that one
stops an expired lease from resurrecting a task that is already
finished. This one is the same race in the other direction, and it was
still open.

`Scheduler.scan_leases` returns a task whose lease has run out to the
queue -- correctly, because the usual cause is a dead worker. But a
worker can also be alive and simply slow: `task.step` only renews the
lease when a tool call *completes*, and while `Worker._heartbeat_loop`
renews mid-step, any renewal that is dropped (a busy bus, a Planning
restart, a `local-multi` worker partitioned for a moment) has the same
effect. The worker then finishes and publishes `task.completed` for a
task that Planning has already put back in `available`.

`available -> completed` was not in the transition table, so
`TaskStore.transition` raised `ValueError: illegal transition available
-> completed` inside `_on_task_completed`; the bus swallowed it. The
finished result was dropped, nothing was recorded, and the task sat on
the queue to be claimed and run again from scratch.

Measured 2026-09-10 on a real Kernel with real Planning and two
competing workers, 3 seconds of work under a 1-second lease with
renewals suppressed:

    ledger claims total=5 (per-task max=3)
    ledger completions total=0        <- five real runs, nothing recorded
    worker-side runs total=5   ran-twice=['fd7d95572187']
    never run=['ad30bbd62bc8']
    final statuses={'available': 3, 'claimed': 1}

Zero of four tasks finished, in a run where the workers did the work
five times over.
"""

from __future__ import annotations

import unittest

from simorgh.ledger.factory import make_ledger
from simorgh.planning.model import AVAILABLE, COMPLETED, FAILED, IN_PROGRESS
from simorgh.planning.store import TaskStore
from tests.simorgh.helpers import FakeClock


class ACompletionThatLostTheRaceTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.store = TaskStore(self.ledger, self.clock)
        await self.store.rebuild()

    async def _slow_worker_loses_its_lease(self) -> str:
        task = await self.store.create(kind="patch", description="a long one", origin="human")
        await self.store.transition(task.id, AVAILABLE)
        await self.store.claim(task.id, "w1", 1.0)
        await self.store.transition(task.id, IN_PROGRESS)
        self.clock.advance(2.0)  # one step outlives the whole lease
        await self.store.expire_lease(task.id)
        self.assertEqual((await self.store.get(task.id)).status, AVAILABLE)
        return task.id

    async def test_the_completion_is_recorded_not_dropped(self):
        task_id = await self._slow_worker_loses_its_lease()
        await self.store.transition(task_id, COMPLETED, note="done, it just took a while")
        task = await self.store.get(task_id)
        self.assertEqual(task.status, COMPLETED)
        self.assertEqual(task.note, "done, it just took a while")

    async def test_the_completed_task_is_no_longer_offered_to_anybody(self):
        """The point of recording it: it leaves the queue. Before, it
        stayed `available` and was claimed and re-run indefinitely."""
        task_id = await self._slow_worker_loses_its_lease()
        await self.store.transition(task_id, COMPLETED, note="done")
        self.assertEqual([t.id for t in self.store.ready()], [])
        claim = await self.store.claim(task_id, "w2", 600.0)
        self.assertFalse(claim.granted)
        self.assertEqual(claim.reason, "not_available")

    async def test_the_completion_keeps_no_lease_and_survives_a_replay(self):
        """`with_status` drops the lease on a terminal status, and the
        `lease_expired` guard keeps a replayed expiry from re-opening
        it -- the two halves of the 2026-09-07 resurrection fix still
        hold on this path."""
        task_id = await self._slow_worker_loses_its_lease()
        await self.store.transition(task_id, COMPLETED, note="done")
        self.assertIsNone((await self.store.get(task_id)).lease)
        rebuilt = TaskStore(self.ledger, self.clock)
        await rebuilt.rebuild()
        self.assertEqual(rebuilt.index.tasks[task_id].status, COMPLETED)

    async def test_a_late_failure_report_does_not_kill_a_requeued_task(self):
        """The deliberate asymmetry: a completion that lost the race is
        real work worth keeping; a failure that lost it would only
        destroy a task somebody has legitimately handed back."""
        task_id = await self._slow_worker_loses_its_lease()
        with self.assertRaises(ValueError):
            await self.store.transition(task_id, FAILED, note="too late to matter")
        self.assertEqual((await self.store.get(task_id)).status, AVAILABLE)


if __name__ == "__main__":
    unittest.main()
