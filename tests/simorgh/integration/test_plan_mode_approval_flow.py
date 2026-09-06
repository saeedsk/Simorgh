"""Plan Mode's approval policy, end-to-end, through a real Kernel running
real Planning + Verification (docs/blueprint/subsystems/07-planning.md
section 5.4, docs/blueprint/subsystems/10-verification.md section 5.5,
docs/blueprint/02-system-architecture.md Flow 3, and Phase 4 roadmap item
4.1: "Flow 3 with human prompt when risk >= high, auto otherwise; plan
review by Verification").

This closes harness-06 gap #1 by name
(docs/KnowledgeBase/harness-06-gap-analysis.md): "No genuine Plan-Mode-
style separation between 'explore/propose' and 'execute' for a single
task." `test_planning_kernel_boot.py` already proves Planning's own
session mechanics (claim/decompose/propose/rollup) with Verification
faked out by hand-publishing `plan.reviewed`; what it does *not* prove --
and what this file adds -- is that the gate is real: a `plan.proposed`
only ever becomes children after an independent subsystem (Verification)
has actually reviewed it, that a high-risk plan's children exist if and
only if a genuine external `ui.prompt.answered` says so (never before,
never automatically), that a low/medium-risk plan needs no human at all,
and that an unanswered high-risk prompt does not hang the project forever
-- past `human_approval_timeout_seconds` the task is paused instead
(the same graceful-degradation guarantee Guardian-down/Verification-
absent already get elsewhere in this suite).

Two pieces of real (not merely tested-in-isolation) production code are
exercised here that no other test reaches end-to-end:
  - `simorgh/planning/intake.py`'s `risk` pass-through from `task.create`
    (without it a project can never be created above "medium", so the
    `risk >= high` branch of the policy would be unreachable through any
    real message, not just untested).
  - `simorgh/planning/service.py`'s `_reconsider_awaiting_human` timeout
    scan (`system.tick.second`), paired with the lease extended in
    `_on_plan_worker_result` so the project task can't spuriously become
    reclaimable while a decision is still pending.
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
from simorgh.verification.service import VerificationService

STEPS_TEXT = "1. src/orchestrator/retry.py :: add exponential backoff with jitter\n"


def _patched_build_factories(planning_config: PlanningConfig):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False):
        # Only bus/ledger (Phase 0) plus the two subsystems this scenario
        # is actually about -- Planning and Verification -- exactly like
        # test_planning_kernel_boot.py's `_patched_build_factories`, so
        # this stays "no Orchestration, no Guardian, no Cognition" and the
        # test drives the plan-mode Worker's and the human's messages by
        # hand.
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories = {name: factories[name] for name in ("bus", "ledger")}
        factories["planning"] = lambda: PlanningService(planning_config)
        factories["verification"] = lambda: VerificationService()
        return factories

    return _build


async def _pump(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


class _Collector:
    """Captures every delivery of one broadcast topic (same helper as
    test_planning_kernel_boot.py's `_Collector`)."""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def __call__(self, message: Message) -> None:
        self.messages.append(message)


class _FakeCognitionThink:
    """Answers Verification's `cognition.think(purpose="review")` goal-
    coverage question with an unambiguous YES. There is no real Cognition
    subsystem in this Kernel; without some responder, `review_plan`
    degrades to `insufficient_evidence` (the honest-degradation path
    `test_planning_kernel_boot.py`'s revision test already covers) instead
    of reaching a real `approve` verdict, which is what this file needs to
    exercise the risk-routing policy itself. Every field the schema
    requires (`cognition.think.reply.v1.json`) must be present or the
    envelope's own contract validation rejects the reply outright and
    Verification silently times out instead -- the fake needs the same
    completeness a real Cognition subsystem's wire format would have.
    """

    def __init__(self, bus) -> None:
        self._bus = bus

    async def __call__(self, message: Message) -> None:
        await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": "YES, every step ties back to the stated goal.", "floor": False, "non_answer": False,
            "tool_calls": [], "provider": "fake", "cost_usd": 0.0, "tokens": 0,
        })


