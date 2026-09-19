"""The telemetry store: spans and samples in one SQLite file, batched
writes off the loop, retention and downsampling (stage 1 item 1)."""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pytest

from simorgh.contracts.protocols import Telemetry
from simorgh.telemetry import Config, TelemetryService, TelemetryStore
from tests.simorgh.helpers import FakeClock

pytestmark = [pytest.mark.contract]

DAY = 86_400.0


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "telemetry.sqlite"
        self.clock = FakeClock()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def _service(self, **config) -> TelemetryService:
        config.setdefault("maintain_after_start_s", 0)
        service = TelemetryService(self.path, config=Config(**config), clock=self.clock)
        await service.start()
        self.addAsyncCleanup(service.stop)
        return service

    def _raw(self, sql: str) -> list[tuple]:
        conn = sqlite3.connect(str(self.path))
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()


class TheFileAndItsTables(_Base):
    async def test_one_wal_file_with_both_tables_and_their_indexes(self):
        await self._service()
        self.assertEqual(self._raw("PRAGMA journal_mode")[0][0], "wal")
        columns = [r[1] for r in self._raw("PRAGMA table_info(spans)")]
        self.assertEqual(columns, ["trace_id", "span_id", "parent_id", "name", "start", "end", "status", "attrs_json"])
        self.assertEqual([r[1] for r in self._raw("PRAGMA table_info(samples)")], ["series", "ts", "value_json"])
        indexes = {r[0]: r[1] for r in self._raw("SELECT name, sql FROM sqlite_master WHERE type='index'")}
        self.assertIn("ON spans(trace_id)", indexes["spans_trace"])
        self.assertIn("ON samples(series, ts)", indexes["samples_series_ts"])

    async def test_the_service_conforms_to_the_protocol(self):
        self.assertIsInstance(await self._service(), Telemetry)


class Spans(_Base):
    async def test_ten_thousand_spans_then_one_trace_is_one_query(self):
        service = await self._service()
        for t in range(100):
            for s in range(100):
                async with service.span(f"step-{s}", trace_id=f"trace-{t}", parent_id="root"):
                    self.clock.advance(0.001)
        rows = await service.query("trace-42")
        self.assertEqual(len(rows), 100)
        self.assertEqual({r["trace_id"] for r in rows}, {"trace-42"})
        self.assertEqual([r["name"] for r in rows], [f"step-{s}" for s in range(100)])  # oldest start first
        self.assertEqual(self._raw("SELECT COUNT(*) FROM spans")[0][0], 10_000)
        plan = " ".join(str(r) for r in self._raw(
            "EXPLAIN QUERY PLAN SELECT * FROM spans WHERE trace_id='trace-42'"))
        self.assertIn("spans_trace", plan)

    async def test_a_span_records_start_end_status_and_attrs(self):
        service = await self._service()
        start = self.clock.now()
        async with service.span("think", trace_id="t1", attrs={"model": "m"}) as span:
            self.clock.advance(2.5)
            span.set("tokens", 12)
        [row] = await service.query("t1")
        self.assertEqual(row["name"], "think")
        self.assertEqual(row["span_id"], span.span_id)
        self.assertEqual((row["start"], row["end"]), (start, start + 2.5))
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["attrs"], {"model": "m", "tokens": 12})

    async def test_nested_spans_record_their_parent(self):
        service = await self._service()
        async with service.span("turn", trace_id="t1") as root:
            async with service.span("think", trace_id="t1") as think:
                async with service.span("tool", trace_id="t1") as tool:
                    pass
            async with service.span("speak", trace_id="t1") as speak:
                pass
            async with service.span("explicit", trace_id="t1", parent_id="given") as explicit:
                pass
            async with service.span("other-trace", trace_id="t2") as other:
                pass
        parents = {r["span_id"]: r["parent_id"] for r in await service.query("t1")}
        self.assertIsNone(parents[root.span_id])
        self.assertEqual(parents[think.span_id], root.span_id)
        self.assertEqual(parents[tool.span_id], think.span_id)
        self.assertEqual(parents[speak.span_id], root.span_id)
        self.assertEqual(parents[explicit.span_id], "given")
        [row] = await service.query("t2")
        self.assertIsNone(row["parent_id"])  # a different trace never inherits
        self.assertEqual(row["span_id"], other.span_id)

    async def test_a_child_task_inherits_the_open_span(self):
        service = await self._service()
        async with service.span("turn", trace_id="t1") as root:
            async def child():
                async with service.span("stt", trace_id="t1") as span:
                    return span
            span = await asyncio.create_task(child())
        self.assertEqual(span.parent_id, root.span_id)

    async def test_an_exception_marks_the_span_error_and_is_reraised(self):
        service = await self._service()
        with self.assertRaises(ValueError):
            async with service.span("tool", trace_id="t1"):
                raise ValueError("boom")
        [row] = await service.query("t1")
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["attrs"]["error"], "ValueError: boom")

    async def test_cancellation_marks_the_span_cancelled(self):
        service = await self._service()

        async def slow():
            async with service.span("wait", trace_id="t1"):
                await asyncio.sleep(10)

        task = asyncio.create_task(slow())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        [row] = await service.query("t1")
        self.assertEqual(row["status"], "cancelled")

    async def test_an_attr_json_cannot_encode_does_not_raise(self):
        service = await self._service()
        async with service.span("x", trace_id="t1", attrs={"obj": object(), "nan": float("nan")}):
            pass
        [row] = await service.query("t1")
        self.assertEqual(row["status"], "ok")
        self.assertIsInstance(row["attrs"], (dict, str))


