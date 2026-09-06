"""The same delivery-semantics scenarios and property tests against
`memory` and `sqlite` (docs/blueprint/subsystems/01-bus.md section 9):
ordering per partition, at-least-once under nack/crash, no cross-group
duplicates, priority-9 preemption, TTL, dead-letter with the Ledger
mirror, pause semantics, dedupe."""

import asyncio
import random
import unittest

from simorgh.contracts import topics, validate

from tests.simorgh.helpers import make_message

from .harness import Harness, for_each_backend


def _task_msg(i: int, key: str, priority: int = 5, ttl: float | None = None, clock=None):
    # `clock` matters only for TTL: `ts` must come from the same clock the
    # backend compares against (the harness's FakeClock), or `now > ts +
    # ttl` never fires -- real `time.time()` is a much later epoch than
    # FakeClock's fixed start, so an unset clock silently makes TTL never
    # expire regardless of how far the fake clock is advanced.
    return make_message(topics.TASK_STEP, source="orchestration", partition_key=key, priority=priority, ttl_seconds=ttl,
                        clock=clock, payload={"task_id": key.split(":")[1], "step_no": i, "phase": "act", "summary": f"s{i}"})


class TestParity(unittest.TestCase):
    @for_each_backend
    async def test_ordering_per_partition_key(self, h: Harness):
        bus = h.client("verification")
        seen: dict[str, list[int]] = {"task:a": [], "task:b": []}

        async def handler(m):
            await asyncio.sleep(random.uniform(0, 0.003))
            seen[m.partition_key].append(m.payload["step_no"])

        await bus.subscribe("task.*", handler, group="verifiers", max_inflight=8)
        order = []
        for i in range(30):
            key = "task:a" if i % 2 == 0 else "task:b"
            order.append((key, i))
            await bus.publish(_task_msg(i, key))
        await h.settle(0.6 if h.name == "sqlite" else 0.3)
        for key in seen:
            expected = [i for k, i in order if k == key]
            self.assertEqual(seen[key], expected, f"{h.name}: {key} out of order")

    @for_each_backend
    async def test_broadcast_reaches_every_subscription_and_competing_reaches_one(self, h: Harness):
        a, b = h.client("memory"), h.client("reflection")
        w1, w2 = h.client("orchestration"), h.client("orchestration")
        counts = {"a": 0, "b": 0, "w1": 0, "w2": 0}

        def make(name):
            async def handler(m):
                counts[name] += 1
            return handler

        await a.subscribe("task.*", make("a"))
        await b.subscribe("task.*", make("b"))
        await w1.subscribe("task.*", make("w1"), group="workers")
        await w2.subscribe("task.*", make("w2"), group="workers")
        for i in range(10):
            await a.publish(_task_msg(i, f"task:t{i}"))
        await h.settle(0.3)
        self.assertEqual(counts["a"], 10)
        self.assertEqual(counts["b"], 10)
        self.assertEqual(counts["w1"] + counts["w2"], 10)

    @for_each_backend
    async def test_no_concurrent_delivery_of_one_message_to_two_group_members(self, h: Harness):
        bus = h.client("orchestration")
        seen: dict[str, int] = {}

        async def handler(m):
            seen[m.id] = seen.get(m.id, 0) + 1
            await asyncio.sleep(0.002)

        await bus.subscribe("task.*", handler, group="workers")
        await h.client("orchestration").subscribe("task.*", handler, group="workers")
        for i in range(20):
            await bus.publish(_task_msg(i, f"task:t{i}"))
        await h.settle(0.4)
        self.assertEqual(len(seen), 20)
        self.assertTrue(all(n == 1 for n in seen.values()))

    @for_each_backend
    async def test_priority_9_is_delivered_before_queued_lower_priority(self, h: Harness):
        bus = h.client("interface")
        delivered: list[str] = []
        gate = asyncio.Event()

        async def handler(m):
            delivered.append(m.type)
            if len(delivered) == 1:
                await gate.wait()  # hold the first so the rest queue up

        await bus.subscribe("#", handler, group="all", max_inflight=1)
        for i in range(5):
            await bus.publish(_task_msg(i, f"task:t{i}"))
        await h.settle(0.05)
        await bus.publish(make_message(topics.SYSTEM_PAUSE, source="interface"))
        gate.set()
        await h.settle(0.3)
        self.assertEqual(delivered[0], topics.TASK_STEP)
        self.assertEqual(delivered[1], topics.SYSTEM_PAUSE, f"{h.name}: {delivered}")

    @for_each_backend
    async def test_ttl_expiry_discards_without_dead_lettering(self, h: Harness):
        bus = h.client("planning")
        seen: list = []

        async def handler(m):
            seen.append(m)

        await bus.subscribe("task.*", handler, group="workers")
        bus.set_state("paused")  # hold dequeue so the message can age
        await bus.publish(_task_msg(1, "task:t1", ttl=1.0, clock=h.clock))
        h.clock.advance(2.0)
        bus.set_state("running")
        await h.settle(0.2)
        self.assertEqual(seen, [])
        self.assertEqual(len(h.expired), 1)
        self.assertEqual(bus.metrics.counters.get("dead", 0), 0)

    @for_each_backend
    async def test_handler_crash_retries_then_dead_letters_to_the_ledger(self, h: Harness):
        bus = h.client("execution")
        attempts: list[int] = []

        async def handler(m):
            attempts.append(1)
            raise RuntimeError("boom")

        await bus.subscribe(topics.ACTION_APPROVED, handler, group="execution")
        await bus.publish(make_message(topics.ACTION_APPROVED, source="execution"))
        for _ in range(4):  # backoff 1s, 2s; max_deliveries=3
            await h.settle(0.15)
            h.clock.advance(3.0)
        await h.settle(0.2)
        self.assertEqual(len(attempts), 3, f"{h.name}: {attempts}")
        stream = f"dead:{topics.ACTION_APPROVED}"
        self.assertEqual(len(h.ledger.streams[stream]), 1)
        dead = h.ledger.streams[stream][0].payload
        self.assertEqual(dead["attempts"], 3)
        self.assertIn("boom", dead["last_error"])
        self.assertEqual(bus.metrics.counters["dead"], 1)

    @for_each_backend
    async def test_broadcast_handler_crash_is_dropped_not_retried(self, h: Harness):
        bus = h.client("reflection")
        attempts: list[int] = []

        async def handler(m):
            attempts.append(1)
            raise RuntimeError("boom")

        await bus.subscribe("task.*", handler)
        await bus.publish(_task_msg(1, "task:t1"))
        await h.settle(0.1)
        h.clock.advance(5.0)
        await h.settle(0.15)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(bus.metrics.counters.get("dropped", 0), 1)

    @for_each_backend
    async def test_pause_halts_commands_but_events_flow(self, h: Harness):
        cmd, evt = h.client("execution"), h.client("reflection")
        commands: list = []
        events: list = []

        async def on_cmd(m):
            commands.append(m)

        async def on_evt(m):
            events.append(m)

        await cmd.subscribe(topics.ACTION_APPROVED, on_cmd, group="execution")
        await evt.subscribe("task.*", on_evt)
        cmd.set_state("paused")
        await cmd.publish(make_message(topics.ACTION_APPROVED, source="execution"))
        await evt.publish(_task_msg(1, "task:t1"))
        await h.settle(0.15)
        self.assertEqual(len(commands), 0)
        self.assertEqual(len(events), 1)
        cmd.set_state("running")
        await h.settle(0.15)
        self.assertEqual(len(commands), 1)

    @for_each_backend
    async def test_duplicate_publish_of_an_acked_id_is_suppressed_for_a_group(self, h: Harness):
        bus = h.client("execution")
        seen: list = []

        async def handler(m):
            seen.append(m.id)

        await bus.subscribe(topics.ACTION_APPROVED, handler, group="execution")
        m = make_message(topics.ACTION_APPROVED, source="execution")
        await bus.publish(m)
        await h.settle(0.1)
        await bus.publish(m)  # at-least-once redelivery of the same id
        await h.settle(0.15)
        self.assertEqual(seen, [m.id])

    @for_each_backend
    async def test_trace_records_every_message_with_sampling(self, h: Harness):
        bus = h.client("planning")
        await bus.subscribe("#", lambda m: asyncio.sleep(0))
        m = _task_msg(1, "task:t1")
        await bus.publish(m)
        await bus.publish(make_message(topics.SYSTEM_TICK_SECOND, source="planning"))  # sampled to 0
        await bus.trace.flush()
        stream = f"trace:{m.trace_id}"
        self.assertEqual(h.ledger.types(stream), [topics.TASK_STEP])
        self.assertEqual(sum(len(v) for k, v in h.ledger.streams.items() if k.startswith("trace:")), 1)


