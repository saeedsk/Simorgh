"""`task.create` is used both ways, and Planning has to accept both.

As a REQUEST by the Interface's commands and by `start_task`, which
want the id back. Fire-and-forget by Reflection's distillation and by
Benchmark, which are announcing work rather than asking for a receipt.

Planning replied unconditionally, and `bus.reply` raises on a message
with no `reply_to` -- so every announcement raised
"task.create (...) is not a request: no reply_to" out of the bus
handler. The task WAS created; the casualties were a traceback in the
middle of the screen and a dead-lettered message. Caught live
2026-09-09, when Reflection distilled a finished build into a skill.

A real bus here, not a fake: the raise came from the real `reply`, and
a fake that accepts anything would prove nothing."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.planning.service import Service

from tests.simorgh.helpers import FakeClock


class _Logger:
    def __init__(self) -> None:
        self.errors: list = []

    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass

    def error(self, event, **f):
        self.errors.append((event, f))


class TaskCreateTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(self.backend, source="planning", ledger=self.ledger,
                               clock=self.clock.now)
        await self.bus.start()
        self.other = make_client(self.backend, source="reflection", ledger=self.ledger,
                                 clock=self.clock.now)
        await self.other.start()
        self.logger = _Logger()
        self.ctx = Context(
            name="planning", instance_id="", run_id="test", mode="single", bus=self.bus,
            ledger=self.ledger, config={}, secrets={}, clock=self.clock, logger=self.logger,
            data_dir=Path(self._tmp.name) / "data")
        self.service = Service()
        await self.service.start(self.ctx)
        self.created: list = []

        async def _on_created(message: Message) -> None:
            self.created.append(message)

        self._sub = await self.other.subscribe(topics.TASK_CREATED, _on_created)

    async def asyncTearDown(self):
        await self._sub.unsubscribe()
        await self.service.stop()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _pump(self, n: int = 30) -> None:
        for _ in range(n):
            await asyncio.sleep(0)

    def _payload(self, description: str) -> dict:
        return {"kind": "patch", "description": description, "origin": "human",
                "mode": "execute", "subject": "workspace/x.html"}

    async def test_an_announcement_with_no_reply_to_does_not_raise(self):
        """Reflection publishes rather than requests. The traceback this
        produced sat in the middle of the screen while the task itself
        was created perfectly."""
        await self.other.publish(Message.new(
            topics.TASK_CREATE, source="reflection",
            payload=self._payload("distil the finished build into a skill"),
            clock=self.clock.now))
        await self._pump()
        self.assertEqual(self.logger.errors, [])
        self.assertTrue(self.created, "the task should still be created")

    async def test_the_task_is_created_either_way(self):
        await self.other.publish(Message.new(
            topics.TASK_CREATE, source="reflection", payload=self._payload("announced work"),
            clock=self.clock.now))
        await self._pump()
        self.assertEqual(self.created[0].payload["description"], "announced work")

    async def test_a_real_request_still_gets_its_id_back(self):
        reply = await self.other.request(
            Message.new(topics.TASK_CREATE, source="reflection",
                        payload=self._payload("requested work"), clock=self.clock.now),
            timeout=5.0)
        self.assertEqual(reply.type, topics.TASK_CREATE_REPLY)
        self.assertTrue(reply.payload.get("task_id"))

    async def test_every_request_gets_an_answer_it_can_use(self):
        """Deliberately not asserting anything about deduplication --
        that is intake's business and this change did not touch it. What
        matters here is that a requester always gets a reply carrying an
        id, whichever branch produced it."""
        for description in ("first piece of work", "second piece of work"):
            reply = await self.other.request(
                Message.new(topics.TASK_CREATE, source="reflection",
                            payload=self._payload(description), clock=self.clock.now),
                timeout=5.0)
            self.assertTrue(reply.payload.get("task_id"), description)

    async def test_an_announcement_that_duplicates_is_also_silent(self):
        for _ in range(2):
            await self.other.publish(Message.new(
                topics.TASK_CREATE, source="reflection", payload=self._payload("same again"),
                clock=self.clock.now))
            await self._pump()
        self.assertEqual(self.logger.errors, [])
