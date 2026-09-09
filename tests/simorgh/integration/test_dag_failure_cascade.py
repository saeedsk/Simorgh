"""Failure propagation across a multi-hop dependency chain, end to end
through a real Kernel running real Planning (docs/blueprint/subsystems/
07-planning.md section 5.3, `dag.py`'s dependency DAG).

`Service._propagate_failure` only ever walked one hop:
`dag.dependents_of(task_id, ...)` finds tasks that name the *just-failed*
task directly in their own `depends_on`, blocks those, and stops. A chain
A -> B -> C, where C depends only on B (not directly on A), is exactly
the shape a real decomposed plan produces (each step names only its
immediate prerequisite). When A fails terminally: B correctly goes
BLOCKED (it names A directly), but C -- whose only dependency, B, has
just gone BLOCKED and will now never COMPLETE -- was left PENDING
forever. `dag.is_ready(C, ...)` requires every dep to be COMPLETED, so
nothing ever moved C out of PENDING: no note, no dependency-failed event,
indistinguishable from a task genuinely still waiting on live work.

Live-reproduced against a real `Kernel` + real `Service` (not a stub) by
creating the chain directly in the store and failing A terminally over
the bus, observer 2026-09-08. Fixed by making `_propagate_failure` walk
the whole downstream closure (BFS), so a BLOCKED node's own dependents
are queued for the same treatment.
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
from simorgh.kernel.state import RUNNING
from simorgh.planning.config import Config as PlanningConfig
from simorgh.planning.model import AVAILABLE, BLOCKED, FAILED, PENDING
from simorgh.planning.service import Service as PlanningService


def _patched_build_factories(planning_config: PlanningConfig):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None, guardian_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl, guardian_config=guardian_config)
        factories = {name: factories[name] for name in ("bus", "ledger")}
        factories["planning"] = lambda: PlanningService(planning_config)
        return factories

    return _build


async def _pump(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


class TestFailureCascadesThroughAMultiHopChain(unittest.IsolatedAsyncioTestCase):
    async def _boot(self) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = LoadedConfig({"runtime": {"data_dir": tmp.name}}, None)
        kernel = Kernel(config, secrets=EnvSecretStore({}))
        patch = mock.patch("simorgh.kernel.service.build_factories", new=_patched_build_factories(PlanningConfig()))
        patch.start()
        self.addCleanup(patch.stop)
        await kernel.boot()
        self.assertEqual(kernel.state.state, RUNNING)
        self.addAsyncCleanup(kernel.shutdown)
        return kernel

    async def _status(self, kernel: Kernel, task_id: str) -> str:
        reply = await kernel.bus.request(Message.new(topics.TASK_LIST_REQUEST, source="tester", payload={}))
        return next(t for t in reply.payload["tasks"] if t["task_id"] == task_id)["status"]

    async def test_a_transitive_dependent_two_hops_away_is_blocked_not_left_pending_forever(self) -> None:
        kernel = await self._boot()
        store = kernel._supervisor.services["planning"].service._store  # noqa: SLF001

        project = await store.create(kind="project", description="chain project", origin="human", initial_status=AVAILABLE)
        a = await store.create(kind="patch", description="A", origin="project", parent_id=project.id, initial_status=AVAILABLE)
        b = await store.create(
            kind="patch", description="B depends on A", origin="project", parent_id=project.id,
            depends_on=[a.id], initial_status=PENDING,
        )
        c = await store.create(
            kind="patch", description="C depends ONLY on B (not directly on A)", origin="project",
            parent_id=project.id, depends_on=[b.id], initial_status=PENDING,
        )
        # An unrelated sibling with no dependency edge to the chain at all.
        d = await store.create(kind="patch", description="D unrelated sibling", origin="project", parent_id=project.id, initial_status=AVAILABLE)

        bus = kernel.bus
        await bus.request(Message.new(topics.TASK_CLAIM, source="tester", payload={"task_id": a.id, "worker_id": "w1"}))
        await bus.publish(Message.new(topics.TASK_STARTED, source="tester", payload={"task_id": a.id, "worker_id": "w1"}))
        await bus.publish(Message.new(
            topics.TASK_FAILED, source="tester",
            payload={"task_id": a.id, "reason": "gave up after 3 attempts", "terminal": True, "attempts": 3},
        ))
        await _pump(20)

        self.assertEqual(await self._status(kernel, a.id), FAILED)
        self.assertEqual(await self._status(kernel, b.id), BLOCKED)
        # This is the bug: without the fix, C stays PENDING forever.
        self.assertEqual(await self._status(kernel, c.id), BLOCKED)
        # An unrelated sibling must be completely unaffected.
        self.assertEqual(await self._status(kernel, d.id), AVAILABLE)

    async def test_a_diamond_that_reconverges_is_blocked_exactly_once_not_twice(self) -> None:
        """C depends on both A and B (B itself depends on A) -- the BFS
        must not visit and re-transition an already-BLOCKED C a second
        time when it reaches it via both the A->C and A->B->C paths."""
        kernel = await self._boot()
        store = kernel._supervisor.services["planning"].service._store  # noqa: SLF001

        project = await store.create(kind="project", description="diamond project", origin="human", initial_status=AVAILABLE)
        a = await store.create(kind="patch", description="A", origin="project", parent_id=project.id, initial_status=AVAILABLE)
        b = await store.create(
            kind="patch", description="B depends on A", origin="project", parent_id=project.id,
            depends_on=[a.id], initial_status=PENDING,
        )
        c = await store.create(
            kind="patch", description="C depends on A and B", origin="project", parent_id=project.id,
            depends_on=[a.id, b.id], initial_status=PENDING,
        )

        bus = kernel.bus
        await bus.request(Message.new(topics.TASK_CLAIM, source="tester", payload={"task_id": a.id, "worker_id": "w1"}))
        await bus.publish(Message.new(topics.TASK_STARTED, source="tester", payload={"task_id": a.id, "worker_id": "w1"}))
        await bus.publish(Message.new(
            topics.TASK_FAILED, source="tester",
            payload={"task_id": a.id, "reason": "gave up after 3 attempts", "terminal": True, "attempts": 3},
        ))
        await _pump(20)

        self.assertEqual(await self._status(kernel, b.id), BLOCKED)
        self.assertEqual(await self._status(kernel, c.id), BLOCKED)


if __name__ == "__main__":
    unittest.main()
