"""Stage 1 item 3: a metrics snapshot is a telemetry sample, not a ledger event."""

import unittest

from simorgh.kernel.metrics import HISTORY_SERIES, MetricsHistoryWriter, MetricsTable
from tests.simorgh.helpers import FakeClock


class _Telemetry:
    def __init__(self):
        self.samples = []

    def sample(self, series, value, ts=None):
        self.samples.append((series, value, ts))


class _Ledger:
    def __init__(self):
        self.appends = []

    async def append(self, stream, event):
        self.appends.append(stream)


class AMetricsSnapshotIsASample(unittest.IsolatedAsyncioTestCase):
    async def _writer(self, telemetry):
        table = MetricsTable()
        table.per_subsystem["process"] = {"counters": {}, "gauges": {"threads": 7}}
        ledger = _Ledger()
        writer = MetricsHistoryWriter(ledger=ledger, clock=FakeClock(), metrics=table, interval_s=5,
                                      telemetry=telemetry)
        await writer.snapshot_once()
        return ledger

    async def test_with_a_store_it_is_a_sample(self):
        telemetry = _Telemetry()
        ledger = await self._writer(telemetry)
        self.assertEqual(ledger.appends, [])
        series, value, _ = telemetry.samples[0]
        self.assertEqual(series, HISTORY_SERIES)
        self.assertEqual(value["metrics"]["process"]["gauges"]["threads"], 7)

    async def test_without_one_it_is_the_ledger_stream(self):
        ledger = await self._writer(None)
        self.assertEqual(ledger.appends, ["metrics:history"])
