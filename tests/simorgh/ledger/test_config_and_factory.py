import tempfile
import unittest
from pathlib import Path

from .helpers import make_event
from simorgh.ledger.api import BackendUnavailable
from simorgh.ledger.config import Config
from simorgh.ledger.factory import make_backend, make_ledger


class TestConfig(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = Config.from_mapping(None, env={})
        self.assertEqual(cfg.backend, "jsonl")
        self.assertEqual(cfg.keep_tail, 50)
        self.assertTrue(cfg.fsync)
        self.assertFalse(cfg.allow_fallback)

    def test_env_overrides_take_priority_over_the_mapping(self) -> None:
        cfg = Config.from_mapping(
            {"backend": "sqlite", "data_dir": "/mapping/path"},
            env={"SIMORGH_LEDGER_BACKEND": "memory", "SIMORGH_LEDGER_DIR": "/env/path"},
        )
        self.assertEqual(cfg.backend, "memory")
        self.assertEqual(cfg.data_dir, "/env/path")

    def test_unknown_backend_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Config.from_mapping({"backend": "carrier-pigeon"}, env={})

    def test_retention_and_keep_tail_are_read_from_the_nested_mapping(self) -> None:
        cfg = Config.from_mapping({"retention": {"task:": "forever", "keep_tail": 5}}, env={})
        self.assertEqual(cfg.keep_tail, 5)
        self.assertNotIn("keep_tail", cfg.retention)
        self.assertEqual(cfg.retention["task:"], "forever")

    def test_dynamodb_table_and_bucket_are_read_from_the_nested_mapping(self) -> None:
        cfg = Config.from_mapping({"dynamodb": {"table": "t", "bucket": "b"}}, env={})
        self.assertEqual((cfg.dynamodb_table, cfg.dynamodb_bucket), ("t", "b"))

    def test_data_path_expands_the_home_directory(self) -> None:
        cfg = Config(data_dir="~/.simorgh/ledger")
        self.assertNotIn("~", str(cfg.data_path))


class TestMakeBackend(unittest.TestCase):
    def test_dynamodb_without_table_or_bucket_is_unavailable(self) -> None:
        with self.assertRaises(BackendUnavailable):
            make_backend(Config(backend="dynamodb"))

    def test_unknown_backend_name_is_unavailable(self) -> None:
        cfg = Config.from_mapping({"backend": "jsonl"}, env={})
        object.__setattr__(cfg, "backend", "not-a-real-backend")  # bypass from_mapping's own validation
        with self.assertRaises(BackendUnavailable):
            make_backend(cfg)


class TestMakeLedger(unittest.IsolatedAsyncioTestCase):
    async def test_memory_backend_round_trip(self) -> None:
        client = make_ledger(Config(backend="memory"))
        await client.start()
        seq = await client.append("task:a", make_event("task:a"))
        self.assertEqual(seq, 1)
        await client.stop()

    async def test_jsonl_backend_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = make_ledger(Config(backend="jsonl", data_dir=tmp))
            await client.start()
            await client.append("task:a", make_event("task:a"))
            self.assertEqual(await client.head("task:a"), 1)
            await client.stop()

    async def test_fallback_to_jsonl_when_allowed_and_the_configured_backend_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(backend="dynamodb", allow_fallback=True, data_dir=tmp)
            client = make_ledger(cfg)
            self.assertIsNotNone(client.fallback_reason)  # type: ignore[attr-defined]
            await client.start()
            await client.append("task:a", make_event("task:a"))
            await client.stop()

    async def test_no_silent_fallback_without_allow_fallback(self) -> None:
        with self.assertRaises(BackendUnavailable):
            make_ledger(Config(backend="dynamodb", allow_fallback=False))


if __name__ == "__main__":
    unittest.main()