class Batching(_Base):
    async def test_rows_are_written_by_the_timer_without_a_flush(self):
        service = await self._service(flush_interval_s=0.02)
        service.sample("cpu", 0.5)
        async with service.span("a", trace_id="t1"):
            pass
        self.assertEqual(self._raw("SELECT COUNT(*) FROM samples")[0][0], 0)  # buffered, not yet written
        for _ in range(100):
            await asyncio.sleep(0.01)
            if service.counters["flushes"]:
                break
        self.assertEqual(self._raw("SELECT COUNT(*) FROM samples")[0][0], 1)
        self.assertEqual(self._raw("SELECT COUNT(*) FROM spans")[0][0], 1)
        self.assertEqual(service.counters["flushes"], 1)  # both rows in one batch

    async def test_a_full_batch_is_written_before_the_timer(self):
        service = await self._service(flush_interval_s=60.0, batch_rows=10)
        for i in range(10):
            service.sample("s", i)
        for _ in range(100):
            await asyncio.sleep(0.01)
            if service.counters["flushes"]:
                break
        self.assertEqual(self._raw("SELECT COUNT(*) FROM samples")[0][0], 10)

    async def test_stop_flushes_everything_buffered(self):
        service = TelemetryService(self.path, config=Config(flush_interval_s=3600.0, batch_rows=10**6,
                                                            maintain_after_start_s=0), clock=self.clock)
        await service.start()
        for i in range(2_000):
            service.sample("s", i)
            async with service.span("op", trace_id=f"t{i % 7}"):
                pass
        self.assertEqual(service.counters["flushes"], 0)
        await service.stop()
        store = TelemetryStore(self.path)
        store.open()
        try:
            self.assertEqual(store.counts(), {"spans": 2_000, "samples": 2_000})
            self.assertEqual([r["value"] for r in store.samples("s")], list(range(2_000)))
        finally:
            store.close()
        self.assertEqual(service.counters["dropped"], 0)

    async def test_a_row_after_stop_is_dropped_and_counted(self):
        service = await self._service()
        await service.stop()
        service.sample("s", 1)
        self.assertEqual(service.counters["dropped"], 1)

    async def test_the_buffer_is_bounded(self):
        service = TelemetryService(self.path, config=Config(max_buffer_rows=5, maintain_after_start_s=0),
                                   clock=self.clock)  # not started: nothing drains it
        for i in range(8):
            service.sample("s", i)
        self.assertEqual(service.counters["dropped"], 3)
        await service.start()
        await service.stop()
        store = TelemetryStore(self.path)
        store.open()
        try:
            self.assertEqual([r["value"] for r in store.samples("s")], [3, 4, 5, 6, 7])  # oldest dropped
        finally:
            store.close()


