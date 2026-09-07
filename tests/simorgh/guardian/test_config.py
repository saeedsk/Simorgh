"""`Config.from_mapping` (09-guardian.md section 3.5): builds from a
TOML-style dict, ignoring unknown keys and coercing list fields to the
tuples the frozen dataclass expects."""

import unittest
import unittest.mock

from simorgh.guardian.config import DEFAULT_DENYLIST, DEFAULT_PROTECTED_SUBJECTS, Config


class TestConfigFromMapping(unittest.TestCase):
    def test_none_or_empty_returns_defaults(self):
        self.assertEqual(Config.from_mapping(None), Config())
        self.assertEqual(Config.from_mapping({}), Config())

    def test_overrides_known_fields(self):
        config = Config.from_mapping({"mode": "trusted", "approval_ttl_s": 60.0})
        self.assertEqual(config.mode, "trusted")
        self.assertEqual(config.approval_ttl_s, 60.0)

    def test_unknown_keys_are_ignored(self):
        config = Config.from_mapping({"mode": "trusted", "not_a_real_field": 123})
        self.assertEqual(config.mode, "trusted")
        self.assertFalse(hasattr(config, "not_a_real_field"))

    def test_list_fields_are_coerced_to_tuples(self):
        config = Config.from_mapping({
            "protected_subjects": ["a", "b"], "autonomous_origins": ["curiosity"],
        })
        self.assertEqual(config.protected_subjects, ("a", "b"))
        self.assertEqual(config.autonomous_origins, ("curiosity",))
        self.assertIsInstance(config.protected_subjects, tuple)

    def test_defaults_carry_the_ported_v1_protected_subjects_and_denylist(self):
        config = Config()
        self.assertEqual(config.protected_subjects, DEFAULT_PROTECTED_SUBJECTS)
        self.assertIn("docs/SOUL.md", config.protected_subjects)
        self.assertEqual(dict(config.denylist), DEFAULT_DENYLIST)

    def test_dataclass_default_still_requires_human_approval(self):
        """Kept safe on purpose (`kernel/service.py::boot`'s own comment
        on why its baseline diverges) -- `guardian/test_rules.py::
        test_irreversible_escalates_by_default` depends on exactly this."""
        self.assertTrue(Config().irreversible_requires_human)

    def test_shell_env_var_enables_auto_approve_regardless_of_the_file(self):
        with unittest.mock.patch.dict("os.environ", {"SIMORGH_GUARDIAN_AUTO_APPROVE": "1"}):
            self.assertFalse(Config.from_mapping(None).irreversible_requires_human)
            self.assertFalse(Config.from_mapping({"irreversible_requires_human": True}).irreversible_requires_human)

    def test_shell_env_var_off_values_require_human_approval(self):
        for off in ("0", "false", "no", "off", "anything-else"):
            with unittest.mock.patch.dict("os.environ", {"SIMORGH_GUARDIAN_AUTO_APPROVE": off}):
                self.assertTrue(Config.from_mapping({"irreversible_requires_human": False}).irreversible_requires_human)

    def test_no_env_var_leaves_the_file_and_default_alone(self):
        with unittest.mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("SIMORGH_GUARDIAN_AUTO_APPROVE", None)
            self.assertTrue(Config.from_mapping(None).irreversible_requires_human)
            self.assertFalse(Config.from_mapping({"irreversible_requires_human": False}).irreversible_requires_human)


if __name__ == "__main__":
    unittest.main()