class _FakeGuardianReview:
    """Answers Verification's `guardian.review` (the per-step protected-
    subject check inside `review_plan`) with an unconditional approval --
    without this, each test would pay Verification's real
    `action_timeout_seconds` (5s) waiting for a responder that was never
    going to be part of this scenario (Guardian isn't under test here)."""

    def __init__(self, bus) -> None:
        self._bus = bus

    async def __call__(self, message: Message) -> None:
        await self._bus.reply(message, type=topics.GUARDIAN_REVIEW_REPLY, payload={
            "approved": True, "reasons": [], "layers_run": [],
        })


class _PlanModeApprovalFlowTestCase(unittest.IsolatedAsyncioTestCase):
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
        self.assertEqual(kernel._supervisor.services["verification"].status, "ok")  # noqa: SLF001
        self.addAsyncCleanup(kernel.shutdown)
        await kernel.bus.subscribe(topics.COGNITION_THINK, _FakeCognitionThink(kernel.bus))
        await kernel.bus.subscribe(topics.GUARDIAN_REVIEW, _FakeGuardianReview(kernel.bus))
        return kernel

    async def _propose(self, kernel: Kernel, *, risk: str, description: str) -> tuple[str, dict]:
        """Creates a project task at the given risk (via `task.create`'s
        own `risk` field), then plays the plan-mode Worker's part by hand
        (claim -> started -> completed with a plan artifact) up through
        `plan.proposed`, and returns `(project_id, plan_proposed_payload)`.
        """
        bus, ledger = kernel.bus, kernel.ledger
        plan_proposed = _Collector()
        await bus.subscribe(topics.PLAN_PROPOSED, plan_proposed)

        create_reply = await bus.request(Message.new(
            topics.TASK_CREATE, source="tester",
            payload={"kind": "project", "description": description, "origin": "human", "risk": risk},
        ))
        project_id = create_reply.payload["task_id"]
        self.assertNotIn("deduplicated_against", create_reply.payload)

        list_reply = await bus.request(Message.new(topics.TASK_LIST_REQUEST, source="tester", payload={}))
        [project] = [t for t in list_reply.payload["tasks"] if t["task_id"] == project_id]
        self.assertEqual(project["risk"], risk)  # the risk override actually took

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
        return project_id, plan_proposed.messages[0].payload


class TestLowRiskAutoApproves(_PlanModeApprovalFlowTestCase):
    async def test_low_risk_plan_auto_approves_with_no_human_prompt(self) -> None:
        kernel = await self._boot(PlanningConfig())
        bus = kernel.bus
        ui_prompt = _Collector()
        plan_approved = _Collector()
        await bus.subscribe(topics.UI_PROMPT, ui_prompt)
        await bus.subscribe(topics.PLAN_APPROVED, plan_approved)

        project_id, proposed = await self._propose(kernel, risk="low", description="tidy up the retry client")
        self.assertEqual(proposed["risk"], "low")

        # Verification's own review runs unattended (real subsystem, real
        # `review_plan`) and Planning must act on its verdict without any
        # human step -- risk "low" <= default `auto_approve_max_risk`
        # ("medium").
        await _pump(40)
        self.assertEqual(ui_prompt.messages, [])
        self.assertEqual(len(plan_approved.messages), 1)
        self.assertEqual(plan_approved.messages[0].payload["approved_by"], "auto")

        children_reply = await bus.request(Message.new(
            topics.TASK_LIST_REQUEST, source="tester", payload={"filter": {"parent_id": project_id}},
        ))
        self.assertEqual(len(children_reply.payload["tasks"]), 1)


