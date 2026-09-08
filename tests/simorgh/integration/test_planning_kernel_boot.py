"""Planning as a real kernel `Service` (docs/blueprint/subsystems/07-planning.md
section 9): boots via the same `Supervisor.start_layer` composition root
as `test_kernel_boot_two_toy_subsystems.py`, with only `bus`/`ledger`
(Phase 0) plus `planning` itself in the factory map -- no cognition,
guardian, execution, or any other Phase 1 subsystem is present, which is
exactly the "graceful operation with no sibling subsystem" scenario the
spec's section 8 degradation rules exist for.

Covers the four things the build directive asked this integration test
to prove: task create -> claim -> complete -> projection; project
creation -> decompose -> children + rollup; dependency ordering (a child
stays `pending` until its dependency completes); and that Planning does
not hang or crash when `cognition.think` has no responder.
"""

from __future__ import annotations

import asyncio
import json
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
from simorgh.planning.service import Service as PlanningService


def _patched_build_factories():
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None, guardian_config=None):
        # `real()` now wires every subsystem (docs/EVOLUTION.md milestone
        # 103) -- when this test was first written it returned only
        # bus/ledger, so filtering down to that plus `planning` itself is
        # what actually keeps this "no cognition, guardian, execution, or
        # any other Phase 1 subsystem present" scenario true, rather than
        # relying on `real()`'s own (now much larger) output.
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl, guardian_config=guardian_config)
        factories = {name: factories[name] for name in ("bus", "ledger")}
        factories["planning"] = lambda: PlanningService()
        return factories

    return _build


