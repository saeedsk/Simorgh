"""A project whose remaining work can never run must not say it is
still in progress.

Live-caught by an observer over a real Kernel, 2026-09-10. Three
children, A -> B -> C. A completed, B failed terminally, C was parked
BLOCKED with the note `dependency_failed:<B>`. BLOCKED is not a terminal
status, so `project_status` fell through to "some children completed ->
IN_PROGRESS" and stayed there: nothing could ever move again, and
`project.failed` was never published, on that event or any later one.

Observed rollup: `in_progress done=1/3 stalled=False`, project events:
none.
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
from simorgh.planning.model import (
    AVAILABLE, BLOCKED, COMPLETED, DEPENDENCY_FAILED_NOTE, FAILED, IN_PROGRESS, PENDING, Task,
)
from simorgh.planning.rollup import project_status
from simorgh.planning.service import Service as PlanningService


def _child(status: str, note: str = "") -> Task:
    return Task(id=f"t{status}{note}", kind="patch", description="d", status=status, note=note)


class TheRollupKnowsWhatIsDeadTestCase(unittest.TestCase):
    def test_a_child_parked_behind_a_failure_cannot_keep_a_project_alive(self):
        children = [_child(COMPLETED), _child(FAILED),
                    _child(BLOCKED, f"{DEPENDENCY_FAILED_NOTE}abc123")]
        self.assertEqual(project_status(children), FAILED)

    def test_a_child_blocked_for_any_other_reason_is_still_alive(self):
        """Planning re-offers those, so the project really is still
        going."""
        children = [_child(COMPLETED), _child(FAILED),
                    _child(BLOCKED, "step budget exhausted before the task was finished")]
        self.assertEqual(project_status(children), IN_PROGRESS)

    def test_an_untouched_sibling_still_keeps_it_alive(self):
        children = [_child(COMPLETED), _child(FAILED), _child(PENDING)]
        self.assertEqual(project_status(children), IN_PROGRESS)

    def test_all_completed_is_still_completed(self):
        self.assertEqual(project_status([_child(COMPLETED), _child(COMPLETED)]), COMPLETED)


def _patched_build_factories():
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None, guardian_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl,
                         guardian_config=guardian_config)
        factories = {name: factories[name] for name in ("bus", "ledger")}
        factories["planning"] = lambda: PlanningService(PlanningConfig())
        return factories

    return _build


class TheProjectReportsItselfFailedTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_dead_project_publishes_project_failed(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kernel = Kernel(LoadedConfig({"runtime": {"data_dir": tmp.name}}, None),
                        secrets=EnvSecretStore({}))
        patcher = mock.patch("simorgh.kernel.service.build_factories",
                             new=_patched_build_factories())
        patcher.start()
        self.addCleanup(patcher.stop)
        await kernel.boot()
        self.addAsyncCleanup(kernel.shutdown)

        events: list[Message] = []
        await kernel.bus.subscribe(topics.PROJECT_FAILED, lambda m: events.append(m) or asyncio.sleep(0))

        store = kernel._supervisor.services["planning"].service._store  # noqa: SLF001
        project = await store.create(kind="project", description="a goal", origin="human")
        first = await store.create(kind="patch", description="A", origin="human", parent_id=project.id)
        second = await store.create(kind="patch", description="B", origin="human", parent_id=project.id)
        third = await store.create(kind="patch", description="C", origin="human", parent_id=project.id,
                                   depends_on=(second.id,))
        for task in (first, second):
            if (await store.get(task.id)).status != AVAILABLE:
                await store.transition(task.id, AVAILABLE)
            await store.claim(task.id, "w1", 60.0)
            await store.transition(task.id, IN_PROGRESS)
        await store.transition(first.id, COMPLETED)

        await kernel.bus.publish(Message.new(
            topics.TASK_FAILED, source="orchestration", partition_key=f"task:{second.id}",
            payload={"task_id": second.id, "reason": "gave up", "terminal": True, "attempts": 9}))
        for _ in range(60):
            await asyncio.sleep(0.01)

        children = store.children(project.id)
        self.assertEqual(project_status(children), FAILED)
        self.assertEqual((await store.get(third.id)).status, BLOCKED)
        self.assertTrue(events, "a project nothing can advance must say it has finished")
        self.assertEqual(events[0].payload["project_id"], project.id)


if __name__ == "__main__":
    unittest.main()


class TheCommonerCaseIsAChildAlreadyBlockedTestCase(unittest.TestCase):
    """The `dependency_failed:` note is written only when the child's
    status CHANGES to blocked.

    A child already BLOCKED for another reason -- out of step budget,
    most often -- never gets it, because BLOCKED -> BLOCKED is not a
    legal transition. So the note-reading fix from the same morning
    missed the commoner case, and the project reported `blocked`
    forever with nothing able to move (observer, 2026-09-10).
    """

    def _task(self, id_: str, status: str, note: str = "", deps=()) -> Task:
        return Task(id=id_, kind="patch", description="d", status=status, note=note,
                    depends_on=deps)

    def test_a_child_blocked_for_another_reason_behind_a_failure_is_dead(self):
        children = [self._task("a", FAILED),
                    self._task("b", BLOCKED, "step budget exhausted", ("a",))]
        self.assertEqual(project_status(children), FAILED)

    def test_the_note_path_still_works(self):
        children = [self._task("a", FAILED),
                    self._task("b", BLOCKED, f"{DEPENDENCY_FAILED_NOTE}a", ("a",))]
        self.assertEqual(project_status(children), FAILED)

    def test_a_chain_two_deep_is_dead_all_the_way_down(self):
        children = [self._task("a", FAILED),
                    self._task("b", BLOCKED, "out of steps", ("a",)),
                    self._task("c", PENDING, deps=("b",))]
        self.assertEqual(project_status(children), FAILED)

    def test_an_independent_child_still_keeps_the_project_alive(self):
        children = [self._task("a", FAILED),
                    self._task("b", IN_PROGRESS)]
        self.assertEqual(project_status(children), IN_PROGRESS)

    def test_a_dependency_cycle_does_not_hang(self):
        children = [self._task("a", BLOCKED, "", ("b",)), self._task("b", BLOCKED, "", ("a",))]
        self.assertEqual(project_status(children), BLOCKED)
