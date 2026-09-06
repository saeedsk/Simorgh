"""`combine` -- the core verdict-combination logic (verdict.py):
mechanical failures win first (cheapest-first, so nothing expensive runs
past a free failure), then a required "no", then denied-actions over the
max, then insufficient-answered-fraction (milestone-92: never `fail`),
else `pass`."""

import unittest

from simorgh.verification.api import CheckResult, Feedback
from simorgh.verification.checklist import AnsweredItem
from simorgh.verification.config import VerificationConfig
from simorgh.verification.trajectory import TrajectoryMetrics
from simorgh.verification.verdict import combine, feedback_to_wire


def _traj(**kw) -> TrajectoryMetrics:
    return TrajectoryMetrics(**kw)


class TestCombine(unittest.TestCase):
    def setUp(self):
        self.config = VerificationConfig()

    def test_all_pass_no_checklist_is_pass(self):
        results = [("syntax", CheckResult(status="passed"))]
        combined = combine(results, [], _traj(), self.config)
        self.assertEqual(combined.verdict, "pass")
        self.assertIsNone(combined.feedback)

    def test_mechanical_failure_short_circuits_checklist(self):
        feedback = Feedback(mechanical_errors=("bad syntax",), retryable=True)
        results = [("syntax", CheckResult(status="failed", feedback=feedback))]
        answered = [AnsweredItem(question="q", required=True, answer="yes", evidence="e")]
        combined = combine(results, answered, _traj(), self.config)
        self.assertEqual(combined.verdict, "fail")
        self.assertEqual(combined.checklist, [])  # never evaluated -- mechanical failed first
        self.assertIs(combined.feedback, feedback)

    def test_required_no_fails_with_retryable_feedback(self):
        answered = [AnsweredItem(question="handles empty list?", required=True, answer="no", evidence="it doesn't")]
        combined = combine([], answered, _traj(), self.config)
        self.assertEqual(combined.verdict, "fail")
        self.assertTrue(combined.feedback.retryable)
        self.assertEqual(len(combined.feedback.failed_items), 1)

    def test_optional_no_does_not_fail(self):
        answered = [AnsweredItem(question="has a test?", required=False, answer="no", evidence="none added")]
        combined = combine([], answered, _traj(), self.config)
        self.assertEqual(combined.verdict, "pass")

    def test_denied_actions_over_max_fails(self):
        combined = combine([], [], _traj(denied_actions=self.config.max_denied_actions), self.config)
        self.assertEqual(combined.verdict, "fail")
        self.assertTrue(combined.feedback.retryable)

    def test_too_many_unanswered_is_insufficient_never_fail(self):
        answered = [
            AnsweredItem(question="q1", required=True, answer=None, evidence=""),
            AnsweredItem(question="q2", required=True, answer=None, evidence=""),
            AnsweredItem(question="q3", required=True, answer="yes", evidence="ok"),
        ]
        combined = combine([], answered, _traj(), self.config)
        self.assertEqual(combined.verdict, "insufficient_evidence")
        self.assertIsNone(combined.feedback)

    def test_mechanical_payload_surfaces_isolated_suite_evidence(self):
        result = CheckResult(status="passed", evidence={"baseline": 3, "patched": 4, "passed": True})
        combined = combine([("isolated_suite", result)], [], _traj(), self.config)
        self.assertEqual(combined.mechanical["baseline"], 3)
        self.assertEqual(combined.mechanical["patched"], 4)
        self.assertTrue(combined.mechanical["tests_passed"])


class TestFeedbackToWire(unittest.TestCase):
    def test_shape_matches_verify_result_schema(self):
        feedback = Feedback(mechanical_errors=("bad syntax",), revise_hint="fix it", retryable=True)
        wire = feedback_to_wire(feedback)
        self.assertEqual(wire["items"], [{"what": "mechanical check failed", "why": "bad syntax", "suggested_fix": ""}])
        self.assertTrue(wire["retryable"])
        self.assertEqual(wire["revise_hint"], "fix it")


if __name__ == "__main__":
    unittest.main()
