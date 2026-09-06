import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.kernel.api import MissingSecret
from simorgh.kernel.secrets import (
    ChainedSecretStore,
    EnvSecretStore,
    FileSecretStore,
    ScopedSecretStore,
    SecretsFileUnsafe,
)


class TestEnvSecretStore(unittest.TestCase):
    def test_get_and_require(self):
        with mock.patch.dict(os.environ, {"MY_KEY": "abc"}):
            store = EnvSecretStore()
            self.assertEqual(store.get("MY_KEY"), "abc")
            self.assertEqual(store.require("MY_KEY"), "abc")

    def test_require_missing_raises(self):
        store = EnvSecretStore({})
        with self.assertRaises(MissingSecret):
            store.require("NOPE")


class TestFileSecretStore(unittest.TestCase):
    def test_reads_safe_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secrets.toml"
            path.write_text('GEMINI_API_KEY = "xyz"\n')
            path.chmod(0o600)
            store = FileSecretStore(path)
            self.assertEqual(store.get("GEMINI_API_KEY"), "xyz")

    def test_refuses_group_readable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secrets.toml"
            path.write_text('X = "y"\n')
            path.chmod(0o640)
            with self.assertRaises(SecretsFileUnsafe):
                FileSecretStore(path)

    def test_missing_file_is_empty_not_an_error(self):
        store = FileSecretStore(Path("/nonexistent/secrets.toml"))
        self.assertIsNone(store.get("ANYTHING"))


class TestChainedSecretStore(unittest.TestCase):
    def test_env_wins_over_file(self):
        env = EnvSecretStore({"KEY": "from_env"})
        file_only = EnvSecretStore({"KEY": "from_file", "OTHER": "file_only"})
        chained = ChainedSecretStore(env, file_only)
        self.assertEqual(chained.get("KEY"), "from_env")
        self.assertEqual(chained.get("OTHER"), "file_only")

    def test_require_missing_from_all_raises(self):
        chained = ChainedSecretStore(EnvSecretStore({}), EnvSecretStore({}))
        with self.assertRaises(MissingSecret):
            chained.require("NOPE")


class TestScopedSecretStore(unittest.TestCase):
    def test_allowed_name_passes_through(self):
        backing = EnvSecretStore({"A": "1", "B": "2"})
        scoped = ScopedSecretStore(backing, frozenset({"A"}))
        self.assertEqual(scoped.get("A"), "1")
        self.assertEqual(scoped.require("A"), "1")

    def test_unscoped_name_is_invisible_even_if_it_exists_in_the_backing_store(self):
        backing = EnvSecretStore({"A": "1", "B": "2"})
        scoped = ScopedSecretStore(backing, frozenset({"A"}))
        self.assertIsNone(scoped.get("B"))
        with self.assertRaises(MissingSecret):
            scoped.require("B")


if __name__ == "__main__":
    unittest.main()
