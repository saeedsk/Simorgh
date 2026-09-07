"""Re-grounding + drift reaction, end to end through a real Kernel
running real Planning (docs/blueprint/subsystems/07-planning.md section
5.5, docs/blueprint/subsystems/12-reflection.md section 3's
`reflect.drift.detected`, Phase 4 roadmap item 4: "staleness check
before old children; `reflect.drift.detected`; `plan.revised` with
reasons").

This closes harness-06 gap #3 by name
(docs/KnowledgeBase/harness-06-gap-analysis-simorgh.md, "No drift/
re-grounding check across a multi-tick PROJECT_TASK"): "Nothing
currently re-checks, when a project's next child is picked up, whether
that child *still* serves the project's original goal given everything
that's happened since it was planned."

Before this fork, `reground.needs_check`/`reground.check` were never
called from `Service` at all (the `reground` module was imported and
unused), and `reflect.drift.detected` was published by Reflection but
consumed by nothing -- Planning's `consumes` tuple didn't include it.
Both gaps are closed here: a stale/drift-flagged child is genuinely
re-grounded via a real `cognition.think(purpose="reground")` round trip
before it becomes `available`, and a `reflect.drift.detected` for any
task in a project forces the project's next-available sibling through
that same check.
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
from simorgh.planning.config import Config as PlanningConfig
from simorgh.planning.service import Service as PlanningService

STEPS_TEXT = (
    "1. RESEARCH :: is the current retry backoff strategy adequate\n"
    "2. src/orchestrator/retry.py :: implement exponential backoff with jitter\n"
)


def _patched_build_factories(planning_config: PlanningConfig):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories = {name: factories[name] for name in ("bus", "ledger")}
        factories["planning"] = lambda: PlanningService(planning_config)
        return factories

    return _build


async def _pump(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


class _Collector:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def __call__(self, message: Message) -> None:
        self.messages.append(message)


class _FakeReground:
    """Answers only `cognition.think(purpose="reground")`; any other
    purpose gets no reply at all, so a test that reaches this fake by
    accident for something else fails loudly via a real timeout rather
    than silently getting an unrelated canned answer."""

    def __init__(self, bus, verdict_text: str) -> None:
        self._bus = bus
        self._verdict_text = verdict_text
        self.prompts: list[str] = []

    async def __call__(self, message: Message) -> None:
        if message.payload.get("purpose") != "reground":
            return
        self.prompts.append(message.payload["messages"][0]["content"])
        await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": self._verdict_text, "floor": False, "non_answer": False,
            "tool_calls": [], "provider": "fake", "cost_usd": 0.0, "tokens": 0,
        })


class _RegroundFlowTestCase(unittest.IsolatedAsyncioTestCase):
    async def _boot(self, planning_config: PlanningConfig) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = LoadedConfig({"runtime": {"data_dir": tmp.name}}, None)
        kernel = Kernel(config, secrets=EnvSecretStore({}))
        patch = mock.patch("simorgh.kernel.service.build_factories", new=_patched_build_factories(planning_config))
        patch.start()
        self.addCleanup(patch.stop)
        await kernel.boot()
        self.assertEqual(kernel.state.state, RUNNING)
        self.assertEqual(kernel._supervisor.services["planning"].status, "ok")  # noqa: SLF001
        self.addAsyncCleanup(kernel.shutdown)
        return kernel

    async def _propose_and_approve(self, kernel: Kernel) -> tuple[str, dict, dict]:
        """Creates+approves a 2-step project (one RESEARCH step, one
        dependent patch step) via the plan-mode Worker/Verification
        hand-played by hand (Verification isn't booted in this Kernel),
        and returns `(project_id, research_task, patch_task)`."""
        bus, ledger = kernel.bus, kernel.ledger
        plan_proposed = _Collector()
        plan_approved = _Collector()
        await bus.subscribe(topics.PLAN_PROPOSED, plan_proposed)
        await bus.subscribe(topics.PLAN_APPROVED, plan_approved)

        create_reply = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "project", "description": "improve outbound request resilience", "origin": "human"},
        ))
        project_id = create_reply.payload["task_id"]

        await bus.request(Message.new(
            topics.TASK_CLAIM, source="tester", payload={"task_id": project_id, "worker_id": "planner-1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_STARTED, source="tester", payload={"task_id": project_id, "worker_id": "planner-1"},
        ))
        await _pump()

        blob_ref = await ledger.put_blob(
            json.dumps({"steps_text": STEPS_TEXT}).encode("utf-8"), content_type="application/json",
        )
        await bus.publish(Message.new(
            topics.TASK_COMPLETED, source="tester",
            payload={"task_id": project_id, "result_summary": "decomposed", "artifacts": [blob_ref],
                     "verification_ref": None},
        ))
        await _pump()
        self.assertEqual(len(plan_proposed.messages), 1)
        plan_id = plan_proposed.messages[0].payload["plan_id"]

        await bus.publish(Message.new(
            topics.PLAN_REVIEWED, source="tester",
            payload={"plan_id": plan_id, "verdict": "approve", "checklist": []},
        ))
        await _pump()
        self.assertEqual(len(plan_approved.messages), 1)

        children_reply = await bus.request(Message.new(
            topics.TASK_LIST_REQUEST, source="tester", payload={"filter": {"parent_id": project_id}},
        ))
        children = {t["task_id"]: t for t in children_reply.payload["tasks"]}
        research = next(t for t in children.values() if t["kind"] == "research")
        patch = next(t for t in children.values() if t["kind"] == "patch")
        self.assertEqual(research["status"], "available")
        self.assertEqual(patch["status"], "pending")  # depends on research -- not stale-checked yet
        return project_id, research, patch

    async def _complete(self, kernel: Kernel, task_id: str, *, result_summary: str = "done") -> None:
        bus = kernel.bus
        await bus.request(Message.new(
            topics.TASK_CLAIM, source="tester", payload={"task_id": task_id, "worker_id": "w1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_STARTED, source="tester", payload={"task_id": task_id, "worker_id": "w1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_COMPLETED, source="tester",
            payload={"task_id": task_id, "result_summary": result_summary, "artifacts": [], "verification_ref": None},
        ))

    async def _task(self, kernel: Kernel, task_id: str) -> dict:
        reply = await kernel.bus.request(Message.new(topics.TASK_LIST_REQUEST, source="tester", payload={}))
        return next(t for t in reply.payload["tasks"] if t["task_id"] == task_id)


class TestStaleChildIsRegroundedBeforeBecomingAvailable(_RegroundFlowTestCase):
    async def test_a_no_verdict_supersedes_the_stale_child_with_a_replacement_and_plan_revised(self) -> None:
        # `-1.0` (never fresh, by real-wall-clock construction) makes
        # every child "stale" the instant it exists -- deterministic,
        # unlike racing a real clock against a tiny positive threshold.
        kernel = await self._boot(PlanningConfig(regrounding_age_seconds=-1.0, project_step_count=2))
        bus = kernel.bus
        fake = _FakeReground(bus, "Nothing has changed.\nSTILL_VALID: no -- the retry client was already rewritten; drop this step.")
        await bus.subscribe(topics.COGNITION_THINK, fake)
        plan_revised = _Collector()
        task_created = _Collector()
        await bus.subscribe(topics.PLAN_REVISED, plan_revised)
        await bus.subscribe(topics.TASK_CREATED, task_created)

        project_id, research, patch = await self._propose_and_approve(kernel)
        await self._complete(kernel, research["task_id"])
        await _pump(40)

        # the real cognition.think(purpose="reground") round trip actually happened
        self.assertEqual(len(fake.prompts), 1)
        self.assertIn("improve outbound request resilience", fake.prompts[0])  # the real project goal, not a stub

        old_patch = await self._task(kernel, patch["task_id"])
        self.assertEqual(old_patch["status"], "failed")
        self.assertIn("superseded", old_patch["note"])

        self.assertEqual(len(plan_revised.messages), 1)
        revised = plan_revised.messages[0].payload
        self.assertIn("already rewritten", revised["reason"])
        self.assertEqual(revised["diff"]["removed"], [patch["task_id"]])
        self.assertEqual(len(revised["diff"]["added"]), 1)
        replacement_id = revised["diff"]["added"][0]

        replacement = await self._task(kernel, replacement_id)
        self.assertEqual(replacement["status"], "available")
        self.assertEqual(replacement["parent_id"], project_id)
        self.assertIn("already rewritten", replacement["description"])

        # the replacement was announced like any other real task, not a
        # side channel only the store knows about
        created_ids = {m.payload["task_id"] for m in task_created.messages}
        self.assertIn(replacement_id, created_ids)


class TestFreshChildWithAYesVerdictProceedsNormally(_RegroundFlowTestCase):
    async def test_a_yes_verdict_makes_the_child_available_unchanged(self) -> None:
        kernel = await self._boot(PlanningConfig(regrounding_age_seconds=-1.0, project_step_count=2))
        bus = kernel.bus
        fake = _FakeReground(bus, "STILL_VALID: yes")
        await bus.subscribe(topics.COGNITION_THINK, fake)
        plan_revised = _Collector()
        await bus.subscribe(topics.PLAN_REVISED, plan_revised)

        _project_id, research, patch = await self._propose_and_approve(kernel)
        await self._complete(kernel, research["task_id"])
        await _pump(40)

        self.assertEqual(len(fake.prompts), 1)
        after = await self._task(kernel, patch["task_id"])
        self.assertEqual(after["status"], "available")  # same task, not superseded
        self.assertEqual(plan_revised.messages, [])


class TestDriftDetectedForcesRegroundingOfTheNextSibling(_RegroundFlowTestCase):
    async def test_reflect_drift_detected_on_one_task_forces_reground_of_the_next_available_sibling(self) -> None:
        # A large age threshold -- if this test's supersede happens, it is
        # because of the drift flag alone, never staleness.
        kernel = await self._boot(PlanningConfig(regrounding_age_seconds=999_999.0, project_step_count=2))
        bus = kernel.bus
        fake = _FakeReground(bus, "STILL_VALID: no -- the goal shifted; this step no longer applies.")
        await bus.subscribe(topics.COGNITION_THINK, fake)
        plan_revised = _Collector()
        await bus.subscribe(topics.PLAN_REVISED, plan_revised)

        project_id, research, patch = await self._propose_and_approve(kernel)

        # Reflection's real signal: some task in this project (the
        # research step, still in flight) is drifting.
        await bus.publish(Message.new(
            topics.REFLECT_DRIFT_DETECTED, source="reflection",
            payload={"kind": "goal", "evidence": "two scope crossings in a row", "recommendation": "reground",
                     "task_id": research["task_id"]},
        ))
        await _pump(10)

        # the drift signal alone is recorded as a plan revision with a
        # real reason, independent of whatever happens to the patch step
        self.assertEqual(len(plan_revised.messages), 1)
        self.assertIn("drift detected", plan_revised.messages[0].payload["reason"])
        self.assertIn("two scope crossings", plan_revised.messages[0].payload["reason"])

        # completing the research step would normally make the fresh
        # (age threshold huge, no sibling has failed) patch step
        # available with no check at all -- the drift flag is what forces
        # the reground round trip here.
        await self._complete(kernel, research["task_id"])
        await _pump(40)

        self.assertEqual(len(fake.prompts), 1)  # the reground call really happened
        old_patch = await self._task(kernel, patch["task_id"])
        self.assertEqual(old_patch["status"], "failed")
        self.assertIn("superseded", old_patch["note"])
        self.assertEqual(len(plan_revised.messages), 2)  # drift-flag revision + supersede revision


class TestNoCognitionPresentDegradesGracefully(_RegroundFlowTestCase):
    async def test_no_responder_times_out_and_the_child_still_becomes_available(self) -> None:
        # No `COGNITION_THINK` responder at all -- `BusCognitionCaller`'s
        # bounded timeout (8s) really elapses; a non-answer must never be
        # treated as evidence of drift (`01` section 4.5), so the child
        # proceeds to `available` exactly as if re-grounding had never
        # been wired in, and Planning must not hang or crash.
        kernel = await self._boot(PlanningConfig(regrounding_age_seconds=-1.0, project_step_count=2))
        plan_revised = _Collector()
        await kernel.bus.subscribe(topics.PLAN_REVISED, plan_revised)

        _project_id, research, patch = await self._propose_and_approve(kernel)
        await self._complete(kernel, research["task_id"])
        await asyncio.sleep(8.5)
        await _pump(40)

        after = await self._task(kernel, patch["task_id"])
        self.assertEqual(after["status"], "available")
        self.assertEqual(plan_revised.messages, [])
        health = await kernel._supervisor.services["planning"].service.health()  # noqa: SLF001
        self.assertEqual(health.status, "ok")


if __name__ == "__main__":
    unittest.main()
