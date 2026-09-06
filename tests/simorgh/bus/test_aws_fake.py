"""The aws backend driven end-to-end against a fake boto3 session --
never the network (docs/blueprint/subsystems/01-bus.md section 5.5)."""

import asyncio
import time
import unittest

from simorgh.bus.api import BackendUnavailable
from simorgh.bus.backends import aws as aws_module
from simorgh.bus.backends.aws import AwsBackend
from simorgh.bus.client import BusClient
from simorgh.bus.config import Config
from simorgh.contracts import topics

from tests.simorgh.helpers import make_message

from .fakes import FakeBoto3Session, FakeLedger, wait_until
from .harness import run


def _backend(session, clock=time.time, **kw):
    return AwsBackend(clock=clock, region="us-east-1", topic_prefix="t", queue_prefix="q",
                      max_deliveries=kw.get("max_deliveries", 3), wait_time_seconds=0, session=session)


class TestAwsBackend(unittest.TestCase):
    def test_missing_boto3_is_a_clear_config_time_error(self):
        saved = aws_module.boto3
        aws_module.boto3 = None
        try:
            with self.assertRaises(BackendUnavailable):
                AwsBackend(clock=time.time, region="r", topic_prefix="t", queue_prefix="q")
        finally:
            aws_module.boto3 = saved

    @run
    async def test_event_fan_out_and_competing_group_over_sns_sqs(self):
        session = FakeBoto3Session(time.time)
        backend = _backend(session)
        ledger = FakeLedger()
        a = BusClient(backend, source="memory", ledger=ledger, config=Config(metrics_interval_seconds=0))
        b = BusClient(backend, source="reflection", ledger=ledger, config=Config(metrics_interval_seconds=0))
        w1 = BusClient(backend, source="orchestration", ledger=ledger, config=Config(metrics_interval_seconds=0))
        w2 = BusClient(backend, source="orchestration", ledger=ledger, config=Config(metrics_interval_seconds=0))
        counts = {"a": 0, "b": 0, "w": 0}

        def make(name):
            async def h(m):
                counts[name] += 1
            return h

        await backend.start()
        await a.subscribe("task.*", make("a"))
        await b.subscribe("task.*", make("b"))
        await w1.subscribe("task.*", make("w"), group="workers")
        await w2.subscribe("task.*", make("w"), group="workers")
        for i in range(6):
            await a.publish(make_message(topics.TASK_STARTED, source="memory", partition_key=f"task:t{i}"))
        await wait_until(lambda: counts["a"] == 6 and counts["b"] == 6 and counts["w"] == 6, timeout=5)
        self.assertEqual(len(session.sqs.deleted), 18)
        await backend.stop()

    @run
    async def test_request_reply_via_inbox_queue(self):
        session = FakeBoto3Session(time.time)
        backend = _backend(session)
        planning = BusClient(backend, source="planning", config=Config(metrics_interval_seconds=0))
        worker = BusClient(backend, source="orchestration", config=Config(metrics_interval_seconds=0))

        async def on_claim(m):
            await planning.reply(m, type=topics.TASK_CLAIM_REPLY, payload={"granted": True, "lease_until": 1.0, "task": {}})

        await backend.start()
        await planning.subscribe(topics.TASK_CLAIM, on_claim, group="planning")
        req = make_message(topics.TASK_CLAIM, source="orchestration", payload={"task_id": "t1", "worker_id": "w1"})
        reply = await worker.request(req, timeout=5.0)
        self.assertTrue(reply.payload["granted"])
        await backend.stop()

    @run
    async def test_crash_retries_via_visibility_then_dead_letters(self):
        now = [1000.0]
        session = FakeBoto3Session(lambda: now[0])
        backend = _backend(session, clock=lambda: now[0])
        ledger = FakeLedger()
        bus = BusClient(backend, source="execution", ledger=ledger, clock=lambda: now[0], config=Config(metrics_interval_seconds=0))
        attempts: list = []

        async def h(m):
            attempts.append(1)
            raise RuntimeError("boom")

        await backend.start()
        await bus.subscribe(topics.ACTION_APPROVED, h, group="execution")
        await bus.publish(make_message(topics.ACTION_APPROVED, source="execution", partition_key="action:a1"))
        for _ in range(6):
            await asyncio.sleep(0.05)
            now[0] += 100.0
        await wait_until(lambda: len(attempts) >= 3, timeout=5)
        await asyncio.sleep(0.05)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(len(ledger.streams[f"dead:{topics.ACTION_APPROVED}"]), 1)
        self.assertGreaterEqual(len(session.sqs.visibility_changes), 2)
        await backend.stop()


if __name__ == "__main__":
    unittest.main()
