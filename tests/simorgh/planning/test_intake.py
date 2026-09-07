"""`Intake`'s `risk` pass-through (07-planning.md section 5.6, Phase 4
roadmap item 4.1): `task.create.v1.json` already has an optional `risk`
field, but until this change `Intake.on_goal_stated`/`on_candidate`
silently dropped it and always forced "medium" (project) or "low" (every
other kind). A project's risk therefore could never be "high" through any
real message, which meant `planmode.approval_decision`'s `risk >= high ->
ask_human` branch -- the entire point of Phase 4 item 4.1 -- was
unreachable in the built system, not just untested. These tests pin the
override behavior directly against `Intake`, independent of the bus/
Kernel wiring the integration test covers."""

import unittest

from simorgh.ledger.backends.memory import InMemoryBackend as LedgerMemoryBackend
from simorgh.ledger.client import LedgerClient
from simorgh.planning.intake import Intake
from simorgh.planning.store import TaskStore

from tests.simorgh.helpers import FakeClock
from tests.simorgh.orchestration.harness import run


async def _intake():
    clock = FakeClock()
    ledger = LedgerClient(LedgerMemoryBackend(), clock=clock)
    await ledger.start()
    store = TaskStore(ledger, clock)
    return Intake(store, dedupe_threshold=0.45), store


class TestDedupeIsForAutonomousOriginsOnly(unittest.TestCase):
    """2026-09-07, live-caught: `improve docs/A.md ...`, `improve
    docs/B.md ...` and a third all returned the first task's id at the
    45% fuzzy threshold, so only the first ever ran."""

    @run
    async def test_a_curiosity_candidate_is_deduped_against_a_similar_task(self):
        intake, _store = await _intake()
        first = await intake.on_candidate(kind="patch", description="improve web access via mcp", subject=None, area="")
        second = await intake.on_candidate(kind="patch", description="improve mcp web access", subject=None, area="")
        self.assertIsNone(second.task)
        self.assertEqual(second.duplicate_of, first.task.id)

    @run
    async def test_a_human_request_is_never_deduped(self):
        intake, _store = await _intake()
        first = await intake.on_candidate(
            kind="patch", description="improve web access via mcp", subject="docs/A.md", area="", origin="human",
        )
        second = await intake.on_candidate(
            kind="patch", description="improve mcp web access", subject="docs/B.md", area="", origin="human",
        )
        self.assertIsNotNone(second.task)
        self.assertNotEqual(second.task.id, first.task.id)

    @run
    async def test_a_human_goal_is_never_deduped_either(self):
        intake, _store = await _intake()
        first = await intake.on_goal_stated(goal="plan web access", origin="human", wants_project=True)
        second = await intake.on_goal_stated(goal="plan for web access mcp", origin="human", wants_project=True)
        self.assertIsNotNone(second.task)
        self.assertNotEqual(second.task.id, first.task.id)


class TestGoalStatedRiskOverride(unittest.TestCase):
    @run
    async def test_project_risk_defaults_to_medium_when_omitted(self):
        intake, _store = await _intake()
        result = await intake.on_goal_stated(goal="ship the thing", origin="human", wants_project=True)
        self.assertEqual(result.task.risk, "medium")

    @run
    async def test_project_risk_honors_high_override(self):
        intake, _store = await _intake()
        result = await intake.on_goal_stated(
            goal="rewrite the auth backend", origin="human", wants_project=True, risk="high",
        )
        self.assertEqual(result.task.risk, "high")

    @run
    async def test_project_risk_honors_low_override(self):
        intake, _store = await _intake()
        result = await intake.on_goal_stated(
            goal="tidy up some comments", origin="human", wants_project=True, risk="low",
        )
        self.assertEqual(result.task.risk, "low")

    @run
    async def test_non_project_goal_risk_defaults_to_low_when_omitted(self):
        intake, _store = await _intake()
        result = await intake.on_goal_stated(goal="what does this file do?", origin="human", wants_project=False)
        self.assertEqual(result.task.risk, "low")

    @run
    async def test_non_project_goal_risk_honors_override(self):
        intake, _store = await _intake()
        result = await intake.on_goal_stated(
            goal="patch the retry client", origin="reflection", wants_project=False, risk="high",
        )
        self.assertEqual(result.task.risk, "high")


class TestCandidateRiskOverride(unittest.TestCase):
    @run
    async def test_candidate_risk_defaults_to_low_when_omitted(self):
        intake, _store = await _intake()
        result = await intake.on_candidate(kind="patch", description="fix the flaky test", subject=None, area="")
        self.assertEqual(result.task.risk, "low")

    @run
    async def test_candidate_risk_honors_override(self):
        intake, _store = await _intake()
        result = await intake.on_candidate(
            kind="patch", description="rewrite the scheduler", subject=None, area="", risk="high",
        )
        self.assertEqual(result.task.risk, "high")


if __name__ == "__main__":
    unittest.main()
