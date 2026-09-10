"""A retry that produces the same answer again is the end of the road.

From a real GAIA run, 2026-09-10. A research task whose answer
verification rejects goes straight back on the queue with the objection
in hand, and that is worth doing: the next attempt carries what the
reviewer said. But 8 of the 18 retried tasks came back with an answer
identical to the one just rejected, so the same reviewer made the same
objection, and the loop ran again -- up to ten times for one question,
while four other questions were never started at all.

The rule here is the narrow one the evidence supports: an attempt that
ends with the answer the previous attempt was blocked for cannot be
followed by a different objection, so it is terminal. An attempt that
produces something *different* still gets its retry.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.planning.config import Config as PlanningConfig
from simorgh.planning.model import AVAILABLE, BLOCKED, FAILED
from simorgh.planning.service import Service as PlanningService

VERIFICATION = "verification failed after max revisions"


def _patched_build_factories(planning_config: PlanningConfig):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None, guardian_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl,
                         guardian_config=guardian_config)
        factories = {name: factories[name] for name in ("bus", "ledger")}
        factories["planning"] = lambda: PlanningService(planning_config)
        return factories

    return _build


async def _pump(n: int = 30) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


class RepeatedAnswerTestCase(unittest.IsolatedAsyncioTestCase):
    async def _boot(self) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = LoadedConfig({"runtime": {"data_dir": tmp.name}}, None)
        kernel = Kernel(config, secrets=EnvSecretStore({}))
        patch = mock.patch("simorgh.kernel.service.build_factories",
                           new=_patched_build_factories(PlanningConfig()))
        patch.start()
        self.addCleanup(patch.stop)
        await kernel.boot()
        self.addAsyncCleanup(kernel.shutdown)
        return kernel

    async def _task(self, kernel: Kernel):
        store = kernel._supervisor.services["planning"].service._store  # noqa: SLF001
        task = await store.create(kind="research", description="how many stanzas?", origin="benchmark")
        if task.status != AVAILABLE:
            await store.transition(task.id, AVAILABLE)
        return store, task

    async def _block(self, kernel: Kernel, task_id: str, answer: str) -> None:
        await kernel.bus.publish(Message.new(
            topics.TASK_BLOCKED, source="orchestration",
            partition_key=f"task:{task_id}",
            payload={"task_id": task_id, "reason": VERIFICATION, "result_summary": answer},
        ))
        await _pump()

    async def test_the_same_answer_twice_ends_the_task(self):
        kernel = await self._boot()
        store, task = await self._task(kernel)

        await self._block(kernel, task.id, "FINAL ANSWER: 2")
        self.assertEqual((await store.get(task.id)).status, BLOCKED)

        await store.transition(task.id, AVAILABLE)
        await self._block(kernel, task.id, "FINAL ANSWER: 2")
        stopped = await store.get(task.id)
        self.assertEqual(stopped.status, FAILED)
        self.assertIn("same answer", stopped.note)

    async def test_a_different_answer_still_earns_another_attempt(self):
        kernel = await self._boot()
        store, task = await self._task(kernel)

        await self._block(kernel, task.id, "FINAL ANSWER: 2")
        await store.transition(task.id, AVAILABLE)
        await self._block(kernel, task.id, "FINAL ANSWER: 3")
        self.assertEqual((await store.get(task.id)).status, BLOCKED)

    async def test_whitespace_alone_is_not_a_different_answer(self):
        kernel = await self._boot()
        store, task = await self._task(kernel)

        await self._block(kernel, task.id, "FINAL ANSWER: 2")
        await store.transition(task.id, AVAILABLE)
        await self._block(kernel, task.id, "FINAL  ANSWER:   2\n")
        self.assertEqual((await store.get(task.id)).status, FAILED)

    async def test_an_outcome_with_no_answer_does_not_end_anything(self):
        """A cancel or a crash says nothing about repetition, and must
        not erase what the last real answer was."""
        kernel = await self._boot()
        store, task = await self._task(kernel)

        await self._block(kernel, task.id, "FINAL ANSWER: 2")
        await store.transition(task.id, AVAILABLE)
        await self._block(kernel, task.id, "")
        self.assertEqual((await store.get(task.id)).status, BLOCKED)

        await store.transition(task.id, AVAILABLE)
        await self._block(kernel, task.id, "FINAL ANSWER: 2")
        self.assertEqual((await store.get(task.id)).status, FAILED)


if __name__ == "__main__":
    unittest.main()
