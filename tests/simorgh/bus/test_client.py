"""BusClient behaviors on the memory backend: validation on publish,
policy hook, request/reply + timeout + late reply, explicit nack,
backpressure, stopping, and the produced message contracts."""

import asyncio
import unittest

from simorgh.bus.api import BusClosed, BusTimeout, PolicyViolation
from simorgh.bus.config import Config
from simorgh.contracts import ContractError, topics, validate
from simorgh.contracts.envelope import Message

from tests.simorgh.helpers import make_message

from .harness import Harness, run


class RefusePolicy:
    def check_subscribe(self, source, pattern):
        if source == "curiosity" and pattern.startswith("action"):
            raise PolicyViolation("no")

    def check_publish(self, source, type, payload):
        if type == topics.ACTION_APPROVED and source != "guardian":
            raise PolicyViolation("no")


class TestPublishValidation(unittest.TestCase):
    @run
    async def test_malformed_message_is_rejected_in_the_producer(self):
        async with Harness("memory") as h:
            bus = h.client("planning")
            bad = make_message(topics.TASK_STARTED, source="planning").with_(priority=42)
            with self.assertRaises(ContractError):
                await bus.publish(bad)
            self.assertEqual(bus.metrics.counters.get("published", 0), 0)

    @run
    async def test_unknown_type_is_rejected(self):
        async with Harness("memory") as h:
            bus = h.client("planning")
            with self.assertRaises(ContractError):
                await bus.publish(Message.new("nope.nothing", source="planning", payload={}) if False else
                                  make_message(topics.TASK_STARTED).with_(type="nope.nothing"))

    @run
    async def test_policy_refuses_publish_and_subscribe(self):
        async with Harness("memory") as h:
            bus = h.client("curiosity", policy=RefusePolicy())
            with self.assertRaises(PolicyViolation):
                await bus.subscribe("action.#", lambda m: asyncio.sleep(0))
            with self.assertRaises(PolicyViolation):
                await bus.publish(make_message(topics.ACTION_APPROVED, source="curiosity"))

    @run
    async def test_new_fills_source_trace_and_causation(self):
        async with Harness("memory") as h:
            bus = h.client("planning")
            first = bus.new(topics.TASK_STARTED, {"task_id": "t1", "worker_id": "w1"}, partition_key="task:t1")
            second = bus.new(topics.TASK_STEP, {"task_id": "t1", "step_no": 1, "phase": "gather", "summary": "x"}, caused_by=first)
            self.assertEqual(first.source, "planning")
            self.assertEqual(second.trace_id, first.trace_id)
            self.assertEqual(second.causation_id, first.id)
            self.assertEqual(second.partition_key, "task:t1")
            validate(first); validate(second)


class TestRequestReply(unittest.TestCase):
    @run
    async def test_round_trip_and_correlation(self):
        async with Harness("memory") as h:
            planning, worker = h.client("planning"), h.client("orchestration")

            async def on_claim(m):
                await planning.reply(m, type=topics.TASK_CLAIM_REPLY,
                                     payload={"granted": True, "lease_until": 5.0, "task": {"id": m.payload["task_id"]}})

            await planning.subscribe(topics.TASK_CLAIM, on_claim, group="planning")
            req = make_message(topics.TASK_CLAIM, source="orchestration",
                               payload={"task_id": "t1", "worker_id": "w1"}, partition_key="task:t1")
            reply = await worker.request(req, timeout=2.0)
            self.assertEqual(reply.type, topics.TASK_CLAIM_REPLY)
            self.assertEqual(reply.correlation_id, req.id)
            self.assertTrue(reply.payload["granted"])
            self.assertGreater(worker.metrics.p50_request_ms(), 0.0)

    @run
    async def test_timeout_raises_and_late_reply_is_dropped(self):
        async with Harness("memory") as h:
            planning, worker = h.client("planning"), h.client("orchestration")
            held: list = []

            async def slow(m):
                held.append(m)

            await planning.subscribe(topics.TASK_CLAIM, slow, group="planning")
            req = make_message(topics.TASK_CLAIM, source="orchestration", payload={"task_id": "t1", "worker_id": "w1"})
            with self.assertRaises(BusTimeout):
                await worker.request(req, timeout=0.05)
            await h.settle(0.02)
            await planning.reply(held[0], type=topics.TASK_CLAIM_REPLY, payload={"granted": False, "lease_until": 0.0, "task": {}})
            await h.settle(0.03)
            self.assertEqual(worker.metrics.counters.get("late_replies", 0), 1)

    @run
    async def test_request_or_error_synthesizes_the_error_reply(self):
        async with Harness("memory") as h:
            worker = h.client("orchestration")
            req = make_message(topics.TASK_CLAIM, source="orchestration", payload={"task_id": "t1", "worker_id": "w1"})
            reply = await worker.request_or_error(req, timeout=0.02)
            self.assertEqual(reply.type, topics.TASK_CLAIM_REPLY)
            self.assertFalse(reply.payload["ok"])
            self.assertEqual(reply.payload["error"]["code"], "timeout")
            validate(reply)

    @run
    async def test_reply_without_request_is_an_error(self):
        async with Harness("memory") as h:
            planning = h.client("planning")
            with self.assertRaises(ValueError):
                await planning.reply(make_message(topics.TASK_CLAIM), type=topics.TASK_CLAIM_REPLY, payload={})


