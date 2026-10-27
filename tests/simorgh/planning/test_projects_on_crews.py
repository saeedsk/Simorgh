"""Stage 18 item 4: projects on crews (planning/crews.py).

With `[planning] project_crews = true` a project's ready plan nodes start
at once, one crew member each (`crew.spawn`), up to the per-project cap,
and each node's outcome is read from its member's `crew.report`. The crew
runtime here is a fake on the bus with a fixed delay per node: no model,
no Orchestration (tests/simorgh/orchestration/test_crew_spawn.py covers
that side, and the integration test at the bottom runs both)."""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.planning import planmode
from simorgh.planning.config import Config
from simorgh.planning.crews import claimer, outcome_of
from simorgh.planning.model import AVAILABLE, BLOCKED, COMPLETED, FAILED, PENDING, Step
from simorgh.planning.service import Service
from tests.simorgh.helpers import FakeClock


class _Logger:
    def __init__(self):
        self.lines = []

    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): self.lines.append((event, f))
    def error(self, event, **f): pass


class FakeCrewRuntime:
    """Answers `crew.spawn` and, after the node's delay, files `crew.report`.
    `delays` and `statuses` are keyed by a word in the node's brief."""

    def __init__(self, bus, *, delays: dict, statuses: dict | None = None) -> None:
        self._bus = bus
        self._delays = delays
        self._statuses = statuses or {}
        self.spawned: list[tuple[str, str, float]] = []   # (handle, brief, at)
        self.reported: list[tuple[str, float]] = []
        self.payloads: list[dict] = []
        self._running: set = set()

    async def start(self):
        await self._bus.subscribe(topics.CREW_SPAWN, self._on_spawn)

    def _key(self, brief: str, table: dict, default):
        return next((v for k, v in table.items() if k in brief), default)

    async def _on_spawn(self, message):
        p = message.payload
        self.payloads.append(dict(p))
        self.spawned.append((p["handle"], p["brief"], time.monotonic()))
        await self._bus.reply(message, type=topics.CREW_SPAWN_REPLY,
                              payload={"crew_id": p["context_id"], "handle": p["handle"]})
        task = asyncio.ensure_future(self._run(p))
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def _run(self, p):
        await asyncio.sleep(self._key(p["brief"], self._delays, 0.0))
        status = self._key(p["brief"], self._statuses, "ok")
        summary = "done: " + p["brief"][:40] if status == "ok" else "the member stopped: it broke"
        self.reported.append((p["handle"], time.monotonic()))
        await self._bus.publish(Message.new(topics.CREW_REPORT, source="orchestration", payload={
            "crew_id": p["context_id"], "handle": p["handle"],
            "report": {"status": status, "summary": summary, "steps": 1}}))


class ProjectsOnCrewsCase(unittest.IsolatedAsyncioTestCase):
    config = Config(project_crews=True, project_crew_spawn_timeout_s=0.5)

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(self.backend, source="planning", ledger=self.ledger, clock=self.clock)
        await self.bus.start()
        self.other = make_client(self.backend, source="orchestration", ledger=self.ledger, clock=self.clock)
        await self.other.start()
        self.logger = _Logger()
        self.ctx = Context(name="planning", instance_id="", run_id="test", mode="single", bus=self.bus,
                           ledger=self.ledger, config={}, secrets={}, clock=self.clock, logger=self.logger,
                           data_dir=Path(self._tmp.name) / "data")
        self.service = Service(self.config)
        await self.service.start(self.ctx)
        self.finished = asyncio.Event()
        self.project_events = []

        async def _done(message):
            self.project_events.append((message.type, dict(message.payload)))
            self.finished.set()
        await self.other.subscribe(topics.PROJECT_COMPLETED, _done)
        await self.other.subscribe(topics.PROJECT_FAILED, _done)
        self.offered = []

        async def _offered(message):
            self.offered.append(message.payload["task_id"])
        await self.other.subscribe(topics.TASK_AVAILABLE, _offered)

    async def asyncTearDown(self):
        await self.service.stop()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    @property
    def store(self):
        return self.service._store  # noqa: SLF001

    async def _project(self, steps: list[Step]) -> tuple[str, dict]:
        """A project whose plan was approved: the real `_approve_plan`."""
        project = await self.store.create(kind="project", description="the goal", origin="human",
                                          mode="plan", initial_status=AVAILABLE)
        state = planmode.PlanState(plan_id="p1", task_id=project.id, goal="the goal", steps=steps, risk="low")
        self.service._plans["p1"] = state  # noqa: SLF001
        self.service._plan_by_task[project.id] = "p1"  # noqa: SLF001
        await self.service._approve_plan(state, approved_by="auto")  # noqa: SLF001
        ids = {c.description.split()[0]: c.id for c in self.store.children(project.id)}
        return project.id, ids

    async def _wait_finished(self, timeout=5.0):
        await asyncio.wait_for(self.finished.wait(), timeout)
        for _ in range(20):
            await asyncio.sleep(0)


