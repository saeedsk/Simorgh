import tempfile
import unittest
from pathlib import Path

from src.memory.long_term import InMemoryStore, JSONFileMemoryStore, MemoryRecord


class MemoryStoreContractTests:
    """Shared behavior contract, run against every MemoryStore backend."""

    def make_store(self):
        raise NotImplementedError

    def test_remember_then_get_round_trips(self):
        store = self.make_store()
        record = store.remember("episodic", "met the creator", mood="curious")

        fetched = store.get(record.id)

        self.assertEqual(fetched.content, "met the creator")
        self.assertEqual(fetched.metadata["mood"], "curious")

    def test_get_missing_id_returns_none(self):
        store = self.make_store()
        self.assertIsNone(store.get("does-not-exist"))

    def test_query_returns_most_recent_first(self):
        store = self.make_store()
        store.remember("episodic", "first")
        store.remember("episodic", "second")
        store.remember("episodic", "third")

        contents = [r.content for r in store.query()]

        self.assertEqual(contents, ["third", "second", "first"])

    def test_query_filters_by_kind(self):
        store = self.make_store()
        store.remember("episodic", "did a thing")
        store.remember("semantic", "learned a fact")

        results = store.query(kind="semantic")

        self.assertEqual([r.content for r in results], ["learned a fact"])

    def test_query_respects_limit(self):
        store = self.make_store()
        for i in range(5):
            store.remember("episodic", str(i))

        results = store.query(limit=2)

        self.assertEqual(len(results), 2)


class TestInMemoryStore(MemoryStoreContractTests, unittest.TestCase):
    def make_store(self):
        return InMemoryStore()


class TestJSONFileMemoryStore(MemoryStoreContractTests, unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._path = Path(self._tmpdir.name) / "memory.jsonl"

    def tearDown(self):
        self._tmpdir.cleanup()

    def make_store(self):
        return JSONFileMemoryStore(self._path)

    def test_records_survive_across_store_instances(self):
        store = self.make_store()
        store.remember("episodic", "persisted fact")

        reloaded = JSONFileMemoryStore(self._path)

        self.assertEqual([r.content for r in reloaded.query()], ["persisted fact"])

    def test_creates_parent_directories(self):
        nested_path = Path(self._tmpdir.name) / "nested" / "dir" / "memory.jsonl"
        store = JSONFileMemoryStore(nested_path)

        store.remember("episodic", "hello")

        self.assertTrue(nested_path.exists())


if __name__ == "__main__":
    unittest.main()
