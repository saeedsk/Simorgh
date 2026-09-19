"""A booted Kernel owns one telemetry store and puts it on every
Context; shutdown flushes it; `[telemetry] enabled = false` hands out
the no-op. Boots only bus, ledger and guardian, to stay fast."""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pytest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message, validate
from simorgh.contracts.protocols import NULL_TELEMETRY
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.telemetry import TelemetryService
from tests.simorgh.helpers import FakeClock

pytestmark = [pytest.mark.integration]


def _kernel(tmp: str, **telemetry) -> Kernel:
    raw = {"runtime": {"data_dir": tmp, "subsystems": ["bus", "ledger"]}}
    if telemetry:
        raw["telemetry"] = telemetry
    return Kernel(LoadedConfig(raw, None), secrets=EnvSecretStore({}), clock=FakeClock())


class ABootedKernel(unittest.IsolatedAsyncioTestCase):
    async def test_every_context_carries_the_kernels_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _kernel(tmp, flush_interval_s=3600.0)
            await kernel.boot()
            try:
                self.assertIsInstance(kernel.telemetry, TelemetryService)
                self.assertEqual(kernel.telemetry.path, Path(tmp) / "telemetry.sqlite")
                services = kernel._supervisor.services  # noqa: SLF001
                self.assertIn("guardian", services)
                ctx = services["guardian"].service._ctx  # noqa: SLF001
                self.assertIs(ctx.telemetry, kernel.telemetry)
                self.assertIs(services["ledger"].service._ctx.telemetry, kernel.telemetry)  # noqa: SLF001
                async with ctx.telemetry.span("decide", trace_id="t1") as root:
                    async with ctx.telemetry.span("rule", trace_id="t1"):
                        pass
                ctx.telemetry.sample("probe", 1)
                rows = await ctx.telemetry.query("t1")
                self.assertEqual([r["name"] for r in rows], ["decide", "rule"])
                self.assertEqual(rows[1]["parent_id"], root.span_id)
                async with ctx.telemetry.span("unflushed", trace_id="t2"):
                    pass
            finally:
                await kernel.shutdown()
            conn = sqlite3.connect(str(Path(tmp) / "telemetry.sqlite"))
            try:  # shutdown flushed the span nobody queried
                self.assertEqual(conn.execute("SELECT name FROM spans WHERE trace_id='t2'").fetchall(), [("unflushed",)])
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM samples WHERE series='probe'").fetchone()[0], 1)
            finally:
                conn.close()

    async def test_the_sleep_tick_runs_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _kernel(tmp, maintain_after_start_s=0, maintain_min_interval_s=0)
            await kernel.boot()
            try:
                before = kernel.telemetry.counters["maintain_runs"]
                await kernel.bus.publish(validate(Message.new(
                    topics.SYSTEM_TICK_SLEEP, source="kernel", payload={"window_seconds": 1.0},
                    clock=FakeClock().now)))
                for _ in range(200):
                    if kernel.telemetry.counters["maintain_runs"] > before:
                        break
                    await asyncio.sleep(0.01)
                self.assertGreater(kernel.telemetry.counters["maintain_runs"], before)
            finally:
                await kernel.shutdown()

    async def test_disabled_telemetry_hands_out_the_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _kernel(tmp, enabled=False)
            await kernel.boot()
            try:
                self.assertIsNone(kernel.telemetry)
                ctx = kernel._supervisor.services["guardian"].service._ctx  # noqa: SLF001
                self.assertIs(ctx.telemetry, NULL_TELEMETRY)
            finally:
                await kernel.shutdown()
            self.assertFalse((Path(tmp) / "telemetry.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