class Retention(_Base):
    async def test_retention_removes_rows_past_their_age(self):
        service = await self._service()
        now = self.clock.now()
        self.clock._now = now - 15 * DAY  # noqa: SLF001
        async with service.span("old", trace_id="t-old"):
            pass
        service.sample("s", "too-old", ts=now - 8 * DAY)
        self.clock._now = now - 13 * DAY  # noqa: SLF001
        async with service.span("kept", trace_id="t-kept"):
            pass
        self.clock._now = now  # noqa: SLF001
        service.sample("s", "fresh", ts=now - 60)
        removed = await service.maintain()
        self.assertEqual(removed["spans"], 1)
        self.assertEqual(removed["samples"], 1)
        self.assertEqual(await service.query("t-old"), [])
        self.assertEqual(len(await service.query("t-kept")), 1)
        self.assertEqual([r["value"] for r in await service.series("s")], ["fresh"])

    async def test_downsampling_keeps_one_sample_per_minute_per_series(self):
        service = await self._service()
        now = self.clock.now()
        base = (now - 2 * DAY) // 60 * 60  # a minute boundary two days back
        for minute in range(3):
            for second in range(0, 60, 5):  # 12 per minute
                service.sample("cpu", minute * 100 + second, ts=base + minute * 60 + second)
                service.sample("mem", -(minute * 100 + second), ts=base + minute * 60 + second)
        for second in range(0, 60, 5):  # recent: untouched
            service.sample("cpu", second, ts=now - 600 + second)
        removed = await service.maintain()
        self.assertEqual(removed["downsampled"], 2 * 3 * 11)
        old_cpu = await service.series("cpu", until=now - DAY)
        self.assertEqual([r["value"] for r in old_cpu], [55, 155, 255])  # the last of each minute
        self.assertEqual(len(await service.series("mem", until=now - DAY)), 3)
        self.assertEqual(len(await service.series("cpu", since=now - DAY)), 12)
        again = await service.maintain()
        self.assertEqual(again["downsampled"], 0)  # idempotent

    async def test_the_sleep_tick_pass_is_rate_limited(self):
        wall = [1000.0]
        service = TelemetryService(self.path, config=Config(maintain_after_start_s=0, maintain_min_interval_s=600),
                                   clock=self.clock, monotonic=lambda: wall[0])
        await service.start()
        self.addAsyncCleanup(service.stop)
        self.assertIsNotNone(await service.on_sleep_tick())
        wall[0] += 10
        self.assertIsNone(await service.on_sleep_tick())
        wall[0] += 600
        self.assertIsNotNone(await service.on_sleep_tick())
        self.assertEqual(service.counters["maintain_runs"], 2)

    async def test_one_pass_runs_shortly_after_start(self):
        service = await self._service(maintain_after_start_s=0.01)
        for _ in range(100):
            await asyncio.sleep(0.01)
            if service.counters["maintain_runs"]:
                break
        self.assertEqual(service.counters["maintain_runs"], 1)


class TheConfig(unittest.TestCase):
    def test_defaults_match_the_plan(self):
        c = Config()
        self.assertTrue(c.enabled)
        self.assertEqual(c.flush_interval_s, 0.25)
        self.assertEqual((c.span_retention_days, c.sample_retention_days, c.downsample_after_days), (14, 7, 1))
        self.assertEqual(c.downsample_bucket_s, 60)

    def test_every_key_is_read_from_the_section(self):
        section = {"enabled": False, "flush_interval_s": 1.0, "batch_rows": 7, "max_buffer_rows": 9,
                   "span_retention_days": 2, "sample_retention_days": 3, "downsample_after_days": 0.5,
                   "downsample_bucket_s": 300, "maintain_after_start_s": 5, "maintain_min_interval_s": 6}
        c = Config.from_mapping(section)
        for key, value in section.items():
            self.assertEqual(getattr(c, key), value, key)

    def test_a_negative_value_is_refused(self):
        with self.assertRaises(ValueError):
            Config.from_mapping({"span_retention_days": -1})


if __name__ == "__main__":
    unittest.main()
