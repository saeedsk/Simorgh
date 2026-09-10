"""A task that is ready must be offered without waiting for the system
to go idle.

`Scheduler.dispatch_ready` was called from exactly two places: the
moment a task was created (`_announce_created`), and the IDLE tick,
which the Kernel only fires after `idle_threshold_s` (10s) of nobody
typing and then no more often than `idle_tick_cooldown_s` (3s). Nothing
else re-offered anything -- not a blocked task coming back
(`_reconsider_blocked`), not a lease expiring (`Scheduler.scan_leases`),
not a dependency being satisfied, not a resume after a pause. And a
dispatch offers only the top 5, so the sixth task of any burst was never
offered by its own creation either.

Measured with a real Kernel, real Planning and three competing workers,
2026-09-10 (20 human tasks, 0.05s of work each):

    nobody typing:   6 ran in the first 0.3s, the other 14 took 16.2s
                     more -- in batches of 5, spaced by the idle
                     threshold and its cooldown, with every worker idle
                     in between.
    typing every 2s: the idle tick NEVER fired. 7 tasks ran; **13 of
                     the 20 were never offered to anybody** in 40
                     seconds and sat in `available` forever, with three
                     idle workers.

Two seconds of typing is ordinary chat use, so the second line is the
live case, not the exotic one. The whole backlog stops moving the moment
a human is at the keyboard -- which is the same defect the 2026-09-07
"offer a NEW task immediately, not only on the idle tick" fix was
written for, closed then only for the one task being created.

The fix is one call on the second tick, which already runs every second
and already scans leases. Its cost is bounded by the dispatch limit --
at most five `task.available` messages a second, whatever the size of
the backlog -- and the Ledger record of a re-offer inside one generation
is deduped on `{id}:{updated_at}`. The bus message itself IS repeated,
deliberately: the memory bus is not durable, so repeating the offer is
what repairs one that was dropped. Measured against the same harness,
the total offer count over the 40-second run barely moved (86 before,
99 after) while the tasks actually run went from 7 to 20.
"""

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
from simorgh.planning.model import AVAILABLE, BLOCKED
from simorgh.planning.service import Service

from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class BacklogIsOfferedEverySecondTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(self.backend, source="planning", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.watcher = make_client(self.backend, source="orchestration", ledger=self.ledger,
                                   clock=self.clock.now)
        await self.watcher.start()
        self.ctx = Context(
            name="planning", instance_id="", run_id="test", mode="single", bus=self.bus,
            ledger=self.ledger, config={}, secrets={}, clock=self.clock, logger=_Logger(),
            data_dir=Path(self._tmp.name) / "data")
        self.service = Service()
        await self.service.start(self.ctx)
        self.offered: list[str] = []

        async def _on_available(message: Message) -> None:
            self.offered.append(message.payload["task_id"])

        self._sub = await self.watcher.subscribe(topics.TASK_AVAILABLE, _on_available)

    async def asyncTearDown(self):
        await self._sub.unsubscribe()
        await self.service.stop()
        await self.watcher.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _pump(self, n: int = 40) -> None:
        for _ in range(n):
            await asyncio.sleep(0)

    async def _tick_second(self) -> None:
        await self.bus.publish(Message.new(
            topics.SYSTEM_TICK_SECOND, source="kernel", payload={"n": 1}, clock=self.clock.now))
        await self._pump()

    async def _make_available(self, description: str) -> str:
        task = await self.service._store.create(  # noqa: SLF001 -- the queue's state is the subject
            kind="patch", description=description, origin="human")
        await self.service._store.transition(task.id, AVAILABLE)  # noqa: SLF001
        return task.id

    async def test_the_sixth_task_of_a_burst_is_offered_on_the_next_second(self):
        """A dispatch offers five. Before the fix the sixth waited for an
        idle tick -- i.e. for the human to stop typing for ten seconds."""
        ids = [await self._make_available(f"task number {i}") for i in range(6)]
        self.offered.clear()
        await self._tick_second()
        self.assertEqual(len(set(self.offered)), 5)  # the queue's own limit
        for task_id in list(set(self.offered)):  # five workers take them
            await self.service._store.claim(task_id, "w1", 600.0)  # noqa: SLF001
        self.offered.clear()
        await self._tick_second()
        self.assertEqual(set(self.offered), {ids[5]},
                         "the sixth task was never offered without an idle tick")

    async def test_a_tick_never_offers_more_than_the_dispatch_limit(self):
        """The cost ceiling of running this every second: five messages,
        whatever the size of the backlog. (A re-offer inside one
        generation is deliberate, not a bug -- the memory bus is not
        durable, so repeating the offer is what repairs a lost one; the
        Ledger dedupes the record of it on `{id}:{updated_at}`.)"""
        for i in range(40):
            await self._make_available(f"a backlog item numbered {i}")
        self.offered.clear()
        await self._tick_second()
        self.assertEqual(len(self.offered), 5)

    async def test_a_task_whose_lease_expired_is_re_offered_without_an_idle_tick(self):
        task_id = await self._make_available("work a crashed worker abandoned")
        await self.service._store.claim(task_id, "w1", 1.0)  # noqa: SLF001
        self.clock.advance(2.0)  # the worker died; the lease runs out
        self.offered.clear()
        await self._tick_second()  # scan_leases makes it available again
        self.assertIn(task_id, self.offered,
                      "an expired lease returned the task to the queue and told nobody")

    async def test_a_blocked_task_coming_back_is_offered_without_an_idle_tick(self):
        task_id = await self._make_available("something verification refused")
        await self.service._store.claim(task_id, "w1", 600.0)  # noqa: SLF001
        await self.service._store.transition(task_id, BLOCKED, note="verification said no")  # noqa: SLF001
        self.clock.advance(self.service.config.blocked_retry_delay_seconds + 1.0)
        self.offered.clear()
        await self._tick_second()  # _reconsider_blocked makes it available again
        self.assertIn(task_id, self.offered,
                      "a blocked task was retried and never offered to a worker")


if __name__ == "__main__":
    unittest.main()
