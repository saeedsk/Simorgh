"""`simorgh.kernel.metrics`: `MetricsTable`/`StatusServer` (the existing
aggregation) plus the two observe-tier additions (02-system-architecture.md
section 6.2) -- `process_gauges`/`ProcessMetricsPublisher` (OS-level
resource usage, previously tracked nowhere) and `MetricsHistoryWriter`
(a "value over time" view independent of trace sampling)."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.bus.enforcement import ReservedTopologyPolicy
from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.config import Config as BusConfig
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.ledger.backends.memory import InMemoryBackend
from simorgh.ledger.client import LedgerClient
from simorgh.kernel.metrics import (
    HISTORY_EVENT_TYPE,
    HISTORY_STREAM,
    MetricsHistoryWriter,
    MetricsTable,
    ProcessMetricsPublisher,
    process_gauges,
)
from tests.simorgh.helpers import FakeClock


async def _pump(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def _make_bus_and_ledger(clock: FakeClock):
    ledger = LedgerClient(InMemoryBackend())
    await ledger.start()
    backend = make_backend(BusConfig(), clock=clock)
    await backend.start()
    bus = make_client(backend, source="kernel", ledger=ledger, clock=clock, policy=ReservedTopologyPolicy())
    return backend, bus, ledger


class TestMetricsTable(unittest.TestCase):
    def test_record_keeps_the_latest_counters_and_gauges_per_subsystem(self):
        table = MetricsTable()
        table.record(Message.new(
            topics.SYSTEM_METRICS, source="bus",
            payload={"subsystem": "bus", "counters": {"published": 1}, "gauges": {"queue_depth.x": 2}},
        ))
        self.assertEqual(table.per_subsystem["bus"]["counters"], {"published": 1})
        self.assertEqual(table.per_subsystem["bus"]["gauges"], {"queue_depth.x": 2})


class TestProcessGauges(unittest.TestCase):
    def test_returns_a_dict_with_threads_and_cpu_count_at_minimum(self):
        gauges = process_gauges()
        self.assertIn("threads", gauges)
        self.assertIn("cpu_count", gauges)
        self.assertGreaterEqual(gauges["threads"], 1)

    def test_never_raises_regardless_of_platform_support(self):
        # `resource`/`getloadavg` are POSIX-only; the function must degrade
        # to a smaller-but-valid dict rather than propagate, on any platform.
        try:
            process_gauges()
        except Exception as exc:  # noqa: BLE001
            self.fail(f"process_gauges() raised {exc!r}")


class TestProcessMetricsPublisher(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.backend, self.bus, self.ledger = await _make_bus_and_ledger(self.clock)
        self.received: list[Message] = []

        async def _collect(message: Message) -> None:
            self.received.append(message)

        self._sub = await self.bus.subscribe(topics.SYSTEM_METRICS, _collect)

    async def asyncTearDown(self):
        await self._sub.unsubscribe()
        await self.backend.stop()
        await self.ledger.stop()

    async def test_publish_once_emits_a_system_metrics_event_for_subsystem_process(self):
        publisher = ProcessMetricsPublisher(bus=self.bus, clock=self.clock, interval_s=5.0)
        await publisher.publish_once()
        await _pump()
        process_events = [m for m in self.received if m.payload.get("subsystem") == "process"]
        self.assertEqual(len(process_events), 1)
        self.assertIn("threads", process_events[0].payload["gauges"])
        self.assertEqual(process_events[0].payload["counters"], {})

    async def test_start_stop_runs_the_periodic_loop_without_leaking_the_task(self):
        publisher = ProcessMetricsPublisher(bus=self.bus, clock=self.clock, interval_s=1.0)
        await publisher.start()
        await _pump(50)
        await publisher.stop()
        process_events = [m for m in self.received if m.payload.get("subsystem") == "process"]
        self.assertGreaterEqual(len(process_events), 1)
        self.assertIsNone(publisher._task)  # noqa: SLF001


class TestMetricsHistoryWriter(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.backend, self.bus, self.ledger = await _make_bus_and_ledger(self.clock)
        self.table = MetricsTable()

    async def asyncTearDown(self):
        await self.backend.stop()
        await self.ledger.stop()

    async def test_snapshot_once_is_a_noop_when_nothing_has_reported_yet(self):
        writer = MetricsHistoryWriter(ledger=self.ledger, clock=self.clock, metrics=self.table, interval_s=30.0)
        await writer.snapshot_once()
        events = await self.ledger.read(HISTORY_STREAM)
        self.assertEqual(events, [])

    async def test_snapshot_once_appends_a_deep_copy_of_the_metrics_table(self):
        self.table.record(Message.new(
            topics.SYSTEM_METRICS, source="bus",
            payload={"subsystem": "bus", "counters": {"published": 3}, "gauges": {"queue_depth.x": 1}},
        ))
        writer = MetricsHistoryWriter(ledger=self.ledger, clock=self.clock, metrics=self.table, interval_s=30.0)
        await writer.snapshot_once()
        events = await self.ledger.read(HISTORY_STREAM)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, HISTORY_EVENT_TYPE)
        self.assertEqual(events[0].payload["metrics"]["bus"]["counters"], {"published": 3})
        # Mutating the live table afterward must never retroactively change
        # an already-recorded snapshot -- history is exactly that, history.
        self.table.per_subsystem["bus"]["counters"]["published"] = 999
        self.assertEqual(events[0].payload["metrics"]["bus"]["counters"], {"published": 3})

    async def test_start_stop_runs_the_periodic_loop_and_writes_multiple_snapshots(self):
        self.table.record(Message.new(
            topics.SYSTEM_METRICS, source="orchestration",
            payload={"subsystem": "orchestration", "counters": {}, "gauges": {"workers.busy": 0}},
        ))
        writer = MetricsHistoryWriter(ledger=self.ledger, clock=self.clock, metrics=self.table, interval_s=1.0)
        await writer.start()
        await _pump(50)
        await writer.stop()
        events = await self.ledger.read(HISTORY_STREAM)
        self.assertGreaterEqual(len(events), 1)
        self.assertIsNone(writer._task)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
