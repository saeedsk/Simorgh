"""Consolidation had never run.

Its only caller is the `system.tick.sleep` handler, and the Kernel's
sleep loop waits a full `sleep_every_s` -- six hours -- before its FIRST
tick. So any session shorter than that pruned nothing, and
`DEFAULT_KEEP_PER_KIND`'s 2,000-per-kind steady state, which everything
downstream assumes (including the cost of a recall), has never actually
existed.

The Ledger hit this identical bug on 2026-09-07: retention said `trace:`
streams expire after 7 days and 190,865 of them were still on disk,
because the same loop was the only thing that ran compaction. It was
fixed with `[ledger] compact_after_start_s`. This is the same fix, for
the same reason, one subsystem over (observer, 2026-09-10).
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.protocols import Context
from simorgh.memory.config import Config
from simorgh.memory.service import Service
from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock


class _Logger:
    def info(self, *a, **k): ...
    def warning(self, *a, **k): ...
    def error(self, *a, **k): ...
    def debug(self, *a, **k): ...


class ConsolidationRunsWithoutWaitingSixHoursTestCase(unittest.IsolatedAsyncioTestCase):
    async def _service(self, **config) -> Service:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        clock = FakeClock()
        ledger = make_ledger({"backend": "memory"}, clock=clock)
        await ledger.start()
        self.addAsyncCleanup(ledger.stop)
        backend = make_backend(BusConfig(backend="memory"), clock=clock.now)
        bus = make_client(backend, source="memory", ledger=ledger, clock=clock.now)
        await bus.start()
        self.addAsyncCleanup(bus.stop)
        service = Service(config=Config(**config))
        await service.start(Context(
            name="memory", instance_id="", run_id="t", mode="single", bus=bus, ledger=ledger,
            config={}, secrets={}, clock=clock, logger=_Logger(),
            data_dir=Path(tmp.name) / "data"))
        self.addAsyncCleanup(service.stop)
        return service

    async def test_a_first_pass_is_scheduled_at_boot(self):
        service = await self._service(consolidate_after_start_s=0.01)
        self.assertIsNotNone(service._first_consolidation)  # noqa: SLF001

    async def test_the_first_pass_actually_runs(self):
        service = await self._service(consolidate_after_start_s=0.01)
        ran = asyncio.Event()
        original = service._consolidate  # noqa: SLF001

        async def _watch(*, window):
            ran.set()
            return await original(window=window)

        service._consolidate = _watch  # noqa: SLF001
        service._first_consolidation.cancel()  # noqa: SLF001
        service._first_consolidation = asyncio.create_task(  # noqa: SLF001
            service._consolidate_after_start())  # noqa: SLF001
        await asyncio.wait_for(ran.wait(), timeout=5.0)

    async def test_it_can_be_switched_off(self):
        service = await self._service(consolidate_after_start_s=0.0)
        self.assertIsNone(service._first_consolidation)  # noqa: SLF001

    async def test_stopping_before_it_fires_does_not_raise(self):
        service = await self._service(consolidate_after_start_s=3600.0)
        await service.stop()
        self.assertIsNone(service._first_consolidation)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
