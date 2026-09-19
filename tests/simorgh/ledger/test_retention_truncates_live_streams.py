"""Retention truncates a long-lived stream that is still being written,
whatever its name (found writing ledger's CONTRACT.md, 2026-09-19: any
name with a colon was treated as per-id and only ever deleted whole once
idle, so `metrics:history` and friends were never trimmed)."""

import unittest

from simorgh.contracts.envelope import Event
from simorgh.ledger.backends.memory import InMemoryBackend
from simorgh.ledger.compaction import RetentionPolicy, run_compaction

DAY = 86400.0


async def _fill(backend, stream, days, now):
    for i in range(days):
        ts = now - (days - 1 - i) * DAY
        await backend.append(Event(stream=stream, type="sample", ts=ts, trace_id="", causation_id=None, payload={"i": i}),
                             expected_seq=None)


class LiveStreamsAreTrimmed(unittest.IsolatedAsyncioTestCase):
    async def test_twenty_daily_samples_under_a_seven_day_window_keep_seven(self):
        backend = InMemoryBackend()
        now = 100 * DAY
        await _fill(backend, "metrics:history", 20, now)
        report = await run_compaction(backend, RetentionPolicy.parse({}), now=now)
        remaining = await backend.read("metrics:history", from_seq=1, limit=None)
        self.assertEqual(report.events_truncated, 12)
        self.assertEqual(len(remaining), 8)   # today and the seven days before it
        self.assertTrue(all(e.ts >= now - 7 * DAY for e in remaining))

    async def test_an_idle_per_id_stream_is_deleted_whole(self):
        backend = InMemoryBackend()
        now = 100 * DAY
        await backend.append(Event(stream="trace:abc", type="x", ts=now - 5 * DAY, trace_id="", causation_id=None,
                                   payload={}), expected_seq=None)
        report = await run_compaction(backend, RetentionPolicy.parse({}), now=now)
        self.assertEqual(report.streams_deleted, 1)

    async def test_a_forever_stream_is_left_alone(self):
        backend = InMemoryBackend()
        now = 100 * DAY
        await _fill(backend, "learn:outcomes", 20, now)
        await run_compaction(backend, RetentionPolicy.parse({}), now=now)
        self.assertEqual(len(await backend.read("learn:outcomes", from_seq=1, limit=None)), 20)
