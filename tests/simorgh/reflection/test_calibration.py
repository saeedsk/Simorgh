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


if __name__ == "__main__":
    unittest.main()
