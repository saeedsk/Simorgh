"""Memory `Service`, over a real (memory-backend) Bus/Ledger and a real
Context -- the same shape `tests/simorgh/worldmodel/test_service.py`
uses, so this package's tests don't depend on `simorgh.kernel`."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.config import Config as BusConfig
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config as MemoryConfig
from simorgh.memory.service import Service
from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class MemoryServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="memory", ledger=self.ledger, clock=self.clock)
        await self.bus.start()
        self.ctx = Context(
            name="memory", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data",
        )
        self.service = Service(config=MemoryConfig(half_life_seconds=1_000_000.0))
        await self.service.start(self.ctx)

    async def asyncTearDown(self):
        await self.service.stop()
        await self.bus.stop()
        self._tmp.cleanup()

    async def _store_and_wait(self, payload: dict) -> Message:
        """`memory.store` is a command (fire-and-forget, no reply_to) --
        wait for its own confirmation event instead of `bus.request`."""
        done: asyncio.Future = asyncio.get_running_loop().create_future()

        async def _on_stored(message: Message) -> None:
            if not done.done():
                done.set_result(message)

        sub = await self.bus.subscribe(topics.MEMORY_STORED, _on_stored)
        try:
            await self.bus.publish(Message.new(topics.MEMORY_STORE, source="test", payload=payload))
            return await asyncio.wait_for(done, timeout=5.0)
        finally:
            await sub.unsubscribe()

    async def test_store_then_retrieve_over_the_bus(self):
        await self._store_and_wait({
            "kind": "semantic", "content": "simorgh likes clear interfaces", "tags": ["design"],
            "source_ref": "",
        })
        retrieve = Message.new(topics.MEMORY_RETRIEVE, source="test", payload={
            "query": "clear interfaces", "kinds": ["semantic"], "k": 5,
        })
        reply = await self.bus.request(retrieve, timeout=5.0)
        self.assertEqual(len(reply.payload["items"]), 1)
        self.assertIn("clear interfaces", reply.payload["items"][0]["content"])
        self.assertGreater(reply.payload["items"][0]["score"], 0.0)

    async def test_store_publishes_memory_stored(self):
        stored = await self._store_and_wait({"kind": "episodic", "content": "something happened", "tags": [], "source_ref": ""})
        self.assertEqual(stored.payload["kind"], "episodic")

    async def test_working_kind_store_is_session_scoped_not_durable(self):
        # working-kind stores never publish memory.stored (service.py's
        # early return) -- publish directly and give the handler a turn.
        await self.bus.publish(Message.new(topics.MEMORY_STORE, source="test", payload={
            "kind": "working", "content": "the reply half of a turn", "tags": ["sess1"], "source_ref": "",
        }))
        for _ in range(10):
            await asyncio.sleep(0)
        retrieve = Message.new(topics.MEMORY_RETRIEVE, source="test", payload={
            "query": "", "kinds": ["working"], "k": 5, "filters": {"session_id": "sess1"},
        })
        reply = await self.bus.request(retrieve, timeout=5.0)
        self.assertEqual(len(reply.payload["items"]), 1)

    async def test_sleep_tick_publishes_consolidated_and_contradiction_events(self):
        await self._store_and_wait({"kind": "semantic", "content": "the sky is blue", "tags": ["sky"], "source_ref": ""})
        self.clock.advance(1.0)
        await self._store_and_wait({"kind": "semantic", "content": "the sky is green", "tags": ["sky"], "source_ref": ""})

        consolidated = []
        contradictions = []

        async def _on_consolidated(message: Message) -> None:
            consolidated.append(message)

        async def _on_contradiction(message: Message) -> None:
            contradictions.append(message)

        sub1 = await self.bus.subscribe(topics.MEMORY_CONSOLIDATED, _on_consolidated)
        sub2 = await self.bus.subscribe(topics.MEMORY_CONTRADICTION_FLAGGED, _on_contradiction)
        await self.bus.publish(Message.new(topics.SYSTEM_TICK_SLEEP, source="test", payload={"window_seconds": 3600.0}))
        for _ in range(20):
            await asyncio.sleep(0)
        await sub1.unsubscribe()
        await sub2.unsubscribe()

        self.assertEqual(len(consolidated), 1)
        self.assertEqual(len(contradictions), 1)
        self.assertEqual(contradictions[0].payload["confidence_after"], 0.5)

    async def test_sleep_tick_with_pruning_publishes_forgotten(self):
        for i in range(5):
            await self._store_and_wait({"kind": "episodic", "content": f"e{i}", "tags": [], "source_ref": ""})

        forgotten = []

        async def _on_forgotten(message: Message) -> None:
            forgotten.append(message)

        async def _floor_think(message: Message) -> None:
            # a non-episodic-empty window makes the Service ask Cognition to
            # distill; answer honestly-unavailable immediately so this test
            # doesn't pay the real 30s no-responder timeout.
            await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
                "text": "[floor] unavailable", "tool_calls": [], "provider": "floor",
                "cost_usd": 0.0, "tokens": 0, "floor": True, "non_answer": False,
            })

        sub = await self.bus.subscribe(topics.MEMORY_FORGOTTEN, _on_forgotten)
        sub_think = await self.bus.subscribe(topics.COGNITION_THINK, _floor_think)
        self.service._keep_per_kind = {"episodic": 2, "semantic": 100, "procedural": 100}
        await self.bus.publish(Message.new(topics.SYSTEM_TICK_SLEEP, source="test", payload={"window_seconds": 3600.0}))
        for _ in range(20):
            await asyncio.sleep(0)
        await sub.unsubscribe()
        await sub_think.unsubscribe()

        self.assertEqual(len(forgotten), 1)
        self.assertIn("pruned 3 record", forgotten[0].payload["reason"])


if __name__ == "__main__":
    unittest.main()
