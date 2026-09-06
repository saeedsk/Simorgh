import unittest

from simorgh.kernel.selfcheck import NOOP_TOOL, SelfCheckResult, StepResult, _wait_for, run


class TestRunEndToEnd(unittest.IsolatedAsyncioTestCase):
    """Exercises the real `run()` -- the same proof `simorgh --self-check`
    runs -- as an automated regression guard, not just a manual check."""

    async def test_all_four_steps_pass_and_overall_is_pass(self):
        result = await run(timeout=5.0)
        self.assertEqual(len(result.steps), 4)
        for step in result.steps:
            self.assertTrue(step.passed, f"{step.name} failed: {step.detail}")
        self.assertTrue(result.passed)

    async def test_step_names_match_the_spec_s_four_proofs(self):
        result = await run(timeout=5.0)
        names = [s.name for s in result.steps]
        self.assertEqual(names, [
            "noop proposal is approved with a valid token and executed",
            "a forged approval token is rejected before the tool runs",
            "a proposal made while paused is denied",
            "a throwaway source cannot subscribe to action.proposed",
        ])

    async def test_report_renders_pass_lines_and_overall_pass(self):
        result = await run(timeout=5.0)
        report = result.report()
        self.assertEqual(report.count("PASS"), 5)  # 4 steps + OVERALL
        self.assertIn("OVERALL: PASS", report)
        self.assertNotIn("FAIL", report)


class TestSelfCheckResultAggregation(unittest.TestCase):
    """`SelfCheckResult.passed`/`.report()` in isolation -- `run()` has no
    injection point for a "broken" Guardian/Execution, so the fact that
    a single failing step fails the whole check is proven at this level."""

    def test_passed_is_false_with_no_steps_at_all(self):
        self.assertFalse(SelfCheckResult().passed)

    def test_passed_is_true_only_when_every_step_passed(self):
        result = SelfCheckResult(steps=[StepResult("a", True), StepResult("b", True)])
        self.assertTrue(result.passed)

    def test_a_single_failing_step_fails_the_whole_check(self):
        result = SelfCheckResult(steps=[
            StepResult("a valid token is accepted", True),
            StepResult("a forged token is rejected", False, "a broken execution stub accepted it anyway"),
        ])
        self.assertFalse(result.passed)

    def test_report_shows_fail_for_the_failing_step_and_overall_fail(self):
        result = SelfCheckResult(steps=[
            StepResult("ok step", True),
            StepResult("broken step", False, "detail here"),
        ])
        report = result.report()
        self.assertIn("PASS  ok step", report)
        self.assertIn("FAIL  broken step -- detail here", report)
        self.assertIn("OVERALL: FAIL", report)


class TestWaitFor(unittest.IsolatedAsyncioTestCase):
    async def test_finds_a_matching_event_already_present(self):
        events = [("a1", "approved", "tok")]
        found = await _wait_for(events, "a1", "approved", timeout=1.0)
        self.assertEqual(found, ("a1", "approved", "tok"))

    async def test_times_out_returning_none_when_nothing_matches(self):
        found = await _wait_for([], "missing", "approved", timeout=0.05)
        self.assertIsNone(found)

    async def test_ignores_events_for_a_different_action_id(self):
        events = [("other", "approved", "tok")]
        found = await _wait_for(events, "a1", "approved", timeout=0.05)
        self.assertIsNone(found)


class TestNoopTool(unittest.TestCase):
    def test_noop_tool_name_is_stable(self):
        self.assertEqual(NOOP_TOOL, "noop")


if __name__ == "__main__":
    unittest.main()
