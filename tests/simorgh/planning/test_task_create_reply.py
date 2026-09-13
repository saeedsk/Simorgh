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


class HeldReplyTestCase(TaskCreateTestCase):
    """The reply says when the new task will not run (2026-09-13)."""

    async def test_an_assistant_task_under_auto_off_is_marked_held_and_a_humans_is_not(self):
        self.service._scheduler.autonomous_paused = True  # noqa: SLF001 -- `auto off`
        reply = await self.other.request(Message.new(topics.TASK_CREATE, source="execution", payload={
            "kind": "patch", "description": "five cartoon splash screens", "origin": "assistant", "mode": "execute"}),
            timeout=5.0)
        self.assertTrue(reply.payload.get("held"))
        self.assertIn("auto is off", reply.payload.get("held_reason", ""))
        reply = await self.other.request(Message.new(topics.TASK_CREATE, source="execution", payload={
            "kind": "patch", "description": "a different thing the person asked for by name", "origin": "human",
            "mode": "execute"}), timeout=5.0)
        self.assertFalse(reply.payload.get("held"))
        self.service._scheduler.autonomous_paused = False  # noqa: SLF001
        reply = await self.other.request(Message.new(topics.TASK_CREATE, source="execution", payload={
            "kind": "patch", "description": "a third, quite unlike the others, about cameras", "origin": "assistant",
            "mode": "execute"}), timeout=5.0)
        self.assertFalse(reply.payload.get("held"))


class CancelAndPauseLifecycleTestCase(TaskCreateTestCase):
    """Three things an observer found on 2026-09-13: a cancelled running
    task whose worker never reports came back with its lease; a task
    paused by a system pause never resumed; a paused task could not be
    cancelled."""

    async def _create(self, description, origin="human"):
        reply = await self.other.request(Message.new(topics.TASK_CREATE, source="execution", payload={
            "kind": "patch", "description": description, "origin": origin, "mode": "execute"}), timeout=5.0)
        return reply.payload["task_id"]

    async def _tick(self, seconds: float):
        self.clock.advance(seconds)
        await self.other.publish(Message.new(topics.SYSTEM_TICK_SECOND, source="kernel", payload={"n": 1, "ts": self.clock.now()}))
        await asyncio.sleep(0.05)

    async def test_a_cancelled_running_task_ends_when_its_lease_expires(self):
        store = self.service._store  # noqa: SLF001
        task_id = await self._create("a running task whose worker vanishes")
        claim = await store.claim(task_id, "w1", lease_seconds=30.0)
        self.assertTrue(claim.granted, claim.reason)
        await self.other.publish(Message.new(topics.TASK_STARTED, source="orchestration",
                                             payload={"task_id": task_id, "worker_id": "w1"}))
        await asyncio.sleep(0.05)
        await self.other.publish(Message.new(topics.TASK_CANCEL, source="interface",
                                             payload={"task_id": task_id, "reason": "cancelled by cli:s1"}))
        await asyncio.sleep(0.05)
        self.assertEqual((await store.get(task_id)).status, "in_progress", "the worker is left to end it")
        # ...but the worker never reports; the lease runs out
        await self._tick(60.0)
        await self._tick(1.0)
        task = await store.get(task_id)
        self.assertEqual(task.status, "failed", task.note)
        self.assertIn("cancelled", task.note)

    async def test_a_system_paused_task_resumes_when_the_system_runs_again(self):
        store = self.service._store  # noqa: SLF001
        task_id = await self._create("a task the pause parked")
        await store.claim(task_id, "w1", lease_seconds=30.0)
        await self.other.publish(Message.new(topics.TASK_PAUSED, source="orchestration",
                                             payload={"task_id": task_id, "reason": "system paused", "resume_from_step": 2}))
        await asyncio.sleep(0.05)
        self.assertEqual((await store.get(task_id)).status, "paused")
        await self.other.publish(Message.new(topics.SYSTEM_STATE_CHANGED, source="kernel", payload={"state": "paused"}))
        await asyncio.sleep(0.05)
        await self.other.publish(Message.new(topics.SYSTEM_STATE_CHANGED, source="kernel", payload={"state": "running"}))
        await asyncio.sleep(0.05)
        self.assertEqual((await store.get(task_id)).status, "available")

    async def test_a_paused_task_can_be_cancelled(self):
        store = self.service._store  # noqa: SLF001
        task_id = await self._create("a parked task nobody wants")
        await store.claim(task_id, "w1", lease_seconds=30.0)
        await self.other.publish(Message.new(topics.TASK_PAUSED, source="orchestration",
                                             payload={"task_id": task_id, "reason": "system paused", "resume_from_step": 1}))
        await asyncio.sleep(0.05)
        await self.other.publish(Message.new(topics.TASK_CANCEL, source="interface",
                                             payload={"task_id": task_id, "reason": "cancelled by cli:s1"}))
        await asyncio.sleep(0.05)
        self.assertEqual((await store.get(task_id)).status, "failed")
