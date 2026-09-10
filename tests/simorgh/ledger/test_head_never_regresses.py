"""The head of a stream never goes backwards, in any backend, under any
state the process could have been handed.

9fbdab1 established the rule and gave `memory`, `sqlite` and `dynamodb`
a high-water mark -- but only `append` ever wrote that mark, so every
state in which the mark is absent while events are removed still hands a
sequence number back:

* a `sqlite` database or a `dynamodb` table written by the OLD code has
  no mark at all, so the first retention pass after the upgrade drops
  head to 0 and the next append reuses seq 1 -- the exact defect the
  commit fixed, on the exact data it was written for;
* `jsonl`, which the commit called the backend that already kept the
  rule, keeps its head only in memory and in `index.json`, which its own
  reader treats as disposable ("absent, truncated, written by an older
  layout -- means an empty index, which costs a full scan and is never
  wrong"). After a pass that empties a stream, the file is 0 bytes: a
  rescan reads head 0 out of it;
* and a second process sharing a `jsonl` directory rescans on any size
  change, so a compaction in process A makes process B reissue seq 1
  even though its own `head()` still answers 5.

Compaction is the only thing that removes events without removing the
stream, so the mark has to be written *there*, not only on append.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.envelope import Event


def _event(stream: str, n: int) -> Event:
    return Event(stream=stream, type="x", ts=float(n), trace_id="", causation_id=None, payload={"n": n})


async def _fill(backend, stream: str, count: int) -> None:
    for n in range(count):
        await backend.append(_event(stream, n), expected_seq=None)


class SqliteHeadTestCase(unittest.IsolatedAsyncioTestCase):
    async def _open(self, path: Path):
        from simorgh.ledger.backends.sqlite import SqliteBackend

        backend = SqliteBackend(path)
        await backend.start()
        self.addAsyncCleanup(backend.stop)
        return backend

    async def test_a_database_written_before_the_fix_still_does_not_reissue(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "l.db"
        old = await self._open(path)
        await _fill(old, "activity", 5)
        # Exactly the state the old code left behind: no `heads` table.
        await old._run(lambda c: c.execute("DROP TABLE heads"))  # noqa: SLF001
        await old.stop()

        new = await self._open(path)  # the new code re-creates `heads`, empty
        self.assertEqual(await new.head("activity"), 5)
        await new.truncate_below("activity", 6)  # one retention pass, all five expire
        self.assertEqual(await new.head("activity"), 5, "head regressed on a pre-fix database")
        self.assertEqual(await new.append(_event("activity", 99), expected_seq=None), 6)


class DynamoHeadTestCase(unittest.IsolatedAsyncioTestCase):
    async def _open(self):
        from simorgh.ledger.backends.dynamodb import DynamoBackend

        from .test_backends import _FakeBlobBucket, _FakeDynamoTable

        table = _FakeDynamoTable()
        backend = DynamoBackend("t", "b", table=table, bucket=_FakeBlobBucket())
        await backend.start()
        return backend, table

    async def test_a_table_written_before_the_fix_still_does_not_reissue(self) -> None:
        from simorgh.ledger.backends.dynamodb import HEAD_SK

        backend, table = await self._open()
        await _fill(backend, "activity", 5)
        table.delete("activity", HEAD_SK)  # pre-fix items: the mark was never written
        self.assertEqual(await backend.head("activity"), 5)
        await backend.truncate_below("activity", 6)
        self.assertEqual(await backend.head("activity"), 5, "head regressed on a pre-fix table")
        self.assertEqual(await backend.append(_event("activity", 99), expected_seq=None), 6)

    async def test_deleting_the_stream_still_starts_it_over(self) -> None:
        backend, _table = await self._open()
        await _fill(backend, "gone", 3)
        await backend.delete_stream("gone")
        self.assertEqual(await backend.head("gone"), 0)

    async def test_a_stale_mark_from_a_lost_race_is_repaired_before_truncation(self) -> None:
        """Two processes' `put`s can land in either order, so the mark on
        the table may be lower than the live head. Compaction re-derives
        it from the live items before removing them, and no append ever
        lowers it."""
        from simorgh.ledger.backends.dynamodb import DynamoBackend, HEAD_SK

        from .test_backends import _FakeBlobBucket, _FakeDynamoTable

        table = _FakeDynamoTable()

        class Reorder:
            """The lowest mark lands last -- the worst legal ordering."""

            def __init__(self, inner) -> None:
                self.inner, self.deferred, self.defer = inner, [], True

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def put(self, item) -> None:
                if self.defer and item["seq"] == HEAD_SK:
                    self.deferred.append(item)
                    return
                self.inner.put(item)

            def flush(self) -> None:
                for item in sorted(self.deferred, key=lambda i: -i["at_seq"]):
                    self.inner.put(item)
                self.deferred.clear()
                self.defer = False

        reordered = Reorder(table)
        backend = DynamoBackend("t", "b", table=reordered, bucket=_FakeBlobBucket())
        await backend.start()
        await _fill(backend, "activity", 5)
        reordered.flush()
        self.assertEqual(table.get("activity", HEAD_SK)["at_seq"], 1)  # a genuinely stale mark
        await backend.truncate_below("activity", 6)
        self.assertEqual(await backend.head("activity"), 5)
        self.assertEqual(await backend.append(_event("activity", 99), expected_seq=None), 6)


class JsonlHeadTestCase(unittest.IsolatedAsyncioTestCase):
    async def _open(self, root: Path):
        from simorgh.ledger.backends.jsonl import JsonlBackend

        backend = JsonlBackend(root, fsync=False)
        await backend.start()
        self.addAsyncCleanup(backend.stop)
        return backend

    def _root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    async def test_losing_index_json_does_not_reissue_a_compacted_seq(self) -> None:
        root = self._root()
        first = await self._open(root)
        await _fill(first, "activity", 5)
        await first.truncate_below("activity", 6)
        self.assertEqual(await first.head("activity"), 5)
        await first.stop()

        (root / "index.json").unlink()  # the module's own reader treats this as disposable
        second = await self._open(root)
        self.assertEqual(await second.head("activity"), 5, "head regressed when the index was lost")
        self.assertEqual(await second.append(_event("activity", 99), expected_seq=None), 6)

    async def test_a_corrupt_index_does_not_reissue_a_compacted_seq(self) -> None:
        root = self._root()
        first = await self._open(root)
        await _fill(first, "activity", 5)
        await first.truncate_below("activity", 6)
        await first.stop()

        (root / "index.json").write_text("{not json", encoding="utf-8")
        second = await self._open(root)
        self.assertEqual(await second.head("activity"), 5)
        self.assertEqual(await second.append(_event("activity", 99), expected_seq=None), 6)

    async def test_a_second_process_does_not_reissue_after_the_first_compacts(self) -> None:
        root = self._root()
        writer = await self._open(root)
        reader = await self._open(root)
        await _fill(writer, "activity", 5)
        self.assertEqual(await reader.head("activity"), 5)
        await writer.truncate_below("activity", 6)
        self.assertEqual(await reader.head("activity"), 5)
        self.assertEqual(await reader.append(_event("activity", 99), expected_seq=None), 6,
                         "the other process reissued a seq the first had already handed out")

    async def test_deleting_the_stream_still_starts_it_over(self) -> None:
        root = self._root()
        backend = await self._open(root)
        await _fill(backend, "gone", 3)
        await backend.delete_stream("gone")
        self.assertEqual(await backend.head("gone"), 0)
        self.assertEqual(await backend.append(_event("gone", 1), expected_seq=None), 1)

    async def test_the_mark_survives_a_restart_and_is_not_read_as_a_stream(self) -> None:
        root = self._root()
        first = await self._open(root)
        await _fill(first, "activity", 5)
        await first.truncate_below("activity", 6)
        await first.stop()
        second = await self._open(root)
        self.assertEqual(await second.streams(""), [])  # an emptied stream is still empty
        self.assertEqual(await second.read("activity", from_seq=0, limit=None), [])


class MemoryHeadTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_truncating_to_seq_one_is_a_no_op(self) -> None:
        from simorgh.ledger.backends.memory import InMemoryBackend

        backend = InMemoryBackend()
        await _fill(backend, "activity", 5)
        self.assertEqual(await backend.truncate_below("activity", 1), 0)
        self.assertEqual(await backend.head("activity"), 5)

    async def test_a_mark_left_behind_by_truncation_survives(self) -> None:
        from simorgh.ledger.backends.memory import InMemoryBackend

        backend = InMemoryBackend()
        await _fill(backend, "activity", 5)
        await backend.truncate_below("activity", 6)
        backend._heads.clear()  # noqa: SLF001 -- as if the mark had never been appended
        self.assertEqual(await backend.head("activity"), 0)  # nothing left to derive from


class BackendsAgreeTestCase(unittest.IsolatedAsyncioTestCase):
    """The four backends must answer the same head for the same history."""

    async def test_all_four_agree_after_a_compaction_that_empties_the_stream(self) -> None:
        from simorgh.ledger.backends.dynamodb import DynamoBackend
        from simorgh.ledger.backends.jsonl import JsonlBackend
        from simorgh.ledger.backends.memory import InMemoryBackend
        from simorgh.ledger.backends.sqlite import SqliteBackend

        from .test_backends import _FakeBlobBucket, _FakeDynamoTable

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        made = {
            "memory": InMemoryBackend(),
            "sqlite": SqliteBackend(root / "l.db"),
            "jsonl": JsonlBackend(root / "jsonl", fsync=False),
            "dynamodb": DynamoBackend("t", "b", table=_FakeDynamoTable(), bucket=_FakeBlobBucket()),
        }
        heads, seqs = {}, {}
        for name, backend in made.items():
            await backend.start()
            self.addAsyncCleanup(backend.stop)
            await _fill(backend, "activity", 5)
            await backend.truncate_below("activity", 6)
            heads[name] = await backend.head("activity")
            seqs[name] = await backend.append(_event("activity", 99), expected_seq=None)
        self.assertEqual(heads, dict.fromkeys(made, 5))
        self.assertEqual(seqs, dict.fromkeys(made, 6))


if __name__ == "__main__":
    unittest.main()
