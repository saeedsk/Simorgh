"""Phase 0 acceptance (docs/blueprint/04 section 3): two toy `Subsystem`s
exchange an event, a command through a competing group of two, and a
request/reply -- on each backend, over the real BusClient, with only
`contracts` + the bus client imported (exactly what a real subsystem
may import)."""

import asyncio
import unittest
from pathlib import Path

from simorgh.bus.client import BusClient
from simorgh.contracts import topics
from simorgh.contracts.protocols import Context, Health

from tests.simorgh.helpers import make_message

from tests.simorgh.bus.harness import Harness, for_each_backend


class Producer:
    name, version = "planning", "0"
    consumes = (topics.TASK_CLAIM,)
    produces = (topics.TASK_AVAILABLE, topics.TASK_CREATED, topics.TASK_CLAIM_REPLY)

    async def start(self, ctx: Context) -> None:
        self.bus = ctx.bus
        self.claims: list = []
        await self.bus.subscribe(topics.TASK_CLAIM, self._on_claim, group="planning")

    async def _on_claim(self, m):
        self.claims.append(m.payload["worker_id"])
        await self.bus.reply(m, type=topics.TASK_CLAIM_REPLY, payload={"granted": True, "lease_until": 9.0, "task": {"id": m.payload["task_id"]}})

    async def stop(self) -> None:
        return None

    async def health(self) -> Health:
        return Health.ok()


class Worker:
    version = "0"
    consumes = (topics.TASK_AVAILABLE, topics.TASK_CREATED)
    produces = (topics.TASK_CLAIM, topics.TASK_STARTED)

    def __init__(self, name: str) -> None:
        self.name = "orchestration"
        self.instance = name
        self.events: list = []
        self.worked: list = []

    async def start(self, ctx: Context) -> None:
        self.bus = ctx.bus
        await self.bus.subscribe(topics.TASK_CREATED, self._on_event)
        await self.bus.subscribe(topics.TASK_AVAILABLE, self._on_available, group="workers")

    async def _on_event(self, m):
        self.events.append(m.payload["task_id"])

    async def _on_available(self, m):
        req = self.bus.new(topics.TASK_CLAIM, {"task_id": m.payload["task_id"], "worker_id": self.instance},
                           caused_by=m, partition_key=m.partition_key)
        reply = await self.bus.request(req, timeout=2.0)
        if reply.payload["granted"]:
            self.worked.append(m.payload["task_id"])
            await self.bus.publish(self.bus.new(topics.TASK_STARTED, {"task_id": m.payload["task_id"], "worker_id": self.instance},
                                                caused_by=reply, partition_key=m.partition_key))

    async def stop(self) -> None:
        return None

    async def health(self) -> Health:
        return Health.ok()


def _ctx(bus: BusClient, h: Harness, name: str, instance: str = "") -> Context:
    return Context(name=name, instance_id=instance, run_id="r1", mode="single", bus=bus, ledger=h.ledger, config={},
                   secrets={}, clock=h.clock, logger=None, data_dir=Path("."))  # type: ignore[arg-type]


class TestTwoToySubsystems(unittest.TestCase):
    @for_each_backend
    async def test_event_command_and_request_reply(self, h: Harness):
        producer, w1, w2 = Producer(), Worker("w1"), Worker("w2")
        await producer.start(_ctx(h.client("planning"), h, "planning"))
        await w1.start(_ctx(h.client("orchestration@w1"), h, "orchestration", "w1"))
        await w2.start(_ctx(h.client("orchestration@w2"), h, "orchestration", "w2"))
        bus = h.client("planning")
        for i in range(6):
            tid = f"t{i}"
            created = make_message(topics.TASK_CREATED, source="planning", partition_key=f"task:{tid}",
                                   payload={"task_id": tid, "kind": "patch", "description": "d", "depends_on": [],
                                            "mode": "execute", "origin": "human", "risk": "low"})
            await bus.publish(created)
            # caused by `created` (not a fresh, independently-traced message) so the whole
            # per-task chain lands in one trace stream -- the point of the assertion below.
            await bus.publish(bus.new(topics.TASK_AVAILABLE, {"task_id": tid, "kind": "patch", "lease_seconds": 60},
                                      caused_by=created))
        await h.settle(0.8 if h.name == "sqlite" else 0.4)
        # event: every worker saw every created task
        self.assertEqual(sorted(w1.events), [f"t{i}" for i in range(6)])
        self.assertEqual(sorted(w2.events), [f"t{i}" for i in range(6)])
        # command: each available task was claimed by exactly one worker
        self.assertEqual(sorted(w1.worked + w2.worked), [f"t{i}" for i in range(6)])
        # request/reply: the producer answered every claim
        self.assertEqual(len(producer.claims), 6)
        # trace: each task's chain is reconstructible from the ledger
        traces = [k for k in h.ledger.streams if k.startswith("trace:")]
        self.assertEqual(len(traces), 6)
        for k in traces:
            self.assertEqual(h.ledger.types(k)[0], topics.TASK_CREATED)


if __name__ == "__main__":
    unittest.main()
