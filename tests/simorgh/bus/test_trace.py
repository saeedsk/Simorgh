import asyncio
import unittest

from simorgh.bus.trace import TraceWriter
from simorgh.contracts import topics

from tests.simorgh.helpers import make_message

from .fakes import FakeLedger
from .harness import run


class TestTraceWriter(unittest.TestCase):
    def test_sample_rate_exact_then_pattern_then_default(self):
        tw = TraceWriter(FakeLedger(), sample={"system.tick.second": 0.0, "_inbox.#": 0.0, "task.*": 0.5})
        self.assertEqual(tw.sample_rate(topics.SYSTEM_TICK_SECOND), 0.0)
        self.assertEqual(tw.sample_rate("_inbox.x.y"), 0.0)
        self.assertEqual(tw.sample_rate(topics.TASK_STEP), 0.5)
        self.assertEqual(tw.sample_rate(topics.ACTION_PROPOSED), 1.0)

    def test_fractional_sampling_uses_the_rng(self):
        tw = TraceWriter(FakeLedger(), sample={"task.*": 0.5}, rng=lambda: 0.9)
        self.assertFalse(tw.should_trace(make_message(topics.TASK_STEP)))
        tw = TraceWriter(FakeLedger(), sample={"task.*": 0.5}, rng=lambda: 0.1)
        self.assertTrue(tw.should_trace(make_message(topics.TASK_STEP)))

    @run
    async def test_writes_to_the_trace_stream_with_the_message_id_as_idempotency_key(self):
        ledger = FakeLedger()
        tw = TraceWriter(ledger)
        m = make_message(topics.TASK_STEP)
        tw.write(m)
        await tw.flush()
        events = ledger.streams[f"trace:{m.trace_id}"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].idempotency_key, m.id)
        self.assertEqual(events[0].payload["type"], topics.TASK_STEP)

    @run
    async def test_ledger_outage_buffers_then_replays(self):
        ledger = FakeLedger()
        tw = TraceWriter(ledger)
        ledger.fail = True
        m1 = make_message(topics.TASK_STEP)
        tw.write(m1)
        await tw.flush()
        self.assertTrue(tw.degraded)
        self.assertEqual(tw.failed, 1)
        ledger.fail = False
        m2 = make_message(topics.TASK_STEP, trace_id=m1.trace_id)
        tw.write(m2)
        await tw.flush()
        self.assertFalse(tw.degraded)
        self.assertEqual(len(ledger.streams[f"trace:{m1.trace_id}"]), 2)

    @run
    async def test_oversized_payload_becomes_a_blob_ref(self):
        ledger = FakeLedger()
        tw = TraceWriter(ledger, blob_threshold=64)
        m = make_message(topics.UI_NOTICE, payload={"level": "info", "text": "x" * 500, "source": "t"})
        ref = await tw.write_blob_body(m)
        self.assertTrue(ref and ref.startswith("blob:"))
        self.assertIn(ref, ledger.blobs)
        self.assertIsNone(await tw.write_blob_body(make_message(topics.TASK_STARTED)))

    @run
    async def test_queue_overflow_drops_with_a_counter_instead_of_blocking(self):
        tw = TraceWriter(FakeLedger(), queue_size=2)
        for _ in range(5):
            tw.write(make_message(topics.TASK_STEP))
        self.assertEqual(tw.dropped, 3)


if __name__ == "__main__":
    unittest.main()