class ThreeIndependentNodes(ProjectsOnCrewsCase):
    async def test_they_run_together_and_the_project_takes_its_longest_node(self):
        runtime = FakeCrewRuntime(self.other, delays={"alpha": 0.3, "beta": 0.5, "gamma": 0.4})
        await runtime.start()
        started = time.monotonic()
        project, ids = await self._project([
            Step("s1", "research", "alpha: find the bin day", why="done when: the day is named"),
            Step("s2", "research", "beta: find the recycling day"),
            Step("s3", "research", "gamma: find the garden waste day"),
        ])
        await self._wait_finished()
        wall = time.monotonic() - started
        self.assertEqual(self.project_events[0][0], topics.PROJECT_COMPLETED)
        self.assertEqual(self.project_events[0][1]["done"], 3)
        # The longest node is 0.5 s and the three in turn are 1.2 s.
        self.assertLess(wall, 0.6 * 1.2, f"the nodes did not run together: {wall:.2f}s")
        self.assertGreaterEqual(wall, 0.5)
        self.assertEqual(sorted(h for h, _, _ in runtime.spawned), sorted(ids.values()))
        # Every node was spawned before the first one finished.
        first_report = min(at for _, at in runtime.reported)
        self.assertTrue(all(at < first_report for _, _, at in runtime.spawned))
        for child in self.store.children(project):
            self.assertEqual(child.status, COMPLETED)
        # None of them was ever offered to a Worker.
        self.assertFalse(set(self.offered) & set(ids.values()), self.offered)

    async def test_the_spawn_names_the_node_the_project_and_what_done_means(self):
        runtime = FakeCrewRuntime(self.other, delays={})
        await runtime.start()
        project, ids = await self._project([
            Step("s1", "patch", "alpha: add a docstring", subject="simorgh/planning/dag.py",
                 why="done when: the module has a docstring; the suite passes"),
        ])
        await self._wait_finished()
        p = runtime.payloads[0]
        self.assertEqual(p["handle"], ids["alpha:"])
        self.assertEqual(p["context_id"], project)
        self.assertEqual(p["agent"], "patch")
        self.assertTrue(p["plan_node"])
        self.assertEqual(p["subject"], "simorgh/planning/dag.py")
        self.assertEqual(p["acceptance"], ["the module has a docstring", "the suite passes"])
        self.assertIn("Done when: the module has a docstring", p["brief"])


class TheCap(ProjectsOnCrewsCase):
    config = Config(project_crews=True, project_crew_concurrency=2, project_crew_spawn_timeout_s=0.5)

    async def test_no_more_than_the_cap_run_at_once(self):
        runtime = FakeCrewRuntime(self.other, delays={"n": 0.2})
        await runtime.start()
        await self._project([Step(f"s{i}", "research", f"n{i}: part {i}") for i in range(4)])
        await self._wait_finished()
        events = sorted([(at, +1) for _, _, at in runtime.spawned] + [(at, -1) for _, at in runtime.reported])
        running = peak = 0
        for _, delta in events:
            running += delta
            peak = max(peak, running)
        self.assertEqual(peak, 2)
        self.assertEqual(self.project_events[0][1]["done"], 4)


