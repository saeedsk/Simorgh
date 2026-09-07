import asyncio
import unittest

from .helpers import FakeBus, make_context, make_event
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.ledger.backends.memory import InMemoryBackend
from simorgh.ledger.client import LedgerClient
from simorgh.ledger.config import Config
from simorgh.ledger.service import Service
from tests.simorgh.helpers import FakeClock


class TestLedgerServiceHealth(unittest.IsolatedAsyncioTestCase):
    async def test_down_before_the_client_is_started(self) -> None:
        client = LedgerClient(InMemoryBackend())
        service = Service(client)

        health = await service.health()

        self.assertEqual(health.status, "down")

    async def test_ok_once_started(self) -> None:
        clock = FakeClock()
        client = LedgerClient(InMemoryBackend(), clock=clock)
        service = Service(client)
        ctx = make_context(bus=FakeBus(), ledger=client, clock=clock)

        await service.start(ctx)
        health = await service.health()

        self.assertEqual(health.status, "ok")
        await service.stop()

    async def test_down_after_a_recorded_backend_error(self) -> None:
        clock = FakeClock()
        client = LedgerClient(InMemoryBackend(), clock=clock)
        service = Service(client)
        ctx = make_context(bus=FakeBus(), ledger=client, clock=clock)
        await service.start(ctx)
        client.last_error = "disk full (ENOSPC)"

        health = await service.health()

        self.assertEqual(health.status, "down")
        self.assertIn("ENOSPC", health.detail)
        await service.stop()


class TestLedgerServiceSleepTick(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.clock = FakeClock()
        self.client = LedgerClient(InMemoryBackend(), clock=self.clock)
        self.bus = FakeBus()
        self.service = Service(self.client, Config(retention={"activity": "1s"}))
        self.ctx = make_context(bus=self.bus, ledger=self.client, clock=self.clock)
        await self.service.start(self.ctx)

    async def asyncTearDown(self) -> None:
        await self.service.stop()

    async def test_sleep_tick_runs_compaction_and_publishes_metrics(self) -> None:
        await self.client.append("activity", make_event("activity", ts=self.clock.now()))
        self.clock.advance(10)

        message = Message.new(
            topics.SYSTEM_TICK_SLEEP, source="kernel", payload={"window_seconds": 10.0}, clock=self.clock
        )
        await self.service._on_sleep(message)

        self.assertEqual(self.service.compactions, 1)
        published_types = [m.type for m in self.bus.published]
        self.assertIn(topics.SYSTEM_METRICS, published_types)
        metrics = next(m for m in self.bus.published if m.type == topics.SYSTEM_METRICS)
        self.assertEqual(metrics.payload["subsystem"], "ledger")
        self.assertIn("appends", metrics.payload["counters"])

    async def test_a_malformed_tick_is_ignored_not_fatal(self) -> None:
        bad = Message.new(topics.SYSTEM_TICK_SLEEP, source="kernel", payload={}, clock=self.clock)

        await self.service._on_sleep(bad)  # missing required window_seconds

        self.assertEqual(self.service.compactions, 0)

    async def test_a_compaction_that_removes_nothing_still_publishes_metrics_without_a_ledger_event(self) -> None:
        message = Message.new(
            topics.SYSTEM_TICK_SLEEP, source="kernel", payload={"window_seconds": 1.0}, clock=self.clock
        )

        await self.service._on_sleep(message)

        self.assertEqual(await self.client.head("ledger:compaction"), 0)
        self.assertTrue(any(m.type == topics.SYSTEM_METRICS for m in self.bus.published))


if __name__ == "__main__":
    unittest.main()


class TestCompactionRunsWithoutWaitingSixHours(unittest.IsolatedAsyncioTestCase):
    """Live-caught 2026-09-07: retention already expired `trace:` streams
    after 7 days, and 190,865 of them (1.8GB) were still on disk. The only
    caller of compaction was the `system.tick.sleep` handler, and the
    Kernel's sleep loop waits a full `sleep_every_s` -- six hours -- before
    its *first* tick. Every session shorter than that compacted nothing,
    so in practice compaction had never run once."""

    async def _service(self, **cfg):
        clock = FakeClock()
        client = LedgerClient(InMemoryBackend(), clock=clock)
        service = Service(client, Config(**cfg))
        await service.start(make_context(bus=FakeBus(), ledger=client, clock=clock))
        return service

    async def test_a_pass_runs_shortly_after_start(self):
        service = await self._service(compact_after_start_s=0.01)
        for _ in range(100):
            if service.compactions:
                break
            await asyncio.sleep(0.01)
        await service.stop()
        self.assertGreaterEqual(service.compactions, 1)

    async def test_zero_disables_the_start_pass(self):
        service = await self._service(compact_after_start_s=0.0)
        await asyncio.sleep(0.05)
        await service.stop()
        self.assertEqual(service.compactions, 0)

    async def test_stopping_before_the_delay_elapses_cancels_it_cleanly(self):
        service = await self._service(compact_after_start_s=30.0)
        await service.stop()  # must not hang for 30s, must not raise
        self.assertEqual(service.compactions, 0)


if __name__ == "__main__":
    unittest.main()
