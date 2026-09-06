import unittest

from simorgh.reflection.config import Config
from simorgh.reflection.patterns import PatternMiner


class TestPatternMiner(unittest.TestCase):
    def setUp(self):
        self.config = Config(pattern_window_seconds=100.0, pattern_min_rate=0.5, pattern_min_samples=3)
        self.miner = PatternMiner(self.config)

    def test_below_min_samples_produces_nothing(self):
        self.miner.add("patch", False, None, 1.0)
        self.miner.add("patch", False, None, 2.0)
        self.assertEqual(self.miner.mine(10.0), [])

    def test_below_min_rate_produces_nothing(self):
        for i in range(4):
            self.miner.add("patch", i != 0, None, float(i))  # 1/4 failure = 25% < 50%
        self.assertEqual(self.miner.mine(10.0), [])

    def test_high_failure_rate_with_enough_samples_is_flagged(self):
        self.miner.add("patch", False, None, 1.0)
        self.miner.add("patch", False, None, 2.0)
        self.miner.add("patch", True, None, 3.0)
        patterns = self.miner.mine(10.0)
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].task_type, "patch")
        self.assertAlmostEqual(patterns[0].rate, 2 / 3)
        self.assertIn("patch", patterns[0].proposal)

    def test_different_strategies_are_grouped_separately(self):
        self.miner.add("patch", False, "search_replace", 1.0)
        self.miner.add("patch", False, "search_replace", 2.0)
        self.miner.add("patch", False, "search_replace", 3.0)
        self.miner.add("patch", True, "full_rewrite", 4.0)
        self.miner.add("patch", True, "full_rewrite", 5.0)
        self.miner.add("patch", True, "full_rewrite", 6.0)
        patterns = self.miner.mine(10.0)
        self.assertEqual(len(patterns), 1)
        self.assertIn("search_replace", patterns[0].proposal)

    def test_samples_outside_the_window_are_pruned(self):
        self.miner.add("patch", False, None, 1.0)
        self.miner.add("patch", False, None, 2.0)
        self.miner.add("patch", False, None, 3.0)
        # now is far enough that the window (100s) no longer covers ts=1..3
        self.assertEqual(self.miner.mine(500.0), [])


if __name__ == "__main__":
    unittest.main()
