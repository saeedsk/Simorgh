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


class RefusalIsNotFailureTestCase(unittest.TestCase):
    """A correct refusal must not be scored as defective work.

    The scaffold tells the model "a denial is an answer, not an error";
    the verifier then failed exactly that answer, pushed the task into
    the revision loop, and made a refusal cost more provider budget than
    a success. Four observers hit this on 2026-09-08.
    """

    def _combined(self, items):
        from simorgh.verification.config import VerificationConfig
        from simorgh.verification.trajectory import TrajectoryMetrics

        return combine([], items, TrajectoryMetrics(available=False), VerificationConfig())

    def _item(self, answer, evidence, required=True):
        return AnsweredItem(question="q?", required=required, answer=answer, evidence=evidence)

    def test_a_required_no_whose_evidence_is_a_denial_does_not_fail(self):
        result = self._combined([
            self._item("no", "Guardian denied the apply_source_patch, so no change was applied"),
        ])
        self.assertNotEqual(result.verdict, "fail")

    def test_a_required_no_on_the_merits_still_fails(self):
        result = self._combined([self._item("no", "the constant is simply not in the file")])
        self.assertEqual(result.verdict, "fail")

    def test_a_denial_alongside_a_real_defect_still_fails(self):
        result = self._combined([
            self._item("no", "Guardian denied the write"),
            self._item("no", "the summary omits three of the rules"),
        ])
        self.assertEqual(result.verdict, "fail")

    def test_denied_action_count_is_forgiven_when_every_no_is_a_refusal(self):
        from simorgh.verification.config import VerificationConfig
        from simorgh.verification.trajectory import TrajectoryMetrics

        items = [self._item("no", "the action was denied by ProtectedRule")]
        result = combine([], items, TrajectoryMetrics(available=True, denied_actions=5), VerificationConfig())
        self.assertNotEqual(result.verdict, "fail")

    def test_denied_action_count_still_fails_a_task_that_also_failed(self):
        from simorgh.verification.config import VerificationConfig
        from simorgh.verification.trajectory import TrajectoryMetrics

        items = [self._item("no", "the file was never written")]
        result = combine([], items, TrajectoryMetrics(available=True, denied_actions=5), VerificationConfig())
        self.assertEqual(result.verdict, "fail")
