import unittest

from simorgh.curiosity.config import Config


class ConfigTest(unittest.TestCase):
    def test_drive_weights_normalize_to_one(self):
        weights = Config().drive_weights
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_drive_weights_preserve_relative_order(self):
        weights = Config().drive_weights
        self.assertGreater(weights["gap"], weights["staleness"])
        self.assertGreater(weights["staleness"], weights["interest"])
        self.assertGreater(weights["interest"], weights["boredom"])

    def test_from_mapping_none_returns_defaults(self):
        self.assertEqual(Config.from_mapping(None), Config())

    def test_from_mapping_overrides_known_fields(self):
        cfg = Config.from_mapping({"candidates_per_tick": 5, "temperature": 1.2})
        self.assertEqual(cfg.candidates_per_tick, 5)
        self.assertEqual(cfg.temperature, 1.2)

    def test_from_mapping_ignores_unknown_fields(self):
        cfg = Config.from_mapping({"not_a_real_field": 1})
        self.assertEqual(cfg, Config())

    def test_from_mapping_parses_focus(self):
        cfg = Config.from_mapping({"focus": {"cognition": 2.0}})
        self.assertEqual(cfg.focus, {"cognition": 2.0})

    def test_from_mapping_parses_interest_default_topics(self):
        cfg = Config.from_mapping({"interest_default_topics": [["https://x/feed", "label"]]})
        self.assertEqual(cfg.interest_default_topics, (("https://x/feed", "label"),))


if __name__ == "__main__":
    unittest.main()
