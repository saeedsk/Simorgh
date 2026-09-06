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

    def _build(*, bus_client, ledger_client):
        # `real()` now wires every subsystem (docs/EVOLUTION.md milestone
        # 103) -- when this test was first written it returned only
        # bus/ledger, so filtering down to that plus `planning` itself is
        # what actually keeps this "no cognition, guardian, execution, or
        # any other Phase 1 subsystem present" scenario true, rather than
        # relying on `real()`'s own (now much larger) output.
        factories = real(bus_client=bus_client, ledger_client=ledger_client)
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

    async def test_second_task_create_with_similar_description_is_deduped(self) -> None:
        bus = self.kernel.bus
        first = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "patch", "description": "add retry jitter to the HTTP client", "origin": "human"},
        ))
        second = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "patch", "description": "add jitter to HTTP client retries", "origin": "human"},
        ))
        self.assertEqual(second.payload.get("deduplicated_against"), first.payload["task_id"])

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
