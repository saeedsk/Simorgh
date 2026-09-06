import unittest

from simorgh.curiosity.api import Area, DriveContext, Gap
from simorgh.curiosity.config import Config
from simorgh.curiosity.drives import DriveEngine


def _ctx(**overrides) -> DriveContext:
    base = dict(
        areas=(Area(name="cognition", modules=("a.py",)),),
        gaps=(), interests=(), boredom=0.0,
        staleness_by_area={}, staleness_horizon=7 * 86400.0,
    )
    base.update(overrides)
    return DriveContext(**base)


class DriveEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = DriveEngine(Config())

    def test_unknown_area_defaults_to_0_6_gap(self):
        scores = self.engine.score_area("cognition", _ctx())
        self.assertAlmostEqual(scores["gap"], 0.6)

    def test_high_confidence_high_competence_gap_beats_unknown_default(self):
        ctx = _ctx(gaps=(Gap(competence="cognition", task_type="cognition.think", score=0.95, samples=20),))
        scores = self.engine.score_area("cognition", ctx)
        self.assertLess(scores["gap"], 0.6)
        self.assertAlmostEqual(scores["gap"], 1.0 - 0.95, places=6)  # confidence=1.0 -> gap_value = 1-score

    def test_high_confidence_low_competence_gap_exceeds_unknown_default(self):
        ctx = _ctx(gaps=(Gap(competence="cognition", task_type="cognition.think", score=0.1, samples=20),))
        scores = self.engine.score_area("cognition", ctx)
        self.assertGreater(scores["gap"], 0.6)
        self.assertAlmostEqual(scores["gap"], 1.0 - 0.1, places=6)

    def test_low_confidence_gap_pulls_toward_unknown_default(self):
        ctx = _ctx(gaps=(Gap(competence="cognition", task_type="cognition.think", score=0.1, samples=1),))
        scores = self.engine.score_area("cognition", ctx)
        # confidence = 1/8 = 0.125, blended = 0.125*0.9 + 0.875*0.6 = 0.6375
        self.assertAlmostEqual(scores["gap"], 0.125 * 0.9 + 0.875 * 0.6, places=6)

    def test_never_touched_area_is_maximally_stale(self):
        scores = self.engine.score_area("cognition", _ctx(staleness_by_area={}))
        self.assertEqual(scores["staleness"], 1.0)

    def test_staleness_scales_with_horizon(self):
        ctx = _ctx(staleness_by_area={"cognition": 3.5 * 86400.0}, staleness_horizon=7 * 86400.0)
        scores = self.engine.score_area("cognition", ctx)
        self.assertAlmostEqual(scores["staleness"], 0.5)

    def test_interest_lexical_match(self):
        ctx = _ctx(interests=("cognition roadmap",))
        scores = self.engine.score_area("cognition", ctx)
        self.assertEqual(scores["interest"], 1.0)

    def test_no_interest_match_scores_zero(self):
        ctx = _ctx(interests=("unrelated topic",))
        scores = self.engine.score_area("cognition", ctx)
        self.assertEqual(scores["interest"], 0.0)

    def test_boredom_passed_through_uniformly(self):
        scores = self.engine.score_area("cognition", _ctx(boredom=0.75))
        self.assertEqual(scores["boredom"], 0.75)

    def test_total_is_weighted_blend(self):
        ctx = _ctx(staleness_by_area={"cognition": 0.0}, boredom=0.0)
        scores = self.engine.score_area("cognition", ctx)
        weights = self.engine.config.drive_weights
        expected = weights["gap"] * scores["gap"] + weights["staleness"] * scores["staleness"] + weights["interest"] * scores["interest"] + weights["boredom"] * scores["boredom"]
        self.assertAlmostEqual(scores["total"], expected)

    def test_temperature_rises_with_arousal_only_when_positive(self):
        base = self.engine.temperature(0.0)
        self.assertGreater(self.engine.temperature(1.0), base)
        self.assertEqual(self.engine.temperature(-1.0), base)  # negative arousal never lowers it

    def test_research_prior_multiplier_kicks_in_below_threshold(self):
        self.assertEqual(self.engine.research_prior_multiplier(-0.5), 1.5)
        self.assertEqual(self.engine.research_prior_multiplier(-0.4), 1.0)
        self.assertEqual(self.engine.research_prior_multiplier(0.0), 1.0)


if __name__ == "__main__":
    unittest.main()