async def _pump(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


class _Collector:
    """Captures every delivery of one broadcast topic, for topics whose
    handler is a publish, not a reply (task.created, plan.proposed,
    plan.approved, project.completed) -- request/reply is asserted
    directly on the reply message instead."""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def __call__(self, message: Message) -> None:
        self.messages.append(message)


class TestPlanningBootsAsARealKernelService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        config = LoadedConfig({"runtime": {"data_dir": self._tmp.name}}, None)
        # Real wall clock, deliberately -- the kernel's own background
        # `Scheduler` advances the injected clock via real `await
        # clock.sleep()` calls in a tight loop; paired with a `FakeClock`
        # (whose `.sleep()` jumps virtual time instead of waiting) that
        # runs virtual time thousands of seconds ahead within a handful of
        # `asyncio.sleep(0)` pumps, expiring every lease almost instantly.
        # This suite's lease window (600s) is only ever compared against
        # real elapsed time, so the default wall clock is what the test
        # actually needs.
        self.kernel = Kernel(config, secrets=EnvSecretStore({}))
        self._patch = mock.patch("simorgh.kernel.service.build_factories", new=_patched_build_factories())
        self._patch.start()
        await self.kernel.boot()
        self.assertEqual(self.kernel.state.state, RUNNING)
        self.assertEqual(self.kernel._supervisor.services["planning"].status, "ok")  # noqa: SLF001

    async def asyncTearDown(self) -> None:
        await self.kernel.shutdown()
        self._patch.stop()
        self._tmp.cleanup()

    async def test_task_create_claim_complete_projection(self) -> None:
        bus = self.kernel.bus
        create_reply = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "patch", "description": "fix the flaky retry test", "origin": "human"},
        ))
        task_id = create_reply.payload["task_id"]
        self.assertNotIn("deduplicated_against", create_reply.payload)

        claim_reply = await bus.request(Message.new(
            topics.TASK_CLAIM, source="tester", payload={"task_id": task_id, "worker_id": "w1"},
        ))
        self.assertTrue(claim_reply.payload["granted"])
        self.assertEqual(claim_reply.payload["task"]["status"], "claimed")

        await bus.publish(Message.new(
            topics.TASK_STARTED, source="tester", payload={"task_id": task_id, "worker_id": "w1"},
        ))
        await _pump()

        await bus.publish(Message.new(
            topics.TASK_COMPLETED, source="tester",
            payload={"task_id": task_id, "result_summary": "fixed it", "artifacts": [], "verification_ref": None},
        ))
        await _pump()

        list_reply = await bus.request(Message.new(topics.TASK_LIST_REQUEST, source="tester", payload={}))
        [task] = [t for t in list_reply.payload["tasks"] if t["task_id"] == task_id]
        self.assertEqual(task["status"], "completed")

    async def test_a_new_task_is_offered_to_workers_immediately_not_only_on_the_idle_tick(self) -> None:
        """Live-caught by the CLI end-to-end test, 2026-09-07: the only
        caller of `Scheduler.dispatch_ready` was the idle-tick handler,
        and the Kernel's idle tick needs `idle_threshold_s` (10s) of no
        percepts first -- which every typed line resets. A task typed at
        the REPL sat unclaimed for at least ten seconds, and someone who
        kept typing could starve their own work indefinitely."""
        bus = self.kernel.bus
        available: list[str] = []
        sub = await bus.subscribe(
            topics.TASK_AVAILABLE, lambda m: available.append(m.payload["task_id"]) or asyncio.sleep(0),
        )
        create_reply = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "patch", "description": "make the dispatcher prompt", "origin": "human"},
        ))
        await _pump()
        await sub.unsubscribe()
        self.assertIn(create_reply.payload["task_id"], available)

    async def test_second_autonomous_task_create_with_similar_description_is_deduped(self) -> None:
        bus = self.kernel.bus
        first = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "patch", "description": "add retry jitter to the HTTP client", "origin": "curiosity"},
        ))
        second = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "patch", "description": "add jitter to HTTP client retries", "origin": "curiosity"},
        ))
        self.assertEqual(second.payload.get("deduplicated_against"), first.payload["task_id"])

    async def test_a_humans_similar_request_is_never_deduped(self) -> None:
        """Live-caught (2026-09-07): three different `improve` requests
        all came back as the first one's id and the later two never ran.
        Fuzzy dedupe is for the autonomous streams; a human asking is
        authoritative (`planning/intake.py::_find_duplicate`)."""
        bus = self.kernel.bus
        first = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "patch", "description": "add retry jitter to the HTTP client", "origin": "human"},
        ))
        second = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "patch", "description": "add jitter to HTTP client retries", "origin": "human"},
        ))
        self.assertNotIn("deduplicated_against", second.payload)
        self.assertNotEqual(second.payload["task_id"], first.payload["task_id"])

    async def test_project_decompose_children_and_dependency_ordering(self) -> None:
        bus, ledger = self.kernel.bus, self.kernel.ledger
        plan_proposed = _Collector()
        plan_approved = _Collector()
        await bus.subscribe(topics.PLAN_PROPOSED, plan_proposed)
        await bus.subscribe(topics.PLAN_APPROVED, plan_approved)

        create_reply = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "project", "description": "improve outbound request resilience", "origin": "human"},
        ))
        project_id = create_reply.payload["task_id"]

        # The project task itself must already be dispatchable (available,
        # not stuck pending) -- it has no depends_on of its own.
        list_reply = await bus.request(Message.new(topics.TASK_LIST_REQUEST, source="tester", payload={}))
        [project] = [t for t in list_reply.payload["tasks"] if t["task_id"] == project_id]
        self.assertEqual(project["status"], "available")

        # A real planner worker claims the project like any other task
        # before it does the decomposition work.
        await bus.request(Message.new(
            topics.TASK_CLAIM, source="tester", payload={"task_id": project_id, "worker_id": "planner-1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_STARTED, source="tester", payload={"task_id": project_id, "worker_id": "planner-1"},
        ))
        await _pump()

        steps_text = (
            "1. RESEARCH :: is the current retry backoff strategy adequate\n"
            "2. src/orchestrator/retry.py :: implement exponential backoff with jitter\n"
        )
        blob_ref = await ledger.put_blob(
            json.dumps({"steps_text": steps_text}).encode("utf-8"), content_type="application/json",
        )
        await bus.publish(Message.new(
            topics.TASK_COMPLETED, source="tester",
            payload={"task_id": project_id, "result_summary": "decomposed", "artifacts": [blob_ref],
                     "verification_ref": None},
        ))
        await _pump()
        self.assertEqual(len(plan_proposed.messages), 1)
        proposed = plan_proposed.messages[0].payload
        self.assertEqual(len(proposed["steps"]), 2)
        plan_id = proposed["plan_id"]

        # medium risk + "approve" auto-approves (config.auto_approve_max_risk == "medium")
        await bus.publish(Message.new(
            topics.PLAN_REVIEWED, source="tester",
            payload={"plan_id": plan_id, "verdict": "approve", "checklist": []},
        ))
        await _pump()
        self.assertEqual(len(plan_approved.messages), 1)
        children_ids = plan_approved.messages[0].payload["children"]
        self.assertEqual(len(children_ids), 2)

        children_reply = await bus.request(Message.new(
            topics.TASK_LIST_REQUEST, source="tester", payload={"filter": {"parent_id": project_id}},
        ))
        children = {t["task_id"]: t for t in children_reply.payload["tasks"]}
        self.assertEqual(set(children), set(children_ids))
        research = next(t for t in children.values() if t["kind"] == "research")
        patch = next(t for t in children.values() if t["kind"] == "patch")

        # dependency ordering: the patch step depends on the research step,
        # so it must start pending, not available, even though its own
        # project was just approved.
        self.assertEqual(research["status"], "available")
        self.assertEqual(patch["status"], "pending")
        self.assertIn(research["task_id"], patch["depends_on"])

        rollup_before = next(p for p in children_reply.payload["projects"] if p["project_id"] == project_id)
        # neither child has started yet (one available, one pending on it)
        # -- `project_status` only promotes to in_progress once something
        # is actually IN_PROGRESS or COMPLETED (rollup.py).
        self.assertEqual(rollup_before["rollup"], "pending")

        # complete the research step -> propagation must make the
        # dependent patch step available.
        await bus.request(Message.new(
            topics.TASK_CLAIM, source="tester", payload={"task_id": research["task_id"], "worker_id": "w1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_STARTED, source="tester",
            payload={"task_id": research["task_id"], "worker_id": "w1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_COMPLETED, source="tester",
            payload={"task_id": research["task_id"], "result_summary": "backoff should use jitter",
                     "artifacts": [], "verification_ref": None},
        ))
        await _pump()

        after_reply = await bus.request(Message.new(
            topics.TASK_LIST_REQUEST, source="tester", payload={"filter": {"parent_id": project_id}},
        ))
        after = {t["task_id"]: t for t in after_reply.payload["tasks"]}
        self.assertEqual(after[patch["task_id"]]["status"], "available")

        # finish the whole project -> rollup projects to completed.
        await bus.request(Message.new(
            topics.TASK_CLAIM, source="tester", payload={"task_id": patch["task_id"], "worker_id": "w1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_STARTED, source="tester", payload={"task_id": patch["task_id"], "worker_id": "w1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_COMPLETED, source="tester",
            payload={"task_id": patch["task_id"], "result_summary": "added jitter", "artifacts": [],
                     "verification_ref": None},
        ))
        await _pump()

        final_reply = await bus.request(Message.new(topics.TASK_LIST_REQUEST, source="tester", payload={}))
        rollup_after = next(p for p in final_reply.payload["projects"] if p["project_id"] == project_id)
        self.assertEqual(rollup_after["rollup"], "completed")
        self.assertEqual(rollup_after["done"], 2)

    async def test_plan_revision_degrades_gracefully_with_no_cognition_present(self) -> None:
        # Exercises `_on_plan_reviewed`'s "revise" branch, which calls
        # `cognition.think` over the bus (spec section 8: "Provider down
        # ... decomposition returns no steps"). No cognition subsystem is
        # registered in this kernel at all, so the bounded-timeout request
        # must time out and Planning must swallow it -- no crash, no hang,
        # no plan.revised.
        bus, ledger = self.kernel.bus, self.kernel.ledger
        plan_proposed = _Collector()
        plan_revised = _Collector()
        await bus.subscribe(topics.PLAN_PROPOSED, plan_proposed)
        await bus.subscribe(topics.PLAN_REVISED, plan_revised)

        create_reply = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "project", "description": "reduce cold-start latency", "origin": "human"},
        ))
        project_id = create_reply.payload["task_id"]
        blob_ref = await ledger.put_blob(
            json.dumps({"steps_text": "1. src/orchestrator/boot.py :: lazy-import heavy deps\n"}).encode("utf-8"),
            content_type="application/json",
        )
        await bus.publish(Message.new(
            topics.TASK_COMPLETED, source="tester",
            payload={"task_id": project_id, "result_summary": "decomposed", "artifacts": [blob_ref],
                     "verification_ref": None},
        ))
        await _pump()
        plan_id = plan_proposed.messages[0].payload["plan_id"]

        await bus.publish(Message.new(
            topics.PLAN_REVIEWED, source="tester",
            payload={"plan_id": plan_id, "verdict": "revise", "checklist": [], "feedback": "needs another step"},
        ))
        # `BusCognitionCaller`'s bounded timeout (8s) really elapses here --
        # this is the one place the suite pays for proving Planning does
        # not hang forever with no cognition subsystem present.
        await asyncio.sleep(8.5)
        await _pump()

        self.assertEqual(plan_revised.messages, [])  # degraded to "no revision", not a crash
        health = await self.kernel._supervisor.services["planning"].service.health()  # noqa: SLF001
        self.assertEqual(health.status, "ok")


if __name__ == "__main__":
    unittest.main()


class TestABlockedOutcomeIsHeardOnce(unittest.IsolatedAsyncioTestCase):
    """Planning answers a Worker's `task.blocked` by parking the task and
    publishing `task.blocked` itself -- on the same topic. It then heard
    its own broadcast as a fresh outcome and parked the task again, and
    again: 466 "blocked" lines on screen from one task before the kernel
    shut down (watched trial, 2026-09-07). One outcome, one broadcast."""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        config = LoadedConfig({"runtime": {"data_dir": self._tmp.name}}, None)
        self.kernel = Kernel(config, secrets=EnvSecretStore({}))
        self._patch = mock.patch("simorgh.kernel.service.build_factories", new=_patched_build_factories())
        self._patch.start()
        await self.kernel.boot()

    async def asyncTearDown(self) -> None:
        await self.kernel.shutdown()
        self._patch.stop()
        self._tmp.cleanup()

    async def test_one_worker_report_yields_one_planning_broadcast(self) -> None:
        bus = self.kernel.bus
        create_reply = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "patch", "description": "do the thing", "origin": "human"},
        ))
        task_id = create_reply.payload["task_id"]
        await bus.request(Message.new(
            topics.TASK_CLAIM, source="tester", payload={"task_id": task_id, "worker_id": "w1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_STARTED, source="tester", payload={"task_id": task_id, "worker_id": "w1"},
        ))
        await _pump()

        heard = _Collector()
        sub = await bus.subscribe(topics.TASK_BLOCKED, heard)
        await bus.publish(Message.new(
            topics.TASK_BLOCKED, source="orchestration",
            payload={"task_id": task_id, "reason": "step budget exhausted"},
        ))
        await _pump(200)
        await sub.unsubscribe()

        from_planning = [m for m in heard.messages if m.source != "orchestration"]
        self.assertEqual(len(from_planning), 1, [m.source for m in heard.messages])
        list_reply = await bus.request(Message.new(topics.TASK_LIST_REQUEST, source="tester", payload={}))
        [task] = [t for t in list_reply.payload["tasks"] if t["task_id"] == task_id]
        self.assertEqual(task["status"], "blocked")
        self.assertEqual(task.get("attempts"), 1)


class TestAContinuationComesBackSoonWithItsOwnCap(unittest.IsolatedAsyncioTestCase):
    """A task that only ran out of steps is offered again after
    `continuation_delay_seconds`, not the full blocked delay; and a
    task's own `max_steps` survives create -> store -> claim reply so the
    worker can honour it."""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        config = LoadedConfig({"runtime": {"data_dir": self._tmp.name}}, None)
        self.kernel = Kernel(config, secrets=EnvSecretStore({}))
        self._patch = mock.patch("simorgh.kernel.service.build_factories", new=_patched_build_factories())
        self._patch.start()
        await self.kernel.boot()

    async def asyncTearDown(self) -> None:
        await self.kernel.shutdown()
        self._patch.stop()
        self._tmp.cleanup()

    async def _claimed_task(self, **extra) -> str:
        bus = self.kernel.bus
        reply = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "patch", "description": "a long refactor", "origin": "human", **extra},
        ))
        task_id = reply.payload["task_id"]
        claim = await bus.request(Message.new(
            topics.TASK_CLAIM, source="tester", payload={"task_id": task_id, "worker_id": "w1"},
        ))
        self.claim = claim.payload
        await bus.publish(Message.new(topics.TASK_STARTED, source="tester", payload={"task_id": task_id, "worker_id": "w1"}))
        await _pump()
        return task_id

    async def test_the_step_cap_rides_through_to_the_claim(self) -> None:
        await self._claimed_task(max_steps=40)
        self.assertEqual(self.claim["task"]["max_steps"], 40)

    async def test_no_cap_is_absent_not_zero(self) -> None:
        await self._claimed_task()
        self.assertIsNone(self.claim["task"].get("max_steps"))

    async def test_running_out_of_steps_is_a_short_retry_and_anything_else_is_long(self) -> None:
        planning = self.kernel._supervisor.services["planning"].service  # noqa: SLF001
        heard = _Collector()
        sub = await self.kernel.bus.subscribe(topics.TASK_BLOCKED, heard)
        for reason in ("step budget exhausted before the task was finished", "verification failed after max revisions"):
            task_id = await self._claimed_task()
            await self.kernel.bus.publish(Message.new(
                topics.TASK_BLOCKED, source="orchestration", payload={"task_id": task_id, "reason": reason},
            ))
            await _pump(100)
        await sub.unsubscribe()
        delays = [m.payload["retry_after"] for m in heard.messages if m.source != "orchestration"]
        self.assertEqual(delays, [planning.config.continuation_delay_seconds, planning.config.blocked_retry_delay_seconds])
        self.assertLess(planning.config.continuation_delay_seconds, 60)