class Dependencies(ProjectsOnCrewsCase):
    async def test_a_dependent_node_waits_for_its_dependency(self):
        runtime = FakeCrewRuntime(self.other, delays={"alpha": 0.3, "beta": 0.1, "gamma": 0.1})
        await runtime.start()
        project, ids = await self._project([
            Step("s1", "research", "alpha: find where the version lives"),
            Step("s2", "patch", "beta: bump the version", depends_on=("s1",)),
            Step("s3", "research", "gamma: read the changelog"),
        ])
        # Before alpha reports, beta is still pending and has not been spawned.
        await asyncio.sleep(0.15)
        self.assertEqual(self.store.index.tasks[ids["beta:"]].status, PENDING)
        self.assertNotIn(ids["beta:"], [h for h, _, _ in runtime.spawned])
        await self._wait_finished()
        spawned_at = {h: at for h, _, at in runtime.spawned}
        reported_at = dict(runtime.reported)
        self.assertGreaterEqual(spawned_at[ids["beta:"]], reported_at[ids["alpha:"]])
        self.assertLess(spawned_at[ids["gamma:"]], reported_at[ids["alpha:"]], "the independent node waited")
        self.assertEqual(self.project_events[0][0], topics.PROJECT_COMPLETED)


class AFailedNode(ProjectsOnCrewsCase):
    async def test_it_reports_blocks_its_dependents_and_the_project_ends(self):
        runtime = FakeCrewRuntime(self.other, delays={"alpha": 0.1, "gamma": 0.2},
                                  statuses={"alpha": "failed"})
        await runtime.start()
        failed = []

        async def _failed(message):
            failed.append(dict(message.payload))
        await self.other.subscribe(topics.TASK_FAILED, _failed)
        project, ids = await self._project([
            Step("s1", "research", "alpha: find where the version lives"),
            Step("s2", "patch", "beta: bump the version", depends_on=("s1",)),
            Step("s3", "research", "gamma: read the changelog"),
        ])
        await self._wait_finished()
        self.assertEqual(self.project_events[0][0], topics.PROJECT_FAILED)
        tasks = self.store.index.tasks
        self.assertEqual(tasks[ids["alpha:"]].status, FAILED)
        self.assertEqual(tasks[ids["beta:"]].status, BLOCKED)
        self.assertEqual(tasks[ids["gamma:"]].status, COMPLETED)
        self.assertNotIn(ids["beta:"], [h for h, _, _ in runtime.spawned])
        self.assertTrue(any(f["task_id"] == ids["alpha:"] and f["terminal"] for f in failed))
        self.assertIn("it broke", tasks[ids["alpha:"]].note)

    async def test_a_blocked_report_goes_through_the_retry_path(self):
        runtime = FakeCrewRuntime(self.other, delays={}, statuses={"alpha": "partial"})
        await runtime.start()
        project, ids = await self._project([Step("s1", "research", "alpha: a long job")])
        for _ in range(200):
            await asyncio.sleep(0.005)
            if self.store.index.tasks[ids["alpha:"]].status == BLOCKED:
                break
        node = self.store.index.tasks[ids["alpha:"]]
        self.assertEqual(node.status, BLOCKED)
        self.assertEqual(node.attempts, 1)
        self.assertFalse(self.finished.is_set())


class NobodyAnswers(ProjectsOnCrewsCase):
    config = Config(project_crews=True, project_crew_spawn_timeout_s=0.05)

    async def test_the_project_goes_back_to_the_queue(self):
        project, ids = await self._project([Step("s1", "research", "alpha: something")])
        for _ in range(100):
            await asyncio.sleep(0.01)
            if self.service._project_crews.fallback:  # noqa: SLF001
                break
        self.assertIn(project, self.service._project_crews.fallback)  # noqa: SLF001
        node = self.store.index.tasks[ids["alpha:"]]
        self.assertEqual(node.status, AVAILABLE)
        await self.service._scheduler.dispatch_ready()  # noqa: SLF001
        await asyncio.sleep(0.01)
        self.assertIn(node.id, self.offered)
        self.assertTrue(any(e == "planning.project_crew_fallback" for e, _ in self.logger.lines))


class AWorkerMayNotClaimACrewNode(ProjectsOnCrewsCase):
    async def test_the_claim_is_refused(self):
        project = await self.store.create(kind="project", description="goal", origin="human",
                                          mode="plan", initial_status=AVAILABLE)
        node = await self.store.create(kind="research", description="x", origin="project",
                                       parent_id=project.id, initial_status=AVAILABLE)
        reply = await self.other.request(Message.new(
            topics.TASK_CLAIM, source="orchestration",
            payload={"task_id": node.id, "worker_id": "w0", "accept_better": True}), timeout=2.0)
        self.assertFalse(reply.payload["granted"])
        self.assertEqual(reply.payload["reason"], "runs_on_crew")


