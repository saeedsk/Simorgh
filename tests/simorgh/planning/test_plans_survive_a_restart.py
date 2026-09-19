"""A plan under review or waiting for a person survives a restart (found
writing planning's CONTRACT.md, 2026-09-19: plan state lived only in
memory; the plan:<id> stream the docstring described was never written)."""

import unittest
from types import SimpleNamespace

from simorgh.ledger.factory import make_ledger
from simorgh.planning import planmode
from simorgh.planning.model import Step
from simorgh.planning.service import PLANS_STREAM, Service
from tests.simorgh.helpers import FakeClock


class PlansSurviveARestart(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()

    def _service(self) -> Service:
        svc = Service()
        svc._ctx = SimpleNamespace(ledger=self.ledger, clock=self.clock)  # noqa: SLF001
        return svc

    async def test_an_awaiting_plan_and_its_prompt_come_back(self):
        first = self._service()
        state = planmode.PlanState(plan_id="p1", task_id="t1", goal="tidy the garage", risk="high",
                                   steps=[Step("s1", "research", "list what is there"),
                                          Step("s2", "patch", "write the plan", depends_on=("s1",), subject="simorgh/x.py")])
        state.status = planmode.AWAITING_HUMAN
        state.prompt_id = "q1"
        first._plans["p1"] = state  # noqa: SLF001
        await first._persist_changed_plans()  # noqa: SLF001

        second = self._service()
        await second._restore_plans()  # noqa: SLF001
        restored = second._plans["p1"]  # noqa: SLF001
        self.assertEqual(restored.status, planmode.AWAITING_HUMAN)
        self.assertEqual(restored.steps[1].depends_on, ("s1",))
        self.assertEqual(second._prompt_to_plan["q1"], "p1")  # noqa: SLF001
        self.assertEqual(second._plan_by_task["t1"], "p1")  # noqa: SLF001

    async def test_an_unchanged_plan_is_not_recorded_twice_and_a_resolved_one_stays_out(self):
        svc = self._service()
        state = planmode.PlanState(plan_id="p2", task_id="t2", goal="g", risk="low", steps=[])
        svc._plans["p2"] = state  # noqa: SLF001
        await svc._persist_changed_plans()  # noqa: SLF001
        await svc._persist_changed_plans()  # noqa: SLF001
        self.assertEqual(len(await self.ledger.read(PLANS_STREAM)), 1)
        state.status = planmode.APPROVED
        await svc._persist_changed_plans()  # noqa: SLF001
        fresh = self._service()
        await fresh._restore_plans()  # noqa: SLF001
        self.assertNotIn("p2", fresh._plans)  # noqa: SLF001
