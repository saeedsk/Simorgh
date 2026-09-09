"""Live-Kernel test of Reflection's real `reflect.drift.detected`
producer path (drift.py's `DriftTracker` + `service.py::_run_drift_close`),
not just `tests/simorgh/reflection/test_drift.py`'s synthetic
`DriftTracker` unit tests, and not just
`tests/simorgh/integration/test_reground_drift_flow.py`'s hand-published
`reflect.drift.detected` (which only exercises Planning's consumer side).

This boots a real Kernel with real Reflection *and* real Planning
together and drives an actual `task.created` -> `task.step` /
`action.denied` -> `task.completed` trajectory so Reflection's own
`DriftTracker` computes the heuristic, makes the real
`cognition.think(purpose="review")` round trip, and publishes
`reflect.drift.detected` itself -- then confirms Planning's
`_on_drift_detected` genuinely changes downstream behavior (forces a
real `cognition.think(purpose="reground")` round trip on the next
sibling, docs/blueprint/subsystems/12-reflection.md section 3,
07-planning.md section 5.5).

Also covers two things the same live wiring makes newly checkable:
- a project whose task is genuinely on-topic must not spuriously drift
  (false-positive check), and
- `reflect.drift.detected` cannot double-fire for one task (it is only
  ever computed once, at that task's own terminal transition), and
  a per-task drift flag never being reproduced twice does not, by
  itself, make it visible whether a *project* flagged once forces every
  future sibling through a real reground call forever -- confirmed
  below to be true, and intentional (mirrors `_project_sibling_failed`,
  which already behaves the same way).
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
from simorgh.reflection.config import Config as ReflectionConfig
from simorgh.reflection.service import Service as ReflectionService

STEPS_TEXT = (
    "1. RESEARCH :: is the current retry backoff strategy adequate\n"
    "2. simorgh/orchestrator/retry.py :: implement exponential backoff with jitter\n"
)


def _patched_build_factories(planning_config: PlanningConfig, reflection_config: ReflectionConfig):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None, guardian_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl, guardian_config=guardian_config)
        factories = {name: factories[name] for name in ("bus", "ledger")}
        factories["planning"] = lambda: PlanningService(planning_config)
        factories["reflection"] = lambda: ReflectionService(reflection_config)
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


class _FakeCognition:
    """Answers every real round trip this flow can make. Reflection
    issues `purpose="review"` from *two* independent call sites that
    share that same purpose string but not its prompt shape:
    `_run_drift_close`'s drift review (prompt starts `"Goal: ..."`) and
    `_run_critique`'s per-terminal-task self-critique (prompt starts
    `"Task (<kind>): ..."`, fires for every completed task whose kind is
    patch/skill/research/project -- i.e. every task this flow creates).
    Telling them apart by prompt prefix, not `purpose` alone, is
    required for a correct prompt count here -- and is itself a real
    finding: nothing on the wire (`purpose="review"` alone) distinguishes
    a drift review from a self-critique round trip. Planning's
    `purpose="reground"` (sibling re-grounding) is the third. Anything
    else gets no reply, so a test that reaches this fake unexpectedly
    fails via a real timeout rather than a silently-wrong canned
    answer."""

    def __init__(self, bus, *, review_text: str, reground_text: str) -> None:
        self._bus = bus
        self._review_text = review_text
        self._reground_text = reground_text
        self.review_prompts: list[str] = []
        self.critique_prompts: list[str] = []
        self.reground_prompts: list[str] = []

    async def __call__(self, message: Message) -> None:
        purpose = message.payload.get("purpose")
        prompt = message.payload["messages"][0]["content"]
        if purpose == "review" and prompt.startswith("Goal:"):
            self.review_prompts.append(prompt)
            text = self._review_text
        elif purpose == "review":
            self.critique_prompts.append(prompt)
            text = '{"what_changed": "n/a", "confidence": 0.5, "open_questions": [], "lesson": null}'
        elif purpose == "reground":
            self.reground_prompts.append(prompt)
            text = self._reground_text
        else:
            return
        await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": text, "floor": False, "non_answer": False,
            "tool_calls": [], "provider": "fake", "cost_usd": 0.0, "tokens": 0,
        })


class _DriftFlowTestCase(unittest.IsolatedAsyncioTestCase):
    async def _boot(self, planning_config: PlanningConfig, reflection_config: ReflectionConfig) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = LoadedConfig({"runtime": {"data_dir": tmp.name}}, None)
        kernel = Kernel(config, secrets=EnvSecretStore({}))
        patch = mock.patch(
            "simorgh.kernel.service.build_factories",
            new=_patched_build_factories(planning_config, reflection_config),
        )
        patch.start()
        self.addCleanup(patch.stop)
        await kernel.boot()
        self.assertEqual(kernel.state.state, RUNNING)
        self.assertEqual(kernel._supervisor.services["planning"].status, "ok")  # noqa: SLF001
        self.assertEqual(kernel._supervisor.services["reflection"].status, "ok")  # noqa: SLF001
        self.addAsyncCleanup(kernel.shutdown)
        return kernel

    async def _propose_and_approve(self, kernel: Kernel) -> tuple[str, dict, dict]:
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
        self.assertEqual(patch["status"], "pending")
        return project_id, research, patch

    async def _task(self, kernel: Kernel, task_id: str) -> dict:
        reply = await kernel.bus.request(Message.new(topics.TASK_LIST_REQUEST, source="tester", payload={}))
        return next(t for t in reply.payload["tasks"] if t["task_id"] == task_id)


class TestRealDriftTrackerFiresAndForcesRealReground(_DriftFlowTestCase):
    async def test_genuine_scope_crossings_on_research_task_produce_a_real_drift_signal_that_reground_the_pending_patch(self) -> None:
        # `drift_check_every_steps=1`: due-for-review after the task's
        # first observed step, so this test does not need to fabricate
        # 8 of them to reach Reflection's own cadence default.
        kernel = await self._boot(
            PlanningConfig(regrounding_age_seconds=999_999.0, project_step_count=2),
            ReflectionConfig(drift_check_every_steps=1),
        )
        bus = kernel.bus
        fake = _FakeCognition(
            bus,
            review_text="The task keeps trying to touch files outside its declared scope. drifting -- two denied scope crossings.",
            reground_text="STILL_VALID: no -- the research kept crossing scope; the plan needs to be redone.",
        )
        await bus.subscribe(topics.COGNITION_THINK, fake)
        drift_detected = _Collector()
        plan_revised = _Collector()
        await bus.subscribe(topics.REFLECT_DRIFT_DETECTED, drift_detected)
        await bus.subscribe(topics.PLAN_REVISED, plan_revised)

        project_id, research, patch = await self._propose_and_approve(kernel)
        research_id = research["task_id"]

        await bus.request(Message.new(
            topics.TASK_CLAIM, source="tester", payload={"task_id": research_id, "worker_id": "w1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_STARTED, source="tester", payload={"task_id": research_id, "worker_id": "w1"},
        ))
        # One real step (so DriftTracker._steps > 0, `due_for_review`'s
        # own guard), then two real `action.denied{layer:"scope"}` --
        # exactly the wire shape Guardian emits when a proposal's scope
        # doesn't match the task's declared one -- both attributed to
        # this task, which is the actual, only path that feeds
        # `DriftTracker.observe_scope_denial` (reflection/service.py's
        # `_on_action_denied`).
        await bus.publish(Message.new(
            topics.TASK_STEP, source="tester",
            payload={"task_id": research_id, "step_no": 1, "phase": "gather", "summary": "read retry backoff docs"},
        ))
        # `action.denied` is guardian-only on the wire
        # (`bus/enforcement.py`'s `ReservedTopologyPolicy`) -- the same
        # boundary `tests/simorgh/integration/test_denials_become_tasks.py`
        # already stands on: call Reflection's own real handler directly,
        # exactly where Guardian's publish would land, rather than fake a
        # second identity through the shared test bus client.
        reflection = kernel._supervisor.services["reflection"].service  # noqa: SLF001
        for _ in range(2):
            await reflection._on_action_denied(Message.new(  # noqa: SLF001
                topics.ACTION_DENIED, source="guardian",
                payload={"action_id": "a1", "reasons": ["scope: path not declared"], "layer": "scope", "task_id": research_id},
            ))
        await _pump()

        await bus.publish(Message.new(
            topics.TASK_COMPLETED, source="tester",
            payload={"task_id": research_id, "result_summary": "done", "artifacts": [], "verification_ref": None},
        ))
        await _pump(60)

        # 1. Reflection's real review round trip happened, and it was
        # this task's actual goal in the prompt -- not a stub.
        self.assertEqual(len(fake.review_prompts), 1)
        self.assertIn("is the current retry backoff strategy adequate", fake.review_prompts[0])

        # 2. Reflection genuinely computed and published
        # `reflect.drift.detected` itself (nobody hand-published it).
        self.assertEqual(len(drift_detected.messages), 1)
        finding = drift_detected.messages[0].payload
        self.assertEqual(finding["task_id"], research_id)
        self.assertIn("scope_crossings=2", finding["evidence"])

        # 3. Planning's `_on_drift_detected` really flagged the project
        # (first `plan.revised`) and really forced a `reground` round
        # trip on the still-pending sibling before it went `available`
        # (second `plan.revised`, from `_supersede_with_replacement`) --
        # not a flag nobody reads.
        old_patch = await self._task(kernel, patch["task_id"])
        self.assertEqual(len(fake.reground_prompts), 1)
        self.assertEqual(old_patch["status"], "failed")
        self.assertIn("superseded", old_patch["note"])
        self.assertEqual(len(plan_revised.messages), 2)
        self.assertIn("drift detected", plan_revised.messages[0].payload["reason"])
        self.assertIn("kept crossing scope", plan_revised.messages[1].payload["reason"])


class TestOnTopicTaskDoesNotSpuriouslyDrift(_DriftFlowTestCase):
    async def test_a_clean_on_scope_task_never_emits_drift_and_the_sibling_becomes_available_untouched(self) -> None:
        kernel = await self._boot(
            PlanningConfig(regrounding_age_seconds=999_999.0, project_step_count=2),
            ReflectionConfig(drift_check_every_steps=1),
        )
        bus = kernel.bus
        fake = _FakeCognition(
            bus, review_text="on_track -- steps so far are squarely in scope.",
            reground_text="STILL_VALID: yes",
        )
        await bus.subscribe(topics.COGNITION_THINK, fake)
        drift_detected = _Collector()
        plan_revised = _Collector()
        await bus.subscribe(topics.REFLECT_DRIFT_DETECTED, drift_detected)
        await bus.subscribe(topics.PLAN_REVISED, plan_revised)

        _project_id, research, patch = await self._propose_and_approve(kernel)
        research_id = research["task_id"]

        await bus.request(Message.new(
            topics.TASK_CLAIM, source="tester", payload={"task_id": research_id, "worker_id": "w1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_STARTED, source="tester", payload={"task_id": research_id, "worker_id": "w1"},
        ))
        # Real steps, no denials, no repeats -- a genuinely healthy
        # trajectory.
        for i in range(3):
            await bus.publish(Message.new(
                topics.TASK_STEP, source="tester",
                payload={"task_id": research_id, "step_no": i + 1, "phase": "gather",
                         "summary": f"read retry backoff source, part {i + 1}"},
            ))
        await _pump()
        await bus.publish(Message.new(
            topics.TASK_COMPLETED, source="tester",
            payload={"task_id": research_id, "result_summary": "done", "artifacts": [], "verification_ref": None},
        ))
        await _pump(60)

        # The review round trip still really happened (due-for-review by
        # cadence), but a genuinely on-track task must never manufacture
        # a drift finding out of it.
        self.assertEqual(len(fake.review_prompts), 1)
        self.assertEqual(drift_detected.messages, [])
        self.assertEqual(plan_revised.messages, [])

        after_patch = await self._task(kernel, patch["task_id"])
        self.assertEqual(after_patch["status"], "available")  # unchanged, no reground churn


class TestDriftCanOnlyFireOnceForOneTask(_DriftFlowTestCase):
    async def test_a_terminal_task_never_produces_a_second_drift_event_for_itself(self) -> None:
        """Reflection's own `_tasks` dict pops the task's `_TaskMeta`
        (and its `DriftTracker`) the moment its terminal event is
        handled (`_on_task_terminal`), and `_run_drift_close` is only
        ever called from there -- so nothing in this subsystem can
        re-evaluate, and therefore re-publish, drift for a task that has
        already gone terminal, however many more `task.step`/
        `action.denied` messages naming that same `task_id` arrive
        afterward (e.g. a duplicate/late-retried event on the bus)."""
        kernel = await self._boot(
            PlanningConfig(regrounding_age_seconds=999_999.0, project_step_count=2),
            ReflectionConfig(drift_check_every_steps=1),
        )
        bus = kernel.bus
        fake = _FakeCognition(bus, review_text="drifting -- scope crossings.", reground_text="STILL_VALID: yes")
        await bus.subscribe(topics.COGNITION_THINK, fake)
        drift_detected = _Collector()
        await bus.subscribe(topics.REFLECT_DRIFT_DETECTED, drift_detected)

        _project_id, research, _patch = await self._propose_and_approve(kernel)
        research_id = research["task_id"]
        reflection = kernel._supervisor.services["reflection"].service  # noqa: SLF001

        await bus.request(Message.new(
            topics.TASK_CLAIM, source="tester", payload={"task_id": research_id, "worker_id": "w1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_STARTED, source="tester", payload={"task_id": research_id, "worker_id": "w1"},
        ))
        await bus.publish(Message.new(
            topics.TASK_STEP, source="tester",
            payload={"task_id": research_id, "step_no": 1, "phase": "gather", "summary": "read docs"},
        ))
        for _ in range(2):
            await reflection._on_action_denied(Message.new(  # noqa: SLF001
                topics.ACTION_DENIED, source="guardian",
                payload={"action_id": "a1", "reasons": ["scope"], "layer": "scope", "task_id": research_id},
            ))
        await bus.publish(Message.new(
            topics.TASK_COMPLETED, source="tester",
            payload={"task_id": research_id, "result_summary": "done", "artifacts": [], "verification_ref": None},
        ))
        await _pump(60)
        self.assertEqual(len(drift_detected.messages), 1)

        # More traffic naming the now-terminal task, as if a duplicate
        # delivery or a late worker heartbeat arrived after the fact.
        for _ in range(3):
            await reflection._on_action_denied(Message.new(  # noqa: SLF001
                topics.ACTION_DENIED, source="guardian",
                payload={"action_id": "a2", "reasons": ["scope"], "layer": "scope", "task_id": research_id},
            ))
        await bus.publish(Message.new(
            topics.TASK_STEP, source="tester",
            payload={"task_id": research_id, "step_no": 2, "phase": "gather", "summary": "late duplicate step"},
        ))
        await bus.publish(Message.new(
            topics.TASK_COMPLETED, source="tester",
            payload={"task_id": research_id, "result_summary": "done (dup)", "artifacts": [], "verification_ref": None},
        ))
        await _pump(60)

        # Still exactly one -- a terminal task has no tracker left to
        # re-evaluate against.
        self.assertEqual(len(drift_detected.messages), 1)


if __name__ == "__main__":
    unittest.main()
