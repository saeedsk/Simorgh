"""Priority is enforced when a worker becomes free, not when an offer
was published.

Live, 2026-09-10, one worker: a benchmark case (weight 2) was created
18s after a curiosity task (weight 1) had been offered. The worker was
busy; both offers queued in the bus in publish order. Five minutes
later the worker freed, claimed the older curiosity offer, and the case
sat for 591 of its 600 seconds before being read -- then was cancelled
by its own clock four steps in, with a correct patch in the tree.

`select_ready` sorted the offers correctly. Nothing consulted that order
at the claim.
"""

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
from simorgh.planning.config import Config
from simorgh.planning.scheduler import better_ready
from simorgh.planning.service import Service
from tests.simorgh.helpers import FakeClock


class _Task:
    def __init__(self, id_, *, origin, created_at=0.0):
        self.id = id_
        self.origin = origin
        self.kind = "patch"
        self.attempts = 0
        self.created_at = created_at
        self.updated_at = created_at


class _Index:
    def __init__(self, tasks):
        self.tasks = {t.id: t for t in tasks}


class _Store:
    def __init__(self, tasks):
        self._tasks = list(tasks)
        self.index = _Index(tasks)

    def ready(self, limit=1000):
        return list(self._tasks)


WEIGHTS = Config().priority_weights


class BetterReadyTestCase(unittest.TestCase):
    def test_a_heavier_task_is_taken_instead_of_the_offered_one(self):
        curiosity = _Task("c", origin="curiosity", created_at=1.0)
        bench = _Task("b", origin="benchmark", created_at=20.0)
        self.assertIs(better_ready(_Store([curiosity, bench]), "c", priority_weights=WEIGHTS), bench)

    def test_the_offered_task_is_kept_when_it_is_the_heaviest(self):
        curiosity = _Task("c", origin="curiosity", created_at=1.0)
        bench = _Task("b", origin="benchmark", created_at=20.0)
        self.assertIsNone(better_ready(_Store([curiosity, bench]), "b", priority_weights=WEIGHTS))

    def test_equal_weight_keeps_the_offer_order(self):
        older = _Task("a", origin="curiosity", created_at=1.0)
        newer = _Task("z", origin="curiosity", created_at=2.0)
        self.assertIsNone(better_ready(_Store([older, newer]), "z", priority_weights=WEIGHTS))

    def test_an_unknown_task_is_no_opinion(self):
        self.assertIsNone(better_ready(_Store([_Task("b", origin="benchmark")]), "nope", priority_weights=WEIGHTS))


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class TheClaimIsRedirected(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="planning", ledger=self.ledger, clock=self.clock)
        self.worker = make_client(backend, source="orchestration", ledger=self.ledger, clock=self.clock)
        await self.bus.start()
        await self.worker.start()
        self.ctx = Context(
            name="planning", instance_id="", run_id="test", mode="single", bus=self.bus,
            ledger=self.ledger, config={}, secrets={}, clock=self.clock, logger=_Logger(),
            data_dir=Path(self._tmp.name) / "data")
        self.service = Service()
        await self.service.start(self.ctx)
        self.offers: list[str] = []

        async def _on_offer(message: Message) -> None:
            self.offers.append(message.payload["task_id"])

        self._sub = await self.worker.subscribe(topics.TASK_AVAILABLE, _on_offer)

    async def asyncTearDown(self):
        await self._sub.unsubscribe()
        await self.service.stop()
        await self.worker.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _create(self, origin: str, description: str) -> str:
        reply = await self.worker.request(Message.new(
            topics.TASK_CREATE, source="test", clock=self.clock.now,
            payload={"kind": "patch", "description": description, "origin": origin, "mode": "execute",
                     "subject": f"workspace/{origin}.py"}), timeout=2.0)
        return reply.payload["task_id"]

    async def _claim(self, task_id: str) -> dict:
        reply = await self.worker.request(Message.new(
            topics.TASK_CLAIM, source="orchestration", clock=self.clock.now,
            # `accept_better`: the redirect is opt-in, and this claimer
            # -- like the real Worker -- runs whatever the reply names.
            payload={"task_id": task_id, "worker_id": "w1", "accept_better": True}), timeout=2.0)
        return reply.payload

    async def test_the_live_shape_the_stale_curiosity_offer_yields_to_the_benchmark_case(self):
        curiosity = await self._create("curiosity", "tidy something")
        self.clock.advance(18.0)
        bench = await self._create("benchmark", "fix this bug in the checkout")
        payload = await self._claim(curiosity)
        self.assertTrue(payload["granted"])
        self.assertEqual(payload["task"]["task_id"], bench, "the worker runs the benchmark case, not the stale offer")
        self.assertEqual(payload["task"]["origin"], "benchmark")
        # And the curiosity task was not lost: still available, and
        # offered again on the next dispatch.
        task = await self.service._store.get(curiosity)  # noqa: SLF001
        self.assertEqual(task.status, "available")
        self.offers.clear()
        await self.service._scheduler.dispatch_ready()  # noqa: SLF001
        for _ in range(20):
            await asyncio.sleep(0)
        self.assertIn(curiosity, self.offers, "a passed-over task must be re-offered")

    async def test_a_claim_for_the_heaviest_task_is_untouched(self):
        curiosity = await self._create("curiosity", "tidy something")
        bench = await self._create("benchmark", "fix this bug in the checkout")
        payload = await self._claim(bench)
        self.assertTrue(payload["granted"])
        self.assertEqual(payload["task"]["task_id"], bench)
        self.assertEqual((await self.service._store.get(curiosity)).status, "available")  # noqa: SLF001

    async def test_a_second_claim_for_the_redirected_offer_now_gets_it(self):
        curiosity = await self._create("curiosity", "tidy something")
        await self._create("benchmark", "fix this bug in the checkout")
        first = await self._claim(curiosity)
        second = await self._claim(curiosity)
        self.assertNotEqual(first["task"]["task_id"], curiosity)
        self.assertTrue(second["granted"])
        self.assertEqual(second["task"]["task_id"], curiosity)


if __name__ == "__main__":
    unittest.main()
