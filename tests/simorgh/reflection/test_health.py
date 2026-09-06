import unittest

from simorgh.reflection.config import Config
from simorgh.reflection.health import CRITICAL, NONE, REQUEST_RESET, WARN, HealthMonitor


class TestHealthMonitor(unittest.TestCase):
    def setUp(self):
        self.config = Config(health_window=6, health_extreme=0.9, health_pinned_n=4, health_load_ceiling=0.9, health_oscillation_warn=4, health_oscillation_critical=6)
        self.monitor = HealthMonitor(self.config)

    def test_empty_buffer_returns_none(self):
        self.assertIsNone(self.monitor.inspect())

    def test_below_thresholds_returns_none(self):
        for i in range(6):
            self.monitor.observe(0.1, 0.1, 0.2, "logic", float(i))
        self.assertIsNone(self.monitor.inspect())

    def test_pinned_valence_is_critical_with_reset_request(self):
        for i in range(4):
            self.monitor.observe(-0.95, 0.0, 0.1, "logic", float(i))
        finding = self.monitor.inspect()
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, CRITICAL)
        self.assertEqual(finding.action_taken, REQUEST_RESET)
        self.assertIn("valence", finding.detail)

    def test_pinned_arousal_is_critical(self):
        for i in range(4):
            self.monitor.observe(0.0, 0.95, 0.1, "logic", float(i))
        finding = self.monitor.inspect()
        self.assertEqual(finding.severity, CRITICAL)
        self.assertIn("arousal", finding.detail)

    def test_sustained_load_across_full_window_is_critical(self):
        for i in range(6):
            self.monitor.observe(0.0, 0.0, 0.95, "logic", float(i))
        finding = self.monitor.inspect()
        self.assertEqual(finding.severity, CRITICAL)
        self.assertEqual(finding.action_taken, REQUEST_RESET)

    def test_load_below_ceiling_for_one_sample_is_not_critical(self):
        for i in range(5):
            self.monitor.observe(0.0, 0.0, 0.95, "logic", float(i))
        self.monitor.observe(0.0, 0.0, 0.1, "logic", 5.0)  # one dip breaks "sustained"
        finding = self.monitor.inspect()
        self.assertIsNone(finding)

    def test_rapid_oscillation_is_critical_at_configured_flip_count(self):
        # window=6 -> exactly 5 consecutive-pair flips is the max the
        # retained buffer can show; use a config whose critical threshold
        # that count actually reaches, rather than assuming pre-eviction
        # sample count translates directly into in-window flips.
        config = Config(health_window=6, health_extreme=0.9, health_pinned_n=4, health_load_ceiling=0.9, health_oscillation_warn=3, health_oscillation_critical=5)
        monitor = HealthMonitor(config)
        values = [0.5, -0.5, 0.5, -0.5, 0.5, -0.5]
        for i, v in enumerate(values):
            monitor.observe(v, 0.0, 0.1, "logic", float(i))
        finding = monitor.inspect()
        self.assertEqual(finding.severity, CRITICAL)
        self.assertIn("oscillat", finding.detail)

    def test_moderate_oscillation_is_warn_not_critical(self):
        values = [0.5, -0.5, 0.5, -0.5, 0.5]
        for i, v in enumerate(values):
            self.monitor.observe(v, 0.0, 0.1, "logic", float(i))
        finding = self.monitor.inspect()
        self.assertEqual(finding.severity, WARN)
        self.assertEqual(finding.action_taken, NONE)

    def test_health_reset_source_is_not_observed_loop_guard(self):
        for i in range(4):
            self.monitor.observe(-0.95, 0.0, 0.1, "logic", float(i))
        self.assertIsNotNone(self.monitor.inspect())
        # A reset-sourced sample must not be treated as a fresh signal.
        self.monitor.observe(0.0, 0.0, 0.0, "health_reset", 10.0)
        # buffer unchanged in length by the guarded sample:
        self.assertEqual(len(self.monitor._buf), 4)  # noqa: SLF001

    def test_window_eviction_keeps_only_the_configured_size(self):
        for i in range(10):
            self.monitor.observe(0.1 * i, 0.0, 0.1, "logic", float(i))
        self.assertEqual(len(self.monitor._buf), 6)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
