"""Sim's own ideas that are not worth a task are never created (2026-10-30).

The creator, after an audit of a week of autonomous work: "fix sim's
logic to not start bogus, useless tasks". The three biggest wastes were
each knowable at intake: patches on Guardian's protected paths (denied
every time, 14 of them), growth tuning its own machinery (dead code), and
five overlapping self-improvement projects in one evening. A person's
request is never judged.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts.protocols import Context
from simorgh.ledger.backends.memory import InMemoryBackend as LedgerMemoryBackend
from simorgh.ledger.client import LedgerClient
from simorgh.ledger.factory import make_ledger
from simorgh.planning import planmode
from simorgh.planning.config import Config
from simorgh.planning.intake import Intake
from simorgh.planning.model import AVAILABLE, COMPLETED, Step
from simorgh.planning.service import Service
from simorgh.planning.store import TaskStore
from simorgh.planning.worth import protected_hit, refusal

from tests.simorgh.helpers import FakeClock

PROTECTED = ("docs/SOUL.md", "simorgh/guardian/", "simorgh/kernel/", "simorgh/contracts/", "agents/")


async def _protected() -> tuple[str, ...]:
    return PROTECTED


async def _intake(**kw):
    clock = FakeClock()
    ledger = LedgerClient(LedgerMemoryBackend(), clock=clock)
    await ledger.start()
    store = TaskStore(ledger, clock)
    return Intake(store, dedupe_threshold=0.45, protected=_protected, **kw), store


class TheRule(unittest.TestCase):
    def test_a_protected_path_is_matched_as_guardian_matches_it(self):
        self.assertEqual(protected_hit("simorgh/kernel/selfcheck.py", PROTECTED), "simorgh/kernel/")
        self.assertEqual(protected_hit("./Simorgh/Guardian/rules.py", PROTECTED), "simorgh/guardian/")
        self.assertEqual(protected_hit("simorgh/memory/store.py", PROTECTED), "")
        self.assertEqual(protected_hit(None, PROTECTED), "")

    def test_only_code_changing_work_is_judged(self):
        kw = dict(subject="simorgh/kernel/selfcheck.py", protected=PROTECTED, self_growth=False)
        self.assertIn("protected", refusal(kind="patch", **kw))
        self.assertIn("protected", refusal(kind="skill", **kw))
        self.assertEqual(refusal(kind="research", **kw), "", "reading a protected file is harmless")
        growth = dict(subject="simorgh/growth/calibration.py", protected=PROTECTED)
        self.assertIn("growth", refusal(kind="patch", self_growth=False, **growth))
        self.assertEqual(refusal(kind="patch", self_growth=True, **growth), "")
        self.assertEqual(refusal(kind="patch", subject="simorgh/pim/tools.py", protected=PROTECTED,
                                 self_growth=False), "")


class AtIntake(unittest.IsolatedAsyncioTestCase):
    async def test_a_patch_guardian_will_deny_is_not_created(self):
        intake, _ = await _intake()
        result = await intake.on_candidate(kind="patch", description="Make selfcheck use a shared stub",
                                           subject="simorgh/kernel/selfcheck.py", area="curiosity")
        self.assertIsNone(result.task)
        self.assertIn("protected", result.refused)

    async def test_growth_tuning_itself_is_not_created_unless_allowed(self):
        intake, _ = await _intake()
        result = await intake.on_candidate(kind="patch", description="Add a calibration facade",
                                           subject="simorgh/growth/calibration.py", area="growth")
        self.assertIsNone(result.task)
        self.assertIn("growth", result.refused)
        allowed, _ = await _intake(self_growth=True)
        self.assertIsNotNone((await allowed.on_candidate(
            kind="patch", description="Add a calibration facade", subject="simorgh/growth/calibration.py",
            area="growth")).task)

    async def test_a_household_fix_still_is(self):
        intake, _ = await _intake()
        result = await intake.on_candidate(kind="patch", description="Reconnect IMAP after an idle drop",
                                           subject="simorgh/domains/pim/connectors/imap.py", area="curiosity")
        self.assertIsNotNone(result.task)

    async def test_a_persons_request_is_never_judged(self):
        intake, _ = await _intake()
        result = await intake.on_candidate(kind="patch", description="tidy the growth calibration",
                                           subject="simorgh/growth/calibration.py", area="", origin="human")
        self.assertIsNotNone(result.task)

    async def test_a_research_follow_up_on_a_protected_path_is_dropped(self):
        intake, _ = await _intake()
        self.assertIsNone(await intake.on_research_follow_up(
            research_task_id="r1", subject="simorgh/contracts/topics.py", description="Rename a topic"))
        self.assertIsNotNone(await intake.on_research_follow_up(
            research_task_id="r1", subject="simorgh/memory/store.py", description="Persist vectors"))

    async def test_one_autonomous_project_at_a_time(self):
        intake, store = await _intake()
        first = await intake.on_goal_stated(goal="Build a closed-loop pipeline", origin="curiosity",
                                            wants_project=True)
        self.assertIsNotNone(first.task)
        second = await intake.on_goal_stated(goal="Calibrate the estimator against outcomes",
                                             origin="curiosity", wants_project=True)
        self.assertIsNone(second.task)
        self.assertIn("max_open_autonomous_projects", second.refused)
        mine = await intake.on_goal_stated(goal="Plan the garden for spring", origin="human",
                                           wants_project=True)
        self.assertIsNotNone(mine.task, "a person's project is never held")

    async def test_a_decomposed_project_still_counts_while_its_steps_run(self):
        intake, store = await _intake()
        project = (await intake.on_goal_stated(goal="Build a closed-loop pipeline", origin="curiosity",
                                               wants_project=True)).task
        await store.create(kind="research", description="n1", origin="project", parent_id=project.id,
                           mode="execute", risk="low", initial_status=AVAILABLE)
        await store.transition(project.id, COMPLETED, note="project decomposed")
        again = await intake.on_goal_stated(goal="Calibrate the estimator against outcomes",
                                            origin="curiosity", wants_project=True)
        self.assertIsNone(again.task)


class AtPlanApproval(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=clock)
        self.bus = make_client(backend, source="planning", ledger=self.ledger, clock=clock)
        await self.bus.start()
        await self.ledger.append("guardian:protected", _subjects_event(clock))
        self.service = Service(Config())
        await self.service.start(Context(
            name="planning", instance_id="", run_id="test", mode="single", bus=self.bus, ledger=self.ledger,
            config={}, secrets={}, clock=clock, logger=_Logger(), data_dir=Path(self._tmp.name) / "data"))

    async def asyncTearDown(self):
        await self.service.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _approve(self, origin: str) -> list[str]:
        store = self.service._store  # noqa: SLF001
        project = await store.create(kind="project", description="the goal", origin=origin, mode="plan",
                                     initial_status=AVAILABLE)
        steps = [Step("n1", "research", "read the night loop"),
                 Step("n2", "patch", "watch benchmarks", subject="simorgh/growth/monitors/service.py",
                      depends_on=("n1",)),
                 Step("n3", "patch", "touch the kernel", subject="simorgh/kernel/selfcheck.py"),
                 Step("n4", "patch", "fix the player", subject="simorgh/domains/media/player.py",
                      depends_on=("n2",))]
        state = planmode.PlanState(plan_id="p1", task_id=project.id, goal="the goal", steps=steps, risk="low")
        self.service._plans["p1"] = state  # noqa: SLF001
        await self.service._approve_plan(state, approved_by="auto")  # noqa: SLF001
        return sorted(c.description for c in store.children(project.id))

    async def test_sims_own_project_skips_steps_that_are_not_worth_it(self):
        # n2 is growth tuning itself, n3 is protected, and n4 needed n2.
        self.assertEqual(await self._approve("curiosity"), ["read the night loop"])

    async def test_a_persons_project_keeps_every_step(self):
        self.assertEqual(len(await self._approve("human")), 4)


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


def _subjects_event(clock):
    from simorgh.contracts.envelope import Event

    return Event(stream="guardian:protected", type="subjects", ts=clock.now(), trace_id=None,
                 causation_id=None, payload={"protected_subjects": list(PROTECTED)})


if __name__ == "__main__":
    unittest.main()