class TestAProjectProducesChildren(unittest.IsolatedAsyncioTestCase):
    """The blocker that survived three hunts.

    `refresh_lease` is the last statement before `plan.proposed` is
    published, and it passed a stale cursor as a compare-and-swap -- the
    identical bug fixed in `transition` on 2026-09-07 and never applied
    to the other four writes. The Worker appends a `task.step` per step,
    so Planning's cursor is stale by exactly that many, the append raised
    `ConflictError: expected head 5, actual 10`, the bus swallowed it,
    and `plan.proposed` was NEVER PUBLISHED. No project had ever produced
    a child task (observer, 2026-09-08).
    """

    PLAN = (
        "1. RESEARCH :: which modules in simorgh/interface/ lack a docstring\n"
        "2. simorgh/interface/api.py :: add a one-line module docstring\n"
        "3. simorgh/interface/vitals.py :: add a one-line module docstring\n"
    )

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        config = LoadedConfig({"runtime": {"data_dir": self._tmp.name}}, None)
        self.kernel = Kernel(config, secrets=EnvSecretStore({}))
        self._patch = mock.patch("simorgh.kernel.service.build_factories", new=_patched_build_factories())
        self._patch.start()
        await self.kernel.boot()
        self.planning = self.kernel._supervisor.services["planning"].service  # noqa: SLF001

    async def asyncTearDown(self) -> None:
        await self.kernel.shutdown()
        self._patch.stop()
        self._tmp.cleanup()

    async def _project_with_steps(self):
        """A project whose stream already carries the Worker's steps --
        which is what made Planning's cursor stale."""
        import json

        from simorgh.contracts.envelope import Event

        store = self.planning._store  # noqa: SLF001
        task = await store.create(kind="project", description="add missing docstrings",
                                  origin="human", mode="plan", initial_status="available")
        await store.claim(task.id, "w1", 600.0)
        await store.transition(task.id, "in_progress")
        for n in range(5):
            await self.kernel.ledger.append(f"task:{task.id}", Event(
                stream=f"task:{task.id}", type=topics.TASK_STEP, ts=0.0, trace_id=task.id,
                causation_id=None, payload={"task_id": task.id, "step_no": n + 1,
                                            "phase": "act", "summary": f"step {n + 1}", "ok": True}))
        blob = await self.kernel.ledger.put_blob(
            json.dumps({"goal": "g", "steps_text": self.PLAN}).encode(), content_type="application/json")
        return await store.get(task.id), blob

    async def test_a_stale_cursor_no_longer_stops_the_plan_being_proposed(self) -> None:
        proposed = _Collector()
        sub = await self.kernel.bus.subscribe(topics.PLAN_PROPOSED, proposed)
        task, blob = await self._project_with_steps()
        await self.planning._on_plan_worker_result(task, [blob])  # noqa: SLF001
        await _pump(50)
        await sub.unsubscribe()
        self.assertEqual(len(proposed.messages), 1, "plan.proposed was never published")
        self.assertEqual(len(proposed.messages[0].payload["steps"]), 3)

    async def test_an_approved_plan_creates_child_tasks_with_a_parent(self) -> None:
        proposed = _Collector()
        sub = await self.kernel.bus.subscribe(topics.PLAN_PROPOSED, proposed)
        task, blob = await self._project_with_steps()
        await self.planning._on_plan_worker_result(task, [blob])  # noqa: SLF001
        await _pump(50)
        await sub.unsubscribe()

        await self.kernel.bus.publish(self.kernel.bus.new(topics.PLAN_REVIEWED, {
            "plan_id": proposed.messages[0].payload["plan_id"], "verdict": "approve",
            "checklist": [], "risks": [], "feedback": "",
        }))
        for _ in range(200):
            await asyncio.sleep(0.01)
            children = [t for t in self.planning._store.index.tasks.values() if t.parent_id == task.id]  # noqa: SLF001
            if children:
                break

        children = [t for t in self.planning._store.index.tasks.values() if t.parent_id == task.id]  # noqa: SLF001
        self.assertEqual(len(children), 3, "a project must decompose into its steps")
        self.assertEqual({t.kind for t in children}, {"research", "patch"})
        self.assertTrue(all(t.parent_id == task.id for t in children))

    async def test_a_plan_with_no_usable_steps_frees_the_task_instead_of_freezing_it(self) -> None:
        """`in_progress -> pending` is not a legal transition, so this
        raised unconditionally and froze the project silently."""
        import json

        task, _ = await self._project_with_steps()
        blob = await self.kernel.ledger.put_blob(
            json.dumps({"goal": "g", "steps_text": "no steps here at all"}).encode(),
            content_type="application/json")
        await self.planning._on_plan_worker_result(task, [blob])  # noqa: SLF001
        await _pump(20)
        self.assertEqual((await self.planning._store.get(task.id)).status, "available")  # noqa: SLF001
