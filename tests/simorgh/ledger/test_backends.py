"""Backend-parity invariants (02-ledger section 9): the same behavior is
required of `memory`, `jsonl`, `sqlite`, and (via in-memory fakes of its
two adapter protocols, no credentials/network) `dynamodb`. `_Invariants`
is a mixin, not a `TestCase` itself, so it is never collected on its own
-- only its concrete subclasses below run.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path

from .helpers import Counter, make_event
from simorgh.ledger.api import BlobNotFound, ConflictError, ValidationError
from simorgh.ledger.client import LedgerClient


class _Invariants:
    """Mixed in with `unittest.IsolatedAsyncioTestCase` by each concrete
    backend below. `self.client` is started; `self.backend` is the raw
    engine, for the few assertions that need it directly."""

    async def make_backend(self):  # pragma: no cover - overridden per backend
        raise NotImplementedError

    async def asyncSetUp(self) -> None:
        from tests.simorgh.helpers import FakeClock

        self.clock = FakeClock()
        self.backend = await self.make_backend()
        self.client = LedgerClient(self.backend, clock=self.clock, inline_threshold=64)

    async def asyncTearDown(self) -> None:
        await self.client.stop()

    # ------------------------------------------------------------- append/read
    async def test_append_returns_monotonic_seq(self) -> None:
        await self.client.start()
        s1 = await self.client.append("task:a", make_event("task:a"))
        s2 = await self.client.append("task:a", make_event("task:a"))
        self.assertEqual((s1, s2), (1, 2))

    async def test_cas_rejects_a_stale_expected_seq(self) -> None:
        await self.client.start()
        await self.client.append("task:a", make_event("task:a"), expected_seq=0)
        with self.assertRaises(ConflictError):
            await self.client.append("task:a", make_event("task:a"), expected_seq=0)

    async def test_cas_accepts_the_true_head(self) -> None:
        await self.client.start()
        await self.client.append("task:a", make_event("task:a"), expected_seq=0)
        seq = await self.client.append("task:a", make_event("task:a"), expected_seq=1)
        self.assertEqual(seq, 2)

    async def test_read_from_seq_and_limit(self) -> None:
        await self.client.start()
        for i in range(5):
            await self.client.append("task:b", make_event("task:b", payload={"i": i}))
        events = await self.client.read("task:b", from_seq=3, limit=2)
        self.assertEqual([e.seq for e in events], [3, 4])

    async def test_streams_by_prefix_excludes_unrelated_and_empty(self) -> None:
        await self.client.start()
        await self.client.append("task:x", make_event("task:x"))
        await self.client.append("task:y", make_event("task:y"))
        await self.client.append("other:z", make_event("other:z"))
        self.assertEqual(await self.client.streams("task:"), ["task:x", "task:y"])

    async def test_delete_stream_removes_it(self) -> None:
        await self.client.start()
        await self.client.append("task:d", make_event("task:d"))
        await self.client.delete_stream("task:d")
        self.assertEqual(await self.client.head("task:d"), 0)
        self.assertEqual(await self.client.read("task:d", from_seq=0), [])

    # ------------------------------------------------------------- idempotency
    async def test_idempotency_key_dedupe(self) -> None:
        await self.client.start()
        s1 = await self.client.append("task:c", make_event("task:c", idempotency_key="k1"))
        s2 = await self.client.append(
            "task:c", make_event("task:c", idempotency_key="k1", payload={"different": True})
        )
        self.assertEqual(s1, s2)
        self.assertEqual(len(await self.client.read("task:c", from_seq=0)), 1)
        self.assertEqual(self.client.counters["dedupes"], 1)

    # ------------------------------------------------------------------ blobs
    async def test_blob_round_trip_and_ref_stability(self) -> None:
        await self.client.start()
        ref1 = await self.client.put_blob(b"hello world", content_type="text/plain")
        ref2 = await self.client.put_blob(b"hello world", content_type="text/plain")
        self.assertEqual(ref1, ref2)
        self.assertEqual(await self.client.get_blob(ref1), b"hello world")

    async def test_missing_blob_raises(self) -> None:
        await self.client.start()
        from simorgh.ledger.blobs import ref_for

        with self.assertRaises(BlobNotFound):
            await self.client.get_blob(ref_for(b"never written"))

    async def test_oversized_inline_payload_is_rejected_before_any_write(self) -> None:
        await self.client.start()
        big = "x" * (self.client.inline_threshold + 1)
        with self.assertRaises(ValidationError):
            await self.client.append("task:e", make_event("task:e", payload={"content": big}))
        self.assertEqual(await self.client.head("task:e"), 0)

    async def test_blob_ref_payload_is_allowed_even_when_long(self) -> None:
        await self.client.start()
        ref = await self.client.put_blob(b"y" * 10_000, content_type="text/plain")
        seq = await self.client.append("task:f", make_event("task:f", payload={"content_ref": ref}))
        self.assertEqual(seq, 1)

    # -------------------------------------------------------------- snapshots
    async def test_rebuild_replays_a_snapshot_plus_the_tail(self) -> None:
        await self.client.start()
        for _ in range(3):
            await self.client.append("task:g", make_event("task:g", type_="inc"))
        proj = Counter()
        head = await self.client.rebuild(proj, "task:g")
        self.assertEqual((head, proj.count), (3, 3))
        await self.client.snapshot("task:g", proj.state(), proj.applied_seq)
        for _ in range(2):
            await self.client.append("task:g", make_event("task:g", type_="inc"))
        proj2 = Counter()
        head2 = await self.client.rebuild(proj2, "task:g")
        self.assertEqual((head2, proj2.count), (5, 5))

    async def test_materialize_snapshots_once_the_view_has_moved_far_enough(self) -> None:
        await self.client.start()
        proj = Counter()
        proj.snapshot_every = 2
        for _ in range(3):
            await self.client.append("task:h", make_event("task:h", type_="inc"))
            await self.client.materialize(proj, "task:h")
        snap = await self.client.load_snapshot("task:h")
        self.assertIsNotNone(snap)
        self.assertGreaterEqual(snap[1], 2)

    async def test_a_corrupt_snapshot_falls_back_to_a_full_replay(self) -> None:
        await self.client.start()
        for _ in range(3):
            await self.client.append("task:i", make_event("task:i", type_="inc"))
        await self.client.snapshot("task:i", {}, 2)  # missing "count" -> Counter.load raises
        proj = Counter()
        head = await self.client.rebuild(proj, "task:i")
        self.assertEqual((head, proj.count), (3, 3))  # recovered by full replay, not stuck on the bad snapshot

    # ------------------------------------------------------------------- tail
    async def test_tail_delivers_new_events_on_an_exact_stream_in_order(self) -> None:
        await self.client.start()
        received: list[int] = []

        async def handler(event):
            received.append(event.seq)

        sub = await self.client.tail("task:j", handler)
        await self.client.append("task:j", make_event("task:j"))
        await self.client.append("task:j", make_event("task:j"))
        await asyncio.sleep(0)
        await sub.unsubscribe()
        self.assertEqual(received, [1, 2])

    async def test_tail_on_a_prefix_delivers_from_every_matching_stream(self) -> None:
        await self.client.start()
        received: list[str] = []

        async def handler(event):
            received.append(event.stream)

        sub = await self.client.tail("task:", handler)
        await self.client.append("task:k1", make_event("task:k1"))
        await self.client.append("task:k2", make_event("task:k2"))
        await self.client.append("other:k3", make_event("other:k3"))
        await asyncio.sleep(0)
        await sub.unsubscribe()
        self.assertEqual(sorted(received), ["task:k1", "task:k2"])

    async def test_unsubscribed_tail_receives_nothing_further(self) -> None:
        await self.client.start()
        received: list[int] = []

        async def handler(event):
            received.append(event.seq)

        sub = await self.client.tail("task:l", handler)
        await self.client.append("task:l", make_event("task:l"))
        await sub.unsubscribe()
        await self.client.append("task:l", make_event("task:l"))
        await asyncio.sleep(0)
        self.assertEqual(received, [1])

    # ------------------------------------------------------------- compaction
    async def test_compact_preserves_rebuildability_via_the_snapshot(self) -> None:
        await self.client.start()
        for _ in range(5):
            await self.client.append("task:m", make_event("task:m", type_="inc"))
        proj = Counter()
        await self.client.rebuild(proj, "task:m")
        await self.client.snapshot("task:m", proj.state(), proj.applied_seq)
        removed = await self.client.compact("task:m", before_seq=proj.applied_seq)
        self.assertGreater(removed, 0)
        proj2 = Counter()
        head = await self.client.rebuild(proj2, "task:m")
        self.assertEqual((head, proj2.count), (5, 5))


class TestMemoryBackend(_Invariants, unittest.IsolatedAsyncioTestCase):
    async def make_backend(self):
        from simorgh.ledger.backends.memory import InMemoryBackend

        return InMemoryBackend()


class TestJsonlBackend(_Invariants, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        await super().asyncSetUp()

    async def asyncTearDown(self) -> None:
        await super().asyncTearDown()
        self._tmp.cleanup()

    async def make_backend(self):
        from simorgh.ledger.backends.jsonl import JsonlBackend

        return JsonlBackend(Path(self._tmp.name))


class TestJsonlBackendBlobSweep(unittest.IsolatedAsyncioTestCase):
    """Live-caught by observer audit `w8b-20260908-210626-62a022`:
    `run_compaction` deletes/truncates *streams* per retention but never
    touched the blob store, so a `trace:` stream's oversized payload
    outlived the stream that referenced it -- forever, unbounded, in
    every real run (content addressing means several streams may share
    one blob, so a naive "delete on stream delete" would break that
    sharing). `sweep_unreferenced_blobs` fixes that; these are the
    regression tests."""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        from simorgh.ledger.backends.jsonl import JsonlBackend

        self.backend = JsonlBackend(Path(self._tmp.name))
        await self.backend.start()

    async def asyncTearDown(self) -> None:
        await self.backend.stop()
        self._tmp.cleanup()

    async def _put_blob(self, data: bytes) -> str:
        return await self.backend.put_blob(data, content_type="text/plain")

    def _blob_path(self, ref: str) -> Path:
        digest = ref.split(":")[-1]
        return Path(self._tmp.name) / "blobs" / digest[:2] / digest

    async def test_orphaned_blob_is_removed_once_its_stream_is_gone(self) -> None:
        ref = await self._put_blob(b"x" * 10_000)
        blob_path = self._blob_path(ref)
        self.assertTrue(blob_path.exists())

        # Age the blob past the grace window without any stream ever
        # referencing it -- the "stream that pointed to it already expired" case.
        old = time.time() - 7200
        os.utime(blob_path, (old, old))

        removed = await self.backend.sweep_unreferenced_blobs(grace_seconds=3600.0)
        self.assertEqual(removed, 1)
        self.assertFalse(blob_path.exists())

    async def test_blob_still_referenced_by_a_live_stream_survives(self) -> None:
        ref = await self._put_blob(b"y" * 10_000)
        blob_path = self._blob_path(ref)
        old = time.time() - 7200
        os.utime(blob_path, (old, old))

        await self.backend.append(make_event("task:keep", type_="tool.result", payload={"output_ref": ref}), expected_seq=None)

        removed = await self.backend.sweep_unreferenced_blobs(grace_seconds=3600.0)
        self.assertEqual(removed, 0)
        self.assertTrue(blob_path.exists())

    async def test_recently_written_blob_is_not_swept_before_its_grace_period(self) -> None:
        """The race this exists for: a producer calls `put_blob` before
        appending the event that will reference it, so a blob can briefly
        exist with nothing pointing at it yet -- that must not make it
        eligible for deletion."""
        ref = await self._put_blob(b"z" * 10_000)
        blob_path = self._blob_path(ref)

        removed = await self.backend.sweep_unreferenced_blobs(grace_seconds=3600.0)
        self.assertEqual(removed, 0)
        self.assertTrue(blob_path.exists())

    async def test_compaction_via_the_service_sweeps_orphaned_blobs(self) -> None:
        """The end-to-end path: `Service._compact` calls the sweep after
        every retention pass, for any backend that implements it."""
        from simorgh.ledger.service import Service

        client = LedgerClient(self.backend)
        await client.start()
        ref = await client.put_blob(b"w" * 10_000, content_type="text/plain")
        blob_path = self._blob_path(ref)
        old = time.time() - 7200
        os.utime(blob_path, (old, old))

        service = Service(client)
        await service._compact("test")  # noqa: SLF001
        self.assertFalse(blob_path.exists())
        self.assertEqual(service.last_report.get("blobs_swept"), 1)
        await client.stop()


class TestSqliteBackend(_Invariants, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        await super().asyncSetUp()

    async def asyncTearDown(self) -> None:
        await super().asyncTearDown()
        self._tmp.cleanup()

    async def make_backend(self):
        from simorgh.ledger.backends.sqlite import SqliteBackend

        return SqliteBackend(Path(self._tmp.name) / "ledger.sqlite3")

    async def test_concurrent_cas_appends_exactly_one_winner_per_seq(self) -> None:
        await self.client.start()
        results = await asyncio.gather(
            *[self.client.append("task:race", make_event("task:race"), expected_seq=0) for _ in range(8)],
            return_exceptions=True,
        )
        ok = [r for r in results if isinstance(r, int)]
        errors = [r for r in results if isinstance(r, ConflictError)]
        self.assertEqual(len(ok), 1)
        self.assertEqual(len(errors), 7)
        self.assertEqual(await self.client.head("task:race"), 1)


class _FakeDynamoTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, int], dict] = {}

    def put_if_absent(self, item: dict) -> bool:
        key = (item["stream"], item["seq"])
        if key in self.items:
            return False
        self.items[key] = item
        return True

    def put(self, item: dict) -> None:
        self.items[(item["stream"], item["seq"])] = item

    def get(self, stream: str, seq: int):
        return self.items.get((stream, seq))

    def latest(self, stream: str):
        candidates = [v for (s, sq), v in self.items.items() if s == stream and sq >= 1]
        return max(candidates, key=lambda v: v["seq"]) if candidates else None

    def range(self, stream: str, from_seq: int, limit):
        items = sorted(
            (v for (s, sq), v in self.items.items() if s == stream and sq >= from_seq),
            key=lambda v: v["seq"],
        )
        return items[:limit] if limit is not None else items

    def find_idem(self, stream: str, key: str):
        for (s, _sq), v in self.items.items():
            if s == stream and v.get("idempotency_key") == key:
                return v["seq"]
        return None

    def delete(self, stream: str, seq: int) -> None:
        self.items.pop((stream, seq), None)

    def list_streams(self, prefix: str):
        return sorted({s for (s, sq) in self.items if sq >= 1 and s.startswith(prefix)})


class _FakeBlobBucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        self.objects[key] = data

    def get(self, key: str):
        return self.objects.get(key)

    def stat(self) -> dict:
        return {"blobs": len(self.objects), "blob_bytes": sum(len(v) for v in self.objects.values())}


class TestDynamoDbBackend(_Invariants, unittest.IsolatedAsyncioTestCase):
    """Exercised entirely through in-memory fakes of `DynamoTable`/
    `BlobBucket` -- no `boto3`, no credentials, no network (02-ledger
    section 9: the aws suite only runs live under `SIMORGH_TEST_AWS=1`,
    which this is not)."""

    async def make_backend(self):
        from simorgh.ledger.backends.dynamodb import DynamoBackend

        return DynamoBackend("t", "b", table=_FakeDynamoTable(), bucket=_FakeBlobBucket())


if __name__ == "__main__":
    unittest.main()


class HeadNeverRegressesTestCase(unittest.IsolatedAsyncioTestCase):
    """Compaction must never hand a sequence number back.

    Head was derived from the live events, so once a retention pass
    removed them all it fell back to 0 and the next append was handed
    seq 1 again. Every reader already past that point -- a projection's
    `applied_seq`, a tail cursor -- then dropped the new events as ones
    it had already folded. Live-caught by an observer 2026-09-10: five
    expired events, one compaction pass, head 5 -> 0, next append seq 1,
    and the live projection's count frozen while events kept arriving.

    The `jsonl` backend already kept this rule; the other three did not.
    """

    async def _each_backend(self):
        import tempfile
        from pathlib import Path

        from simorgh.ledger.backends.memory import InMemoryBackend
        from simorgh.ledger.backends.sqlite import SqliteBackend

        yield "memory", InMemoryBackend(), None
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        sqlite = SqliteBackend(Path(tmp.name) / "l.db")
        await sqlite.start()
        yield "sqlite", sqlite, sqlite

    def _event(self, stream: str, n: int):
        from simorgh.contracts.envelope import Event

        return Event(stream=stream, type="x", ts=float(n), trace_id="", causation_id=None,
                     payload={"n": n})

    async def test_a_compacted_stream_does_not_reissue_seqs(self):
        async for name, backend, closable in self._each_backend():
            for n in range(5):
                await backend.append(self._event("activity", n), expected_seq=None)
            await backend.truncate_below("activity", 6)
            self.assertEqual(await backend.head("activity"), 5, name)
            seq = await backend.append(self._event("activity", 99), expected_seq=None)
            self.assertEqual(seq, 6, f"{name}: a reader past seq 5 would drop this")
            if closable is not None:
                await closable.stop()

    async def test_deleting_the_stream_really_does_start_it_over(self):
        """Compaction is not deletion. Deletion is."""
        async for name, backend, closable in self._each_backend():
            await backend.append(self._event("gone", 1), expected_seq=None)
            await backend.delete_stream("gone")
            self.assertEqual(await backend.head("gone"), 0, name)
            if closable is not None:
                await closable.stop()