class TestAtLeastOnceProperty(unittest.TestCase):
    @for_each_backend
    async def test_every_command_is_acked_at_least_once_or_dead_lettered(self, h: Harness):
        rng = random.Random(7)
        bus = h.client("execution")
        acked: dict[str, int] = {}
        flaky: set[str] = set()

        async def handler(m):
            if m.id in flaky and acked.get(m.id, 0) == 0 and rng.random() < 0.5:
                acked[m.id] = acked.get(m.id, 0)  # crash before acking
                raise RuntimeError("transient")
            acked[m.id] = acked.get(m.id, 0) + 1

        await bus.subscribe(topics.ACTION_APPROVED, handler, group="execution", max_inflight=4)
        ids = []
        for i in range(25):
            m = make_message(topics.ACTION_APPROVED, source="execution", partition_key=f"action:{i % 5}")
            if rng.random() < 0.4:
                flaky.add(m.id)
            ids.append(m.id)
            await bus.publish(m)
        for _ in range(8):
            await h.settle(0.1)
            h.clock.advance(4.0)
        await h.settle(0.2)
        dead = {e.payload["message"]["id"] for e in h.ledger.streams.get(f"dead:{topics.ACTION_APPROVED}", [])}
        for i in ids:
            self.assertTrue(acked.get(i, 0) >= 1 or i in dead, f"{h.name}: lost {i}")


if __name__ == "__main__":
    unittest.main()
