"""Stage 1 item 3: a curiosity tick's breakdown is a telemetry sample."""

import unittest
from types import SimpleNamespace

from simorgh.growth.explore.service import Service


class _Telemetry:
    def __init__(self):
        self.samples = []

    def sample(self, series, value, ts=None):
        self.samples.append((series, value))

    async def series(self, *a, **k):
        return []


class ATickIsASample(unittest.IsolatedAsyncioTestCase):
    async def test_a_tick_goes_to_the_store_not_the_ledger(self):
        svc = Service()
        appended = []

        async def _append(stream, kind, payload):
            appended.append(stream)

        telemetry = _Telemetry()
        svc._ctx = SimpleNamespace(telemetry=telemetry)  # noqa: SLF001
        svc._append = _append  # noqa: SLF001
        svc._now = lambda: 100.0  # noqa: SLF001
        await svc._record_tick(skipped_reason="autonomy_paused")  # noqa: SLF001
        self.assertEqual(appended, [])
        self.assertEqual(telemetry.samples[0][0], "growth.explore.tick")
        self.assertEqual(telemetry.samples[0][1]["skipped_reason"], "autonomy_paused")