class TestExplicitNackAndStop(unittest.TestCase):
    @run
    async def test_explicit_nack_redelivers_after_retry_after(self):
        async with Harness("memory") as h:
            bus = h.client("execution")
            seen: list = []

            async def handler(m):
                seen.append(m.id)
                if len(seen) == 1:
                    await bus.nack(m, retry_after=1.0)

            await bus.subscribe(topics.ACTION_APPROVED, handler, group="execution")
            await bus.publish(make_message(topics.ACTION_APPROVED, source="execution"))
            await h.settle(0.03)
            self.assertEqual(len(seen), 1)
            h.clock.advance(1.5)
            await h.settle(0.05)
            self.assertEqual(len(seen), 2)
            self.assertEqual(bus.metrics.counters["explicit_nack"], 1)

    @run
    async def test_stopping_refuses_non_system_publishes(self):
        async with Harness("memory") as h:
            bus = h.client("planning")
            bus.set_state("stopping")
            with self.assertRaises(BusClosed):
                await bus.publish(make_message(topics.TASK_STARTED, source="planning"))
            await bus.publish(make_message(topics.SYSTEM_HEALTH, source="planning"))  # system.* still allowed

    @run
    async def test_stop_fails_pending_requests(self):
        async with Harness("memory") as h:
            worker = h.client("orchestration")
            req = make_message(topics.TASK_CLAIM, source="orchestration", payload={"task_id": "t1", "worker_id": "w1"})
            task = asyncio.create_task(worker.request(req, timeout=5.0))
            await h.settle(0.02)
            await worker.stop()
            with self.assertRaises(BusClosed):
                await task


class TestBackpressure(unittest.TestCase):
    @run
    async def test_publish_awaits_while_a_group_is_full_and_priority_9_bypasses(self):
        cfg = Config(max_queue_depth=2, metrics_interval_seconds=0)
        async with Harness("memory", config=cfg) as h:
            bus = h.client("planning")
            gate = asyncio.Event()

            async def slow(m):
                await gate.wait()

            await bus.subscribe("task.*", slow, group="workers", max_inflight=1)
            for _ in range(3):
                await bus.publish(make_message(topics.TASK_AVAILABLE, source="planning"))
            await h.settle(0.02)
            blocked = asyncio.create_task(bus.publish(make_message(topics.TASK_AVAILABLE, source="planning")))
            await h.settle(0.03)
            self.assertFalse(blocked.done())
            self.assertGreater(bus.metrics.counters["backpressure_waits"], 0)
            await bus.publish(make_message(topics.SYSTEM_PAUSE, source="planning"))  # priority 9: never waits
            gate.set()
            await asyncio.wait_for(blocked, 2.0)


class TestProducedContracts(unittest.TestCase):
    @run
    async def test_metrics_and_health_payloads_validate(self):
        async with Harness("memory") as h:
            bus = h.client("planning")
            got: list = []

            async def catch(m):
                got.append(m)

            await bus.subscribe("system.*", catch)
            body = await bus.emit_metrics()
            self.assertEqual(body["subsystem"], "bus")
            await bus._emit_health("degraded", "test")
            await h.settle(0.03)
            types = {m.type for m in got}
            self.assertEqual(types, {topics.SYSTEM_METRICS, topics.SYSTEM_HEALTH})
            for m in got:
                validate(m)


if __name__ == "__main__":
    unittest.main()