class TheQueuesHoldsApply(ProjectsOnCrewsCase):
    """Review 2026-10-27: a crew node starts only when the queue would have
    offered it -- not while the system is paused, nor under `auto off`
    (a plan node's origin, `project`, is autonomous)."""

    async def _spawned_after(self, runtime, seconds=0.1):
        for _ in range(int(seconds / 0.01)):
            await asyncio.sleep(0.01)
        return [h for h, _, _ in runtime.spawned]

    async def test_nothing_starts_while_the_system_is_paused(self):
        runtime = FakeCrewRuntime(self.other, delays={})
        await runtime.start()
        self.service._scheduler.paused = True  # noqa: SLF001
        project, ids = await self._project([Step("s1", "research", "alpha: x")])
        await self.service._project_crews.dispatch()  # noqa: SLF001
        self.assertEqual(await self._spawned_after(runtime), [])
        self.service._scheduler.paused = False  # noqa: SLF001
        await self.service._project_crews.dispatch()  # noqa: SLF001
        await self._wait_finished()
        self.assertEqual([h for h, _, _ in runtime.spawned], [ids["alpha:"]])

    async def test_nothing_starts_under_auto_off(self):
        runtime = FakeCrewRuntime(self.other, delays={})
        await runtime.start()
        self.service._scheduler.autonomous_paused = True  # noqa: SLF001
        await self._project([Step("s1", "research", "alpha: x")])
        await self.service._project_crews.dispatch()  # noqa: SLF001
        self.assertEqual(await self._spawned_after(runtime), [])
        self.service._scheduler.autonomous_paused = False  # noqa: SLF001
        await self.service._project_crews.dispatch()  # noqa: SLF001
        await self._wait_finished()
        self.assertEqual(self.project_events[0][0], topics.PROJECT_COMPLETED)


class AHumanTaskDoesNotPreemptACrewNode(ProjectsOnCrewsCase):
    # A project weighs as much as a human by default, so only a deployment
    # that lowers it reaches the preemption at all.
    config = Config(project_crews=True, project_crew_spawn_timeout_s=0.5,
                    priority_weights={"human": 3, "project": 1, "benchmark": 2, "reflection": 2,
                                      "assistant": 2, "curiosity": 1, "research": 1})

    async def test_the_running_node_is_left_alone(self):
        runtime = FakeCrewRuntime(self.other, delays={"alpha": 0.3})
        await runtime.start()
        cancels = []

        async def _cancel(message):
            cancels.append(dict(message.payload))
        await self.other.subscribe(topics.TASK_CANCEL, _cancel)
        project, ids = await self._project([Step("s1", "research", "alpha: x")])
        for _ in range(50):
            await asyncio.sleep(0.01)
            if runtime.spawned:
                break
        await self.other.publish(Message.new(topics.TASK_STARTED, source="orchestration",
                                             payload={"task_id": ids["alpha:"], "worker_id": "w0"}))
        for _ in range(20):
            await asyncio.sleep(0.005)
        self.assertEqual(self.store.index.tasks[ids["alpha:"]].status, "in_progress")
        human = await self.store.create(kind="research", description="mine now", origin="human",
                                        initial_status=AVAILABLE)
        await self.service._preempt_for(human)  # noqa: SLF001
        await asyncio.sleep(0.02)
        self.assertEqual(cancels, [])
        await self._wait_finished()
        self.assertEqual(self.project_events[0][0], topics.PROJECT_COMPLETED)


class OffByDefault(unittest.TestCase):
    def test_the_switch_is_off_and_reads_from_the_mapping(self):
        self.assertFalse(Config().project_crews)
        cfg = Config.from_mapping({"project_crews": True, "project_crew_concurrency": 3})
        self.assertTrue(cfg.project_crews)
        self.assertEqual(cfg.project_crew_concurrency, 3)

    def test_outcomes(self):
        self.assertEqual(outcome_of({"status": "ok", "summary": "x"})[0], "completed")
        self.assertEqual(outcome_of({"status": "partial", "summary": "step budget exhausted\nmore"})[:2],
                         ("blocked", "step budget exhausted"))
        self.assertEqual(outcome_of({"status": "cancelled", "summary": ""})[0], "failed")
        self.assertEqual(claimer("p"), "crew:p")


if __name__ == "__main__":
    unittest.main()
