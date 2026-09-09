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

    @run
    async def test_a_benchmark_case_is_never_deduped_either(self):
        """Observer, 2026-09-08 (GAIA deep dive): every case gets the
        same ~330-char answer-format suffix appended by
        `benchmark/runner.py::Runner.prompt`, which alone pushed two
        wholly unrelated GAIA questions (Kipchoge's marathon, Mercedes
        Sosa's albums) over this 45% fuzzy threshold -- 5 of 7 cases in
        one real run silently got handed back an unrelated,
        already-completed task_id and were never actually asked."""
        intake, _store = await _intake()
        suffix = "\n\nFINAL ANSWER: <answer in the exact format requested>" * 8  # a shared, long boilerplate
        first = await intake.on_goal_stated(
            goal=f"How many hours did Kipchoge take?{suffix}", origin="benchmark", wants_project=False,
        )
        second = await intake.on_goal_stated(
            goal=f"How many albums did Mercedes Sosa release?{suffix}", origin="benchmark", wants_project=False,
        )
        self.assertIsNotNone(second.task)
        self.assertNotEqual(second.task.id, first.task.id)


class TestPatternsFoundDedupeUsesTaskType(unittest.TestCase):
    """2026-09-08, observer w8-04, reproduced against a real Kernel:
    `PatternMiner`'s proposal template ("'{task_type}' tasks failed N/M
    recent outcomes (X%) -- worth reviewing for a systematic issue.") is
    almost entirely shared boilerplate -- two patterns for different
    task_types measured ~0.93 SequenceMatcher similarity, well past the
    0.45 dedupe threshold, so the second pattern silently collapsed into
    the first's task and Planning never got a task for it. `on_patterns_
    found` now passes each pattern's own `task_type` as a `distinguish`
    key so a match must actually be about the same task_type."""

    @run
    async def test_two_different_task_types_both_become_tasks(self):
        intake, _store = await _intake()
        patch_pattern = {
            "kind": "failure_rate", "rate": 1.0, "task_type": "patch",
            "proposal": "'patch' tasks failed 5/5 recent outcomes (100%) -- worth reviewing for a systematic issue.",
        }
        unknown_pattern = {
            "kind": "failure_rate", "rate": 1.0, "task_type": "unknown",
            "proposal": "'unknown' tasks failed 5/5 recent outcomes (100%) -- worth reviewing for a systematic issue.",
        }
        created = await intake.on_patterns_found(patterns=[patch_pattern, unknown_pattern])
        self.assertEqual(len(created), 2, "a genuinely distinct task_type's pattern was dropped as a false duplicate")
        self.assertNotEqual(created[0].id, created[1].id)

    @run
    async def test_the_same_task_type_mined_again_is_still_a_real_duplicate(self):
        """The fix must not defeat dedupe entirely -- a pattern re-mined
        next window for the *same* task_type is still the same idea."""
        intake, _store = await _intake()
        pattern = {
            "kind": "failure_rate", "rate": 1.0, "task_type": "patch",
            "proposal": "'patch' tasks failed 5/5 recent outcomes (100%) -- worth reviewing for a systematic issue.",
        }
        first = await intake.on_patterns_found(patterns=[pattern])
        self.assertEqual(len(first), 1)
        second = await intake.on_patterns_found(patterns=[pattern])
        self.assertEqual(second, [], "the same task_type's repeated pattern should still dedupe")


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
