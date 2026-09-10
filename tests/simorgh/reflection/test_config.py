"""`review_timeout_s` and `max_concurrent_reviews` were absent from
`Config.from_mapping`'s `cls(...)` call entirely -- not read into a
nested or differently-named key, simply never passed at all, so the
dataclass default always won regardless of simorgh.toml. Confirmed live
by an observer 2026-09-08: writing max_concurrent_reviews=6 left the
running semaphore at the default of 2.
"""

from __future__ import annotations

import unittest

from simorgh.reflection.config import Config


class TestEveryFieldFromMappingActuallyReads(unittest.TestCase):
    def test_review_timeout_s_is_read(self) -> None:
        self.assertEqual(Config.from_mapping({"review_timeout_s": 45.0}).review_timeout_s, 45.0)

    def test_max_concurrent_reviews_is_read(self) -> None:
        self.assertEqual(Config.from_mapping({"max_concurrent_reviews": 6}).max_concurrent_reviews, 6)

    def test_both_together_alongside_an_already_working_field(self) -> None:
        config = Config.from_mapping({
            "review_timeout_s": 45.0, "max_concurrent_reviews": 6, "denial_window_seconds": 111.0,
        })
        self.assertEqual((config.review_timeout_s, config.max_concurrent_reviews, config.denial_window_seconds),
                        (45.0, 6, 111.0))

    def test_absent_keys_keep_the_dataclass_default(self) -> None:
        config = Config.from_mapping({})
        self.assertEqual(config.review_timeout_s, Config.review_timeout_s)
        self.assertEqual(config.max_concurrent_reviews, Config.max_concurrent_reviews)


class TestDistillationKeysAreRead(unittest.TestCase):
    """The same bug as the two above, in three more keys, found by an
    observer on 2026-09-10: `service.py` reads `distillation_enabled`,
    `max_distillations_per_day` and `skill_dir` at runtime, but
    `from_mapping` never passed any of them to `cls(...)`, so
    simorgh.toml could not change any of them."""

    def test_max_distillations_per_day_is_read(self) -> None:
        self.assertEqual(Config.from_mapping({"max_distillations_per_day": 99}).max_distillations_per_day, 99)

    def test_distillation_can_be_switched_off(self) -> None:
        self.assertFalse(Config.from_mapping({"distillation_enabled": False}).distillation_enabled)

    def test_skill_dir_is_read(self) -> None:
        self.assertEqual(Config.from_mapping({"skill_dir": "my_skills"}).skill_dir, "my_skills")

    def test_reflection_pass_cadence_is_read(self) -> None:
        config = Config.from_mapping({"reflect_after_start_s": 1.5, "reflect_every_s": 30.0})
        self.assertEqual((config.reflect_after_start_s, config.reflect_every_s), (1.5, 30.0))


class TestNoFieldIsUnreachableFromAMapping(unittest.TestCase):
    """Three separate sweeps have now found a `[reflection]` field the
    running code reads and `from_mapping` silently drops. This test is
    the one that makes the fourth impossible to add quietly: every
    dataclass field must be settable from some mapping key, and a new
    field with no key here fails loudly instead of looking configurable
    while being a constant.
    """

    #: dataclass field -> the mapping path that sets it. A nested path
    #: is written "group.key", matching `from_mapping`'s own groups.
    KEYS = {
        "health_window": "health.window",
        "health_extreme": "health.extreme",
        "health_pinned_n": "health.pinned_n",
        "health_load_ceiling": "health.load_ceiling",
        "health_oscillation_warn": "health.oscillation_flips_warn",
        "health_oscillation_critical": "health.oscillation_flips_critical",
        "drift_check_every_steps": "drift_check_every_steps",
        "drift_heuristic_threshold": "drift_heuristic_threshold",
        "drift_emit_threshold": "drift_emit_threshold",
        "stall_idle_seconds": "stall_idle_seconds",
        "critique_max_tokens": "critique_max_tokens",
        "distillation_enabled": "distillation_enabled",
        "max_distillations_per_day": "max_distillations_per_day",
        "skill_dir": "skill_dir",
        "pattern_window_seconds": "pattern.window_seconds",
        "pattern_min_rate": "pattern.min_rate",
        "pattern_min_samples": "pattern.min_samples",
        "denial_window_seconds": "denial_window_seconds",
        "denial_min_repeats": "denial_min_repeats",
        "monitors_enabled": "monitors_enabled",
        "alert_warn_window_s": "alert_warn_window_s",
        "quiet_hours": "quiet_hours",
        "digest_enabled": "digest_enabled",
        "digest_hour": "digest_hour",
        "announce_critical": "announce_critical",
        "calibration_bins": "calibration.bins",
        "calibration_min_samples": "calibration.min_samples",
        "review_timeout_s": "review_timeout_s",
        "max_concurrent_reviews": "max_concurrent_reviews",
        "reflect_after_start_s": "reflect_after_start_s",
        "reflect_every_s": "reflect_every_s",
    }

    @staticmethod
    def _distinct(value):
        if isinstance(value, bool):
            return not value
        if isinstance(value, int):
            return value + 7
        if isinstance(value, float):
            return value + 7.5
        return f"{value}_changed"

    def test_every_field_has_a_mapping_key(self) -> None:
        missing = set(Config.__dataclass_fields__) - set(self.KEYS)
        self.assertEqual(missing, set(), f"fields with no entry in KEYS: {sorted(missing)}")

    def test_every_mapping_key_actually_changes_its_field(self) -> None:
        default = Config()
        unreachable = []
        for field, path in self.KEYS.items():
            want = self._distinct(getattr(default, field))
            if "." in path:
                group, key = path.split(".", 1)
                mapping = {group: {key: want}}
            else:
                mapping = {path: want}
            got = getattr(Config.from_mapping(mapping), field)
            if got != want:
                unreachable.append(f"{field} (via {path}): wrote {want!r}, config says {got!r}")
        self.assertEqual(unreachable, [], "\n".join(unreachable))


if __name__ == "__main__":
    unittest.main()
