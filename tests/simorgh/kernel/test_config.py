import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.kernel.config import ConfigError, LoadedConfig, find_config_path, load_config, load_runtime_config


class TestLoadRuntimeConfig(unittest.TestCase):
    def test_defaults_with_no_section(self):
        cfg = load_runtime_config(None)
        self.assertEqual(cfg.mode, "single")
        self.assertEqual(cfg.idle_threshold_s, 10.0)

    def test_invalid_mode_raises(self):
        with self.assertRaises(ConfigError):
            load_runtime_config({"mode": "bogus"})

    def test_data_dir_expands_user(self):
        cfg = load_runtime_config({"data_dir": "~/.simorgh-test"})
        self.assertEqual(cfg.data_dir, Path("~/.simorgh-test").expanduser())

    def test_env_override_wins_over_file(self):
        with mock.patch.dict(os.environ, {"SIMORGH_RUNTIME_IDLE_THRESHOLD_S": "42"}):
            cfg = load_runtime_config({"idle_threshold_s": 5})
        self.assertEqual(cfg.idle_threshold_s, 42.0)

    def test_bool_env_override(self):
        with mock.patch.dict(os.environ, {"SIMORGH_RUNTIME_ALLOW_BACKEND_FALLBACK": "true"}):
            cfg = load_runtime_config({})
        self.assertTrue(cfg.allow_backend_fallback)

    def test_subsystems_string_becomes_tuple(self):
        cfg = load_runtime_config({"subsystems": "all"})
        self.assertEqual(cfg.subsystems, ("all",))


class TestLoadedConfig(unittest.TestCase):
    def test_section_missing_returns_empty_dict_not_keyerror(self):
        config = LoadedConfig({}, None)
        self.assertEqual(config.section("cognition"), {})

    def test_hash_is_stable_for_same_content(self):
        a = LoadedConfig({"runtime": {"mode": "single"}}, None)
        b = LoadedConfig({"runtime": {"mode": "single"}}, None)
        self.assertEqual(a.hash, b.hash)

    def test_hash_differs_for_different_content(self):
        a = LoadedConfig({"runtime": {"mode": "single"}}, None)
        b = LoadedConfig({"runtime": {"mode": "local-multi"}}, None)
        self.assertNotEqual(a.hash, b.hash)


class TestFindConfigPath(unittest.TestCase):
    def test_explicit_path_wins(self):
        self.assertEqual(find_config_path("/tmp/x.toml"), Path("/tmp/x.toml"))

    def test_env_var_used_when_no_explicit(self):
        with mock.patch.dict(os.environ, {"SIMORGH_CONFIG": "/tmp/env.toml"}):
            self.assertEqual(find_config_path(None), Path("/tmp/env.toml"))

    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                self.assertIsNone(find_config_path(None, data_dir=Path(tmp) / "nowhere"))
            finally:
                os.chdir(cwd)


class TestLoadConfig(unittest.TestCase):
    def test_load_config_with_real_toml_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "simorgh.toml"
            path.write_text('[runtime]\nmode = "local-multi"\n')
            config = load_config(str(path))
            self.assertEqual(config.runtime.mode, "local-multi")

    def test_load_config_missing_file_uses_defaults(self):
        config = load_config("/definitely/not/a/real/path.toml")
        self.assertEqual(config.runtime.mode, "single")


if __name__ == "__main__":
    unittest.main()
