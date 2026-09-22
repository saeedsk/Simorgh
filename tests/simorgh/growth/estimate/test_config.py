"""`[growth.estimate]` carries only the keys something reads.

Six keys (`max_draft_attempts`, `max_pipeline_wall_seconds`,
`action_timeout_seconds`, `verify_timeout_seconds`, `hot_swap_slots`,
`max_concurrent_pipelines`) belonged to the PatchPipeline retired on
2026-09-18 and were parsed into the dataclass with no reader. Removed
2026-09-19; writing one now changes nothing, so the Kernel's config
check reports the section instead of the key sailing through silently.
"""

import dataclasses
import unittest

from simorgh.growth.estimate.config import Config

_RETIRED = ("max_draft_attempts", "max_pipeline_wall_seconds", "action_timeout_seconds",
            "verify_timeout_seconds", "hot_swap_slots", "max_concurrent_pipelines")


class TestLearningConfig(unittest.TestCase):
    def test_only_the_live_keys_remain(self) -> None:
        self.assertEqual(
            {f.name for f in dataclasses.fields(Config)},
            {"explore_bonus", "min_samples_for_trust", "blocked_sample_weight",
             "unverified_sample_weight", "eval_sample_weight", "eval_suites",
             "evals_record", "competence_half_life_days"},
        )

    def test_a_retired_key_changes_nothing(self) -> None:
        for key in _RETIRED:
            with self.subTest(key=key):
                self.assertEqual(Config.from_mapping({key: 1}), Config())

    def test_the_live_keys_are_read(self) -> None:
        config = Config.from_mapping({"explore_bonus": 0.3, "min_samples_for_trust": 7,
                                      "blocked_sample_weight": 0.25})
        self.assertEqual((config.explore_bonus, config.min_samples_for_trust, config.blocked_sample_weight),
                         (0.3, 7, 0.25))


if __name__ == "__main__":
    unittest.main()
