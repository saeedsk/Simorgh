"""Sim's own ideas wait when the queue is full; a person's request does not.

The creator, 2026-09-10, looking at 330 queued tasks: "why would a
system schedule that many tasks -- shouldn't it wait until the backlog
drops, then add more?" Intake accepted every candidate unconditionally;
dedupe was the only brake. (Those particular 330 were an observer's test
data written into the live ledger by mistake -- but nothing would have
stopped Sim producing them itself.)
"""

from __future__ import annotations

import unittest

from simorgh.ledger.backends.memory import InMemoryBackend
from simorgh.ledger.client import LedgerClient
from simorgh.planning.intake import Intake
from simorgh.planning.store import TaskStore
from tests.simorgh.helpers import FakeClock


class BoundedBacklogTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = TaskStore(LedgerClient(InMemoryBackend(), source="test"), FakeClock())
        self.intake = Intake(self.store, dedupe_threshold=0.99, max_backlog=3)

    async def _fill(self, n: int, origin: str = "human"):
        for i in range(n):
            await self.store.create(kind="patch", description=f"real work {i}", origin=origin)

    async def test_an_autonomous_candidate_is_deferred_at_the_cap(self):
        await self._fill(3)
        result = await self.intake.on_candidate(kind="patch", description="an idea", subject=None,
                                                area="x", origin="curiosity")
        self.assertIsNone(result.task)
        self.assertIn("backlog full", result.deferred)
        self.assertEqual(self.intake.backlog(), 3, "nothing was added")

    async def test_below_the_cap_it_is_accepted(self):
        await self._fill(2)
        result = await self.intake.on_candidate(kind="patch", description="an idea", subject=None,
                                                area="x", origin="curiosity")
        self.assertIsNotNone(result.task)
        self.assertEqual(result.backlog, 2)

    async def test_a_persons_request_is_never_deferred(self):
        await self._fill(10)
        result = await self.intake.on_candidate(kind="patch", description="please fix it", subject=None,
                                                area="x", origin="human")
        self.assertIsNotNone(result.task)
        self.assertIsNone(result.deferred)
        self.assertEqual(result.backlog, 10, "but the reply says how deep the queue is")

    async def test_a_benchmark_case_is_never_deferred(self):
        await self._fill(10)
        result = await self.intake.on_candidate(kind="patch", description="case 1", subject=None,
                                                area="x", origin="benchmark")
        self.assertIsNotNone(result.task)

    async def test_finished_work_does_not_count(self):
        await self._fill(3)
        for t in list(self.store.index.tasks.values()):
            # `create` leaves a task pending; the legal road to done is
            # pending -> available -> claimed -> completed.
            await self.store.transition(t.id, "available")
            await self.store.transition(t.id, "claimed")
            await self.store.transition(t.id, "completed")
        result = await self.intake.on_candidate(kind="patch", description="an idea", subject=None,
                                                area="x", origin="curiosity")
        self.assertIsNotNone(result.task)

    async def test_reflection_patterns_stop_at_the_cap(self):
        await self._fill(3)
        created = await self.intake.on_patterns_found(patterns=[{"proposal": "fix a"}, {"proposal": "fix b"}])
        self.assertEqual(created, [])

    async def test_a_research_follow_up_waits_too(self):
        await self._fill(3)
        task = await self.intake.on_research_follow_up(research_task_id="r1", subject="s.py", description="do it")
        self.assertIsNone(task)

    async def test_zero_disables_the_cap(self):
        intake = Intake(self.store, dedupe_threshold=0.99, max_backlog=0)
        await self._fill(50)
        result = await intake.on_candidate(kind="patch", description="an idea", subject=None,
                                           area="x", origin="curiosity")
        self.assertIsNotNone(result.task)


if __name__ == "__main__":
    unittest.main()
