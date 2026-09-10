import unittest

from simorgh.reflection.calibration import CalibrationTable
from simorgh.reflection.config import Config


class TestCalibrationTable(unittest.TestCase):
    def setUp(self):
        self.config = Config(calibration_bins=10, calibration_min_samples=4)
        self.table = CalibrationTable(self.config)

    def test_below_min_samples_returns_none(self):
        self.table.record("patch", 0.8, True)
        self.table.record("patch", 0.8, True)
        self.assertIsNone(self.table.summary("patch"))

    def test_unknown_task_type_returns_none(self):
        self.assertIsNone(self.table.summary("nonexistent"))

    def test_perfectly_calibrated_has_zero_brier(self):
        for _ in range(4):
            self.table.record("patch", 1.0, True)
        summary = self.table.summary("patch")
        self.assertIsNotNone(summary)
        self.assertAlmostEqual(summary.brier, 0.0)
        self.assertAlmostEqual(summary.empirical_accuracy, 1.0)

    def test_overconfident_shows_accuracy_below_stated(self):
        # stated 0.8 confidence, but only half actually succeed
        self.table.record("patch", 0.8, True)
        self.table.record("patch", 0.8, True)
        self.table.record("patch", 0.8, False)
        self.table.record("patch", 0.8, False)
        summary = self.table.summary("patch")
        self.assertAlmostEqual(summary.stated_confidence, 0.8)
        self.assertAlmostEqual(summary.empirical_accuracy, 0.5)
        self.assertGreater(summary.brier, 0.0)

    def test_task_types_are_independent(self):
        for _ in range(4):
            self.table.record("patch", 0.9, True)
        self.assertIsNone(self.table.summary("research"))
        self.assertIsNotNone(self.table.summary("patch"))

    def test_bins_bucket_by_stated_confidence(self):
        for _ in range(4):
            self.table.record("patch", 0.85, True)
        summary = self.table.summary("patch")
        populated = [b for b in summary.bins if b[2] > 0]
        self.assertEqual(len(populated), 1)
        lo, hi, n, hits = populated[0]
        self.assertLessEqual(lo, 0.85)
        self.assertGreater(hi, 0.85)
        self.assertEqual(n, 4)
        self.assertEqual(hits, 4)

    def test_task_types_lists_every_recorded_type(self):
        self.table.record("patch", 0.5, True)
        self.table.record("research", 0.5, True)
        self.assertEqual(set(self.table.task_types()), {"patch", "research"})


class TestAConfidenceThatIsNotAProbability(unittest.TestCase):
    """Every one of these used to take the whole reflection pass down.

    `_on_outcome_recorded`, `_on_verify_result` and `_on_task_terminal`
    pass the wire `confidence` straight to `record()` behind nothing but
    an `isinstance(x, (int, float))` check, which NaN, inf and -3.0 all
    satisfy. `summary()` then died in `int()` or indexed `bins[-30]`,
    and because the pass loops over task types, every type after the bad
    one silently never published -- on that tick and every tick after
    (observer bulk5-02, 2026-09-10).
    """

    def setUp(self):
        self.table = CalibrationTable(Config(calibration_bins=10, calibration_min_samples=1))

    def test_a_negative_confidence_is_refused_not_indexed(self):
        self.assertFalse(self.table.record("patch", -3.0, True))
        self.assertIsNone(self.table.summary("patch"), "an unusable sample must not become a data point")
        self.assertEqual(self.table.unusable("patch"), 1)

    def test_nan_is_refused(self):
        self.assertFalse(self.table.record("patch", float("nan"), True))
        self.assertEqual(self.table.unusable("patch"), 1)

    def test_infinity_is_refused(self):
        self.assertFalse(self.table.record("patch", float("inf"), False))
        self.assertEqual(self.table.unusable("patch"), 1)

    def test_above_one_is_refused(self):
        self.assertFalse(self.table.record("patch", 5.0, True))
        self.assertEqual(self.table.unusable("patch"), 1)

    def test_a_bad_sample_does_not_poison_the_good_ones(self):
        self.table.record("patch", float("nan"), True)
        self.table.record("patch", 0.8, True)
        self.table.record("patch", 0.8, False)
        summary = self.table.summary("patch")
        self.assertEqual(summary.samples, 2, "the unusable sample is excluded, not clamped in")
        self.assertAlmostEqual(summary.stated_confidence, 0.8)
        self.assertAlmostEqual(summary.empirical_accuracy, 0.5)

    def test_the_boundaries_are_still_usable(self):
        self.assertTrue(self.table.record("patch", 0.0, False))
        self.assertTrue(self.table.record("patch", 1.0, True))
        self.assertEqual(self.table.summary("patch").samples, 2)

    def test_zero_bins_is_a_misconfiguration_not_a_crash(self):
        table = CalibrationTable(Config(calibration_bins=0, calibration_min_samples=1))
        table.record("patch", 0.5, True)
        self.assertEqual(table.summary("patch").samples, 1)


if __name__ == "__main__":
    unittest.main()
