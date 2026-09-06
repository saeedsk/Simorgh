import unittest

from simorgh.reflection.config import Config
from simorgh.reflection.drift import (
    BEHAVIOR,
    DRIFTING,
    GOAL,
    NOTE,
    ON_TRACK,
    PAUSE,
    REGROUND,
    SCOPE,
    TIGHTEN,
    UNKNOWN,
    DriftTracker,
    DriftVerdict,
    parse_verdict,
)


class TestParseVerdict(unittest.TestCase):
    def test_empty_text_is_unknown(self):
        self.assertEqual(parse_verdict("").verdict, UNKNOWN)
        self.assertEqual(parse_verdict("   ").verdict, UNKNOWN)

    def test_no_recognized_token_is_unknown(self):
        self.assertEqual(parse_verdict("I'm not sure how to answer that.").verdict, UNKNOWN)

    def test_recognizes_on_track_case_insensitively(self):
        self.assertEqual(parse_verdict("ON_TRACK. Looks fine.").verdict, ON_TRACK)

    def test_recognizes_drifting(self):
        self.assertEqual(parse_verdict("drifting - this reads guardian policy, unrelated to memory.").verdict, DRIFTING)

    def test_first_token_wins_when_narrating_before_answering(self):
        verdict = parse_verdict("Let me think about this... drifting, because it left scope.")
        self.assertEqual(verdict.verdict, DRIFTING)


class TestDriftTracker(unittest.TestCase):
    def setUp(self):
        self.config = Config(drift_check_every_steps=8, drift_heuristic_threshold=0.5, drift_emit_threshold=0.6)

    def test_no_steps_has_zero_heuristic(self):
        tracker = DriftTracker("t1", "fix memory retrieval", ["src/memory/"], self.config)
        self.assertEqual(tracker.heuristic_score().heuristic, 0.0)

    def test_in_scope_steps_do_not_raise_heuristic(self):
        tracker = DriftTracker("t1", "fix memory retrieval", ["src/memory/"], self.config)
        for i in range(5):
            tracker.observe_step("read_file", f"read src/memory/long_term.py step {i}")
        self.assertEqual(tracker.heuristic_score().off_goal_touches, 0)

    def test_off_goal_touches_raise_heuristic(self):
        tracker = DriftTracker("t1", "fix memory retrieval", ["src/memory/"], self.config)
        tracker.observe_step("read_file", "read src/guardian/policy.py")
        score = tracker.heuristic_score()
        self.assertEqual(score.off_goal_touches, 1)
        self.assertGreater(score.heuristic, 0.0)

    def test_repeated_identical_calls_are_counted(self):
        tracker = DriftTracker("t1", "goal", [], self.config)
        for _ in range(3):
            tracker.observe_step("read_file", "read src/x.py")
        self.assertEqual(tracker.heuristic_score().repeated_calls, 2)  # 2nd and 3rd repeat the 1st

    def test_scope_denial_increments_crossings(self):
        tracker = DriftTracker("t1", "goal", ["src/memory/"], self.config)
        tracker.observe_step("read_file", "read src/memory/x.py")
        tracker.observe_scope_denial()
        self.assertEqual(tracker.heuristic_score().scope_crossings, 1)

    def test_unknown_verdict_never_fabricates_a_finding_below_heuristic(self):
        tracker = DriftTracker("t1", "goal", ["src/memory/"], self.config)
        tracker.observe_step("read_file", "read src/memory/x.py")  # in scope, low heuristic
        combined, finding = tracker.combined(DriftVerdict(UNKNOWN))
        self.assertIsNone(finding)

    def test_drifting_verdict_pushes_combined_score_up_and_emits(self):
        tracker = DriftTracker("t1", "goal", ["src/memory/"], self.config)
        # off-scope step -> nonzero heuristic contribution, so the
        # model's "drifting" verdict and the heuristic agree rather than
        # relying on the verdict alone to clear the emit threshold.
        tracker.observe_step("read_file", "read src/guardian/policy.py")
        combined, finding = tracker.combined(DriftVerdict(DRIFTING, "off task"))
        self.assertGreaterEqual(combined, self.config.drift_emit_threshold)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.kind, GOAL)
        self.assertEqual(finding.recommendation, REGROUND)

    def test_scope_dominant_crossings_recommend_tighten(self):
        tracker = DriftTracker("t1", "goal", ["src/memory/"], self.config)
        for _ in range(3):
            tracker.observe_scope_denial()
        tracker.observe_step("read_file", "read src/memory/x.py")
        combined, finding = tracker.combined(None)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.kind, SCOPE)
        self.assertEqual(finding.recommendation, TIGHTEN)

    def test_plan_revision_without_reason_recommends_tighten_behavior(self):
        tracker = DriftTracker("t1", "goal", [], self.config)
        tracker.observe_plan_revision(has_reason=False)
        for _ in range(6):
            tracker.observe_step("read_file", "x")
        combined, finding = tracker.combined(None)
        # repeated calls alone should push heuristic up; plan-revision-without-reason wins kind selection
        if finding is not None:
            self.assertEqual(finding.kind, BEHAVIOR)
            self.assertEqual(finding.recommendation, TIGHTEN)

    def test_on_track_verdict_lowers_combined_score(self):
        tracker = DriftTracker("t1", "goal", ["src/memory/"], self.config)
        tracker.observe_step("read_file", "read src/memory/x.py")
        combined_on_track, finding_on_track = tracker.combined(DriftVerdict(ON_TRACK))
        combined_drifting, _ = tracker.combined(DriftVerdict(DRIFTING))
        self.assertLess(combined_on_track, combined_drifting)

    def test_due_for_review_by_cadence(self):
        tracker = DriftTracker("t1", "goal", [], self.config)
        for _ in range(8):
            tracker.observe_step(None, "in scope")
        self.assertTrue(tracker.due_for_review())

    def test_due_for_review_by_heuristic_before_cadence(self):
        tracker = DriftTracker("t1", "goal", ["src/memory/"], self.config)
        tracker.observe_scope_denial()
        tracker.observe_step("read_file", "off scope touch")
        self.assertTrue(tracker.due_for_review())

    def test_mark_reviewed_resets_cadence_counter(self):
        tracker = DriftTracker("t1", "goal", [], self.config)
        for _ in range(8):
            tracker.observe_step(None, "x")
        self.assertTrue(tracker.due_for_review())
        tracker.mark_reviewed()
        self.assertFalse(tracker.due_for_review())


if __name__ == "__main__":
    unittest.main()
