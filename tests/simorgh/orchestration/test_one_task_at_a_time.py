"""A worker runs one task at a time.

Live-caught 2026-09-07. The creator's `tasks` output showed all 109 tasks
in `claimed` at once -- a single worker holding the entire backlog. Every
one of those sessions was running concurrently, competing for the same
provider, and none of them finished.

The cause was one default. `BusClient.subscribe`'s `max_inflight` is 16,
and the worker took it, so a single worker ran up to sixteen sessions at
once. `current_task_id` being a single value -- a dashboard's "what is
this worker doing right now" -- says one at a time was always the intent.

The cap belongs on the subscription rather than in a queue inside the
worker: that way the delivery stays unacknowledged until the session
really finishes, which is what lets a *crashed* worker's task be
redelivered to the next one (see
tests/simorgh/integration/test_local_multi_worker_crash_resume.py).
"""

from __future__ import annotations

import asyncio
import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.orchestration.worker import Worker

from .fakes import FakeCognition
from .harness import Harness, run


class _Planning:
    """Grants every claim and records the order, standing where the real
    Planning service stands."""

    def __init__(self, bus) -> None:
        self._bus = bus
        self.claims: list[str] = []
        self._granted: set[str] = set()
        self.live = 0
        self.max_live = 0
        self._sub = None

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(topics.TASK_CLAIM, self._on_claim)

    async def stop(self) -> None:
        if self._sub:
            await self._sub.unsubscribe()

    async def _on_claim(self, message: Message) -> None:
        """Grants a task once, then refuses -- what the real store does,
        since a claimed task is already leased to somebody."""
        task_id = message.payload["task_id"]
        self.claims.append(task_id)
        if task_id in self._granted:
            await self._bus.reply(message, type=topics.TASK_CLAIM_REPLY,
                                  payload={"granted": False, "reason": "leased_to_other"})
            return
        self._granted.add(task_id)
        self.live += 1
        self.max_live = max(self.max_live, self.live)
        await self._bus.reply(message, type=topics.TASK_CLAIM_REPLY, payload={
            "granted": True,
            "task": {"task_id": task_id, "kind": "chat", "description": "do a thing",
                     "mode": "execute", "origin": "curiosity", "status": "claimed"},
        })

    def finished(self) -> None:
        self.live -= 1


class OneAtATimeTestCase(unittest.TestCase):
    @run
    async def test_offering_ten_tasks_claims_them_one_at_a_time(self):
        async with Harness() as h:
            planning = _Planning(h.client("planning"))
            await planning.start()
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "done"}])
            await cognition.start()

            done: list[str] = []

            async def _watch(message: Message) -> None:
                planning.finished()
                done.append(message.payload["task_id"])

            sub = await h.client("observer").subscribe(topics.TASK_COMPLETED, _watch)

            worker = Worker(h.client("orchestration"), h.ledger, clock=h.clock.now)
            await worker.start()
            offers = h.client("planning")
            for i in range(10):
                await offers.publish(Message.new(
                    topics.TASK_AVAILABLE, source="planning",
                    payload={"task_id": f"t{i}", "kind": "chat", "lease_seconds": 600.0},
                ))

            for _ in range(400):
                if len(done) >= 10:
                    break
                await asyncio.sleep(0.01)

            await worker.stop()
            await sub.unsubscribe()
            await cognition.stop()
            await planning.stop()

            self.assertEqual(len(done), 10, "every offered task should still get run")
            self.assertEqual(
                planning.max_live, 1,
                f"the worker held {planning.max_live} tasks at once; it must hold one",
            )

    @run
    async def test_the_same_task_offered_three_times_is_only_run_once(self):
        """Duplicate offers are settled by Planning refusing the second
        claim (a claimed task is already leased), not by the worker
        keeping its own list."""
        async with Harness() as h:
            planning = _Planning(h.client("planning"))
            await planning.start()
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "done"}])
            await cognition.start()

            done: list[str] = []
            sub = await h.client("observer").subscribe(
                topics.TASK_COMPLETED, lambda m: (planning.finished(), done.append(m.payload["task_id"]))[0] or asyncio.sleep(0),
            )

            worker = Worker(h.client("orchestration"), h.ledger, clock=h.clock.now)
            await worker.start()
            for _ in range(3):
                await h.client("planning").publish(Message.new(
                    topics.TASK_AVAILABLE, source="planning",
                    payload={"task_id": "t-same", "kind": "chat", "lease_seconds": 600.0},
                ))

            for _ in range(200):
                if done:
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.1)

            await worker.stop()
            await sub.unsubscribe()
            await cognition.stop()
            await planning.stop()

            self.assertEqual(done.count("t-same"), 1, "the task ran more than once")
            self.assertEqual(planning.max_live, 1)

    @run
    async def test_stopping_a_worker_with_no_work_does_not_raise(self):
        async with Harness() as h:
            worker = Worker(h.client("orchestration"), h.ledger, clock=h.clock.now)
            await worker.start()
            await worker.stop()  # no offers ever arrived; must be clean


if __name__ == "__main__":
    unittest.main()
