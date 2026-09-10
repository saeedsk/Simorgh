"""A benchmark run reports what it actually cost.

`Step.cost_usd`, `task.step`'s `cost_usd`, and `CaseResult.cost_usd`
all existed from the beginning and nothing ever wrote to any of them --
three layers of a declared field with no producer. So a run that made
real, billed model calls summed its cases and reported **$0.00**, which
is the "succeeds while saying nothing true" failure in the one unit
whose entire job is honest measurement.

Observed live 2026-09-10: three GAIA cases, 8 model calls, `cost_usd
0.0` on every case and on the run."""

from __future__ import annotations

import unittest

from simorgh.benchmark.runner import _AnswerWatch
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message


class _Bus:
    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}
        self.source = "benchmark"

    async def subscribe(self, topic, handler, **kwargs):
        self.handlers.setdefault(topic, []).append(handler)

        class _Sub:
            async def unsubscribe(self_inner) -> None:
                return None

        return _Sub()

    async def deliver(self, topic: str, payload: dict) -> None:
        for handler in self.handlers.get(topic, []):
            await handler(Message.new(topic, source="orchestration", payload=payload))


class WatchCostTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bus = _Bus()
        self.watch = _AnswerWatch(self.bus)
        await self.watch.start()

    async def _step(self, task_id: str, **fields) -> None:
        payload = {"task_id": task_id, "step_no": 1, "phase": "gather", "summary": "s"}
        payload.update(fields)
        await self.bus.deliver(topics.TASK_STEP, payload)

    async def test_a_step_with_a_cost_is_counted(self):
        await self._step("t1", ok=True, cost_usd=0.004)
        self.assertAlmostEqual(self.watch.cost("t1"), 0.004, places=6)

    async def test_costs_add_up_across_steps(self):
        await self._step("t1", ok=True, cost_usd=0.004)
        await self._step("t1", ok=True, cost_usd=0.006)
        self.assertAlmostEqual(self.watch.cost("t1"), 0.010, places=6)

    async def test_a_failed_think_is_still_billed_and_still_counted(self):
        """A step with no `ok` was skipped entirely by the step counter.
        Cognition still charged for it."""
        await self._step("t1", cost_usd=0.002)
        self.assertAlmostEqual(self.watch.cost("t1"), 0.002, places=6)

    async def test_costs_are_kept_per_task(self):
        await self._step("t1", ok=True, cost_usd=0.004)
        await self._step("t2", ok=True, cost_usd=0.009)
        self.assertAlmostEqual(self.watch.cost("t1"), 0.004, places=6)
        self.assertAlmostEqual(self.watch.cost("t2"), 0.009, places=6)

    async def test_a_task_that_spent_nothing_reports_zero(self):
        self.assertEqual(self.watch.cost("never-seen"), 0.0)


class StepCostTestCase(unittest.IsolatedAsyncioTestCase):
    """`Session.spent_usd` accumulates every think, and each step
    publishes the spend SINCE the previous one -- so a task's steps sum
    to the task's cost instead of each repeating the running total."""

    def _session(self):
        from simorgh.orchestration.api import Budget, Session
        from simorgh.orchestration.profiles import CHAT

        return Session(task_id="t1", kind="chat", mode="execute", profile=CHAT,
                       budget=Budget(max_steps=6))

    async def test_each_step_carries_only_its_own_share(self):
        from simorgh.orchestration.api import Step

        session = self._session()
        published: list[dict] = []

        class _Runner:
            async def _append(self, s, t, payload): pass

            async def _publish(self, s, t, payload):
                published.append(payload)

        from simorgh.orchestration.session import SessionRunner

        runner = _Runner()
        record = SessionRunner._record_step

        session.spent_usd = 0.004
        first = Step(no=1, phase="gather", summary="one", ok=True)
        await record(runner, session, first)
        session.steps.append(first)

        session.spent_usd = 0.010
        second = Step(no=2, phase="act", summary="two", ok=True)
        await record(runner, session, second)
        session.steps.append(second)

        self.assertAlmostEqual(first.cost_usd, 0.004, places=6)
        self.assertAlmostEqual(second.cost_usd, 0.006, places=6)
        self.assertAlmostEqual(sum(s.cost_usd for s in session.steps), 0.010, places=6)
        self.assertEqual([p.get("cost_usd") for p in published], [0.004, 0.006])

    async def test_a_step_that_cost_nothing_omits_the_field(self):
        from simorgh.orchestration.api import Step
        from simorgh.orchestration.session import SessionRunner

        published: list[dict] = []

        class _Runner:
            async def _append(self, s, t, payload): pass

            async def _publish(self, s, t, payload):
                published.append(payload)

        session = self._session()
        await SessionRunner._record_step(_Runner(), session, Step(no=1, phase="act", summary="x"))
        self.assertNotIn("cost_usd", published[0])