class TestHighRiskBlocksOnGenuineHumanAnswer(_PlanModeApprovalFlowTestCase):
    async def test_high_risk_plan_creates_no_children_until_a_real_human_says_yes(self) -> None:
        kernel = await self._boot(PlanningConfig(human_approval_timeout_seconds=3600.0))
        bus = kernel.bus
        ui_prompt = _Collector()
        plan_approved = _Collector()
        await bus.subscribe(topics.UI_PROMPT, ui_prompt)
        await bus.subscribe(topics.PLAN_APPROVED, plan_approved)

        project_id, proposed = await self._propose(kernel, risk="high", description="rewrite the retry client")
        self.assertEqual(proposed["risk"], "high")

        # Verification approves the plan on its merits, but risk=high must
        # still stop at a genuine human gate -- no plan.approved, no
        # children, yet.
        await _pump(40)
        self.assertEqual(len(ui_prompt.messages), 1)
        self.assertEqual(plan_approved.messages, [])
        prompt = ui_prompt.messages[0].payload
        self.assertIn("high", proposed["risk"])

        children_reply = await bus.request(Message.new(
            topics.TASK_LIST_REQUEST, source="tester", payload={"filter": {"parent_id": project_id}},
        ))
        self.assertEqual(children_reply.payload["tasks"], [])  # nothing executes before the human decides

        # The genuine external answer: a real "yes" published independently
        # of Planning/Verification, exactly what a human-facing Interface
        # would relay from `ui.prompt.answered`.
        await bus.publish(Message.new(
            topics.UI_PROMPT_ANSWERED, source="tester",
            payload={"prompt_id": prompt["prompt_id"], "answer": "yes"},
        ))
        await _pump(40)

        self.assertEqual(len(plan_approved.messages), 1)
        self.assertEqual(plan_approved.messages[0].payload["approved_by"], "human")
        children_reply = await bus.request(Message.new(
            topics.TASK_LIST_REQUEST, source="tester", payload={"filter": {"parent_id": project_id}},
        ))
        self.assertEqual(len(children_reply.payload["tasks"]), 1)

    async def test_high_risk_plan_rejected_by_a_real_human_no_creates_no_children(self) -> None:
        kernel = await self._boot(PlanningConfig(human_approval_timeout_seconds=3600.0))
        bus = kernel.bus
        ui_prompt = _Collector()
        await bus.subscribe(topics.UI_PROMPT, ui_prompt)

        project_id, _proposed = await self._propose(kernel, risk="high", description="delete the legacy adapter")
        await _pump(40)
        self.assertEqual(len(ui_prompt.messages), 1)
        prompt_id = ui_prompt.messages[0].payload["prompt_id"]

        await bus.publish(Message.new(
            topics.UI_PROMPT_ANSWERED, source="tester", payload={"prompt_id": prompt_id, "answer": "no"},
        ))
        await _pump(40)

        list_reply = await bus.request(Message.new(topics.TASK_LIST_REQUEST, source="tester", payload={}))
        [project] = [t for t in list_reply.payload["tasks"] if t["task_id"] == project_id]
        self.assertEqual(project["status"], "failed")
        children_reply = await bus.request(Message.new(
            topics.TASK_LIST_REQUEST, source="tester", payload={"filter": {"parent_id": project_id}},
        ))
        self.assertEqual(children_reply.payload["tasks"], [])


class TestUnansweredHighRiskPromptTimesOutRatherThanHanging(_PlanModeApprovalFlowTestCase):
    async def test_no_answer_within_timeout_pauses_the_task_instead_of_hanging_forever(self) -> None:
        # A tiny timeout so the real `system.tick.second` loop (1 real
        # second per tick, simorgh/kernel/scheduler.py) crosses it within
        # this test's patience.
        kernel = await self._boot(PlanningConfig(human_approval_timeout_seconds=0.05))
        bus = kernel.bus
        ui_prompt = _Collector()
        plan_approved = _Collector()
        await bus.subscribe(topics.UI_PROMPT, ui_prompt)
        await bus.subscribe(topics.PLAN_APPROVED, plan_approved)

        project_id, _proposed = await self._propose(kernel, risk="high", description="replace the auth backend")
        await _pump(40)
        self.assertEqual(len(ui_prompt.messages), 1)

        # Nobody ever answers. Wait past both the timeout and the next
        # real system.tick.second.
        await asyncio.sleep(1.5)
        await _pump(40)

        self.assertEqual(plan_approved.messages, [])  # never silently proceeded
        list_reply = await bus.request(Message.new(topics.TASK_LIST_REQUEST, source="tester", payload={}))
        [project] = [t for t in list_reply.payload["tasks"] if t["task_id"] == project_id]
        self.assertEqual(project["status"], "paused")
        self.assertIn("timed out", project["note"])

        # A very-late human answer must not resurrect a paused task into
        # an illegal transition (PAUSED has no legal edge to COMPLETED) --
        # it is simply ignored.
        await bus.publish(Message.new(
            topics.UI_PROMPT_ANSWERED, source="tester",
            payload={"prompt_id": ui_prompt.messages[0].payload["prompt_id"], "answer": "yes"},
        ))
        await _pump(40)
        self.assertEqual(plan_approved.messages, [])

        health = await kernel._supervisor.services["planning"].service.health()  # noqa: SLF001
        self.assertEqual(health.status, "ok")


if __name__ == "__main__":
    unittest.main()
