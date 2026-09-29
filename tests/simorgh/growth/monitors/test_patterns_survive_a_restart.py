"""The pattern miner's window survives a restart.

2026-09-29: the miner was fed only by live events, so every boot emptied
it and the night's diagnose saw only what happened since -- on a ledger
holding 138 outcomes from the past week, a night found nothing. It now
reads its window back from `learn:outcomes` when it starts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import Context
from simorgh.growth.monitors.config import Config as MonitorsConfig
from simorgh.growth.monitors.service import Service
from simorgh.ledger.factory import make_ledger

from tests.simorgh.helpers import FakeClock

from .test_service_stall import _Logger


class PatternsSurviveARestart(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="growth", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.ctx = Context(name="growth", instance_id="", run_id="test", mode="single", bus=self.bus,
                           ledger=self.ledger, config={}, secrets={}, clock=self.clock, logger=_Logger(),
                           data_dir=Path(self._tmp.name) / "data")

    async def asyncTearDown(self) -> None:
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _record(self, task_type: str, succeeded: bool, ts: float) -> None:
        await self.ledger.append("learn:outcomes", Event(
            stream="learn:outcomes", type="outcome", ts=ts, trace_id="t", causation_id=None,
            payload={"task_type": task_type, "succeeded": succeeded, "task_id": "t", "verdict": "x"}))

    async def test_the_window_is_read_back_and_older_outcomes_are_not(self):
        now = self.clock.now()
        for _ in range(3):
            await self._record("patch:simorgh/growth", False, now - 3600)
        for _ in range(3):
            await self._record("research", False, now - 3 * 86400)      # outside a day's window
        service = Service(MonitorsConfig(reflect_after_start_s=0.0))
        await service.start(self.ctx)
        try:
            mined = {p.task_type for p in service._patterns.mine(now)}  # noqa: SLF001
        finally:
            await service.stop()
        self.assertEqual(mined, {"patch:simorgh/growth"})


if __name__ == "__main__":
    unittest.main()
