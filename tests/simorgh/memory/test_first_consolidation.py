"""Consolidation has to run in a session that ends the same day.

`DEFAULT_KEEP_PER_KIND` describes a steady state of 2,000 records per
kind, and `retrieve`'s cost is a function of exactly that number. But
until 2026-09-10 the only thing that called `run_consolidation` was
`system.tick.sleep`, and the Kernel's sleep loop (`kernel/scheduler.py`
`_sleep_loop`) waits a full `sleep_every_s` -- 6 hours by default,
`kernel/api.py` -- before its FIRST tick, then skips it entirely if the
system is not RUNNING at that instant. Every session shorter than six
hours therefore pruned nothing and flagged no contradictions: memory
only grew, and the steady state the retrieval budget assumed never
existed. The Ledger hit the identical bug (190,865 expired streams on
disk) and fixed it with `[ledger] compact_after_start_s`.
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
from simorgh.memory.config import Config as MemoryConfig
from simorgh.memory.service import Service
from simorgh.memory.store import TOMBSTONE_STREAM
from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class FirstConsolidationTestCase(unittest.IsolatedAsyncioTestCase):
    async def _service(self, config: MemoryConfig, **kwargs) -> Service:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        clock = FakeClock()
        ledger = make_ledger({"backend": "memory"}, clock=clock)
        await ledger.start()
        bus = make_client(make_backend(BusConfig(backend="memory"), clock=clock),
                          source="memory", ledger=ledger, clock=clock)
        await bus.start()
        self.ledger, self.bus, self.clock = ledger, bus, clock
        ctx = Context(name="memory", instance_id="", run_id="test", mode="single",
                      bus=bus, ledger=ledger, config={}, secrets={}, clock=clock,
                      logger=_Logger(), data_dir=Path(self._tmp.name) / "data")
        service = Service(config=config, **kwargs)
        await service.start(ctx)
        self.addCleanup(lambda: asyncio.get_event_loop().run_until_complete(bus.stop()))
        return service

    async def _tombstoned(self) -> int:
        events = await self.ledger.read(TOMBSTONE_STREAM)
        return sum(len(e.payload.get("refs", [])) for e in events)

    async def test_pruning_happens_without_waiting_for_the_first_sleep_tick(self):
        """No `system.tick.sleep` is ever published here -- that is the
        point. The real one is six hours away."""
        service = await self._service(
            MemoryConfig(half_life_seconds=1_000_000.0, consolidate_after_start_s=0.01),
            keep_per_kind={"semantic": 3},
        )
        try:
            for i in range(10):
                await service.engine.store(kind="semantic", content=f"fact {i}",
                                           tags=[f"t{i}"], source_ref="", confidence=1.0)
            self.assertEqual(await self._tombstoned(), 0)
            await asyncio.sleep(0.25)
            self.assertEqual(await self._tombstoned(), 7,
                             "consolidation never ran, so nothing was pruned")
        finally:
            await service.stop()

    async def test_the_first_pass_can_be_switched_off(self):
        service = await self._service(
            MemoryConfig(half_life_seconds=1_000_000.0, consolidate_after_start_s=0.0),
            keep_per_kind={"semantic": 3},
        )
        try:
            for i in range(10):
                await service.engine.store(kind="semantic", content=f"fact {i}",
                                           tags=[f"t{i}"], source_ref="", confidence=1.0)
            await asyncio.sleep(0.25)
            self.assertEqual(await self._tombstoned(), 0)
        finally:
            await service.stop()

    async def test_stopping_before_the_first_pass_does_not_raise_or_leak(self):
        service = await self._service(
            MemoryConfig(consolidate_after_start_s=60.0), keep_per_kind={"semantic": 3})
        task = service._first_consolidation
        self.assertIsNotNone(task)
        await service.stop()
        self.assertTrue(task.cancelled() or task.done())

    async def test_the_sleep_tick_still_consolidates(self):
        service = await self._service(
            MemoryConfig(half_life_seconds=1_000_000.0, consolidate_after_start_s=0.0),
            keep_per_kind={"semantic": 3},
        )
        try:
            for i in range(10):
                await service.engine.store(kind="semantic", content=f"fact {i}",
                                           tags=[f"t{i}"], source_ref="", confidence=1.0)
            done: asyncio.Future = asyncio.get_running_loop().create_future()

            async def _on(message: Message) -> None:
                if not done.done():
                    done.set_result(message)

            sub = await self.bus.subscribe(topics.MEMORY_CONSOLIDATED, _on)
            try:
                await self.bus.publish(Message.new(
                    topics.SYSTEM_TICK_SLEEP, source="test", payload={"window_seconds": 3600.0}))
                await asyncio.wait_for(done, timeout=5.0)
            finally:
                await sub.unsubscribe()
            self.assertEqual(await self._tombstoned(), 7)
        finally:
            await service.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
