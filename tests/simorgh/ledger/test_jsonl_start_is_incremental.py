"""Starting the JSONL backend must not re-read streams that have not
changed.

Live-caught, 2026-09-07: `sim.sh` took 38 seconds to boot on the
creator's real ledger. `start()` called `_scan_stream` on every file --
open, read whole, JSON-parse every line -- for all 192,456 of them, of
which 190,865 are one-file-per-message `trace:<id>` streams. 40 of 43
profiled seconds were in that loop.

`index.json` already recorded `{head, bytes, last_ts}` per stream and was
written on every start and stop and read by nobody; the `.idx` files the
module docstring calls "a cache; rebuilt if stale" were likewise
write-only. These tests pin the behaviour that fixed it, and the crash
recovery that must survive it.
"""

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.envelope import Event
from simorgh.ledger.backends.jsonl import JsonlBackend


def _event(stream: str, seq: int = 0, *, key: str | None = None) -> Event:
    return Event(
        stream=stream, type="test.event", ts=1000.0 + seq, trace_id="t", causation_id=None,
        payload={"n": seq}, idempotency_key=key,
    )


class StartIsIncrementalTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def _seed(self, streams: int = 5, *, key_prefix: str | None = None) -> JsonlBackend:
        backend = JsonlBackend(self.root, fsync=False)
        await backend.start()
        for i in range(streams):
            key = f"{key_prefix}-{i}" if key_prefix else None
            await backend.append(_event(f"s{i}", i, key=key), expected_seq=None)
        await backend.stop()
        return backend

    async def test_an_unchanged_ledger_rescans_nothing_on_the_next_start(self):
        await self._seed(5)
        backend = JsonlBackend(self.root, fsync=False)
        await backend.start()
        self.assertEqual(backend.scanned_on_start, 0)
        self.assertEqual(backend.trusted_on_start, 5)

    async def test_the_trusted_metadata_matches_what_a_full_scan_would_have_found(self):
        await self._seed(3)
        fast = JsonlBackend(self.root, fsync=False)
        await fast.start()
        heads_fast = {s: (m.head, m.bytes, m.last_ts) for s, m in fast._meta.items()}  # noqa: SLF001

        (self.root / "index.json").unlink()  # forces the old full-scan path
        slow = JsonlBackend(self.root, fsync=False)
        await slow.start()
        self.assertEqual(slow.scanned_on_start, 3)
        heads_slow = {s: (m.head, m.bytes, m.last_ts) for s, m in slow._meta.items()}  # noqa: SLF001
        self.assertEqual(heads_fast, heads_slow)

    async def test_a_stream_that_grew_since_the_index_is_rescanned(self):
        await self._seed(3)
        with open(self.root / "streams" / "s1.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_event("s1", 99).to_dict() | {"seq": 2}) + "\n")

        backend = JsonlBackend(self.root, fsync=False)
        await backend.start()
        self.assertEqual(backend.scanned_on_start, 1)
        self.assertEqual(backend._meta["s1"].head, 2)  # noqa: SLF001

    async def test_a_stream_missing_from_the_index_is_scanned(self):
        await self._seed(2)
        index = json.loads((self.root / "index.json").read_text())
        del index["s1"]
        (self.root / "index.json").write_text(json.dumps(index))

        backend = JsonlBackend(self.root, fsync=False)
        await backend.start()
        self.assertEqual(backend.scanned_on_start, 1)
        self.assertEqual(backend._meta["s1"].head, 1)  # noqa: SLF001

    async def test_a_corrupt_index_costs_a_full_scan_and_is_never_wrong(self):
        await self._seed(3)
        (self.root / "index.json").write_text("{not json")
        backend = JsonlBackend(self.root, fsync=False)
        await backend.start()
        self.assertEqual(backend.scanned_on_start, 3)

    async def test_a_crash_mid_write_is_still_truncated_and_recovered(self):
        """Appends only grow a file, so a process that died mid-write
        leaves a size the index does not have -- which is exactly what
        puts the stream back on the scan path."""
        await self._seed(2)
        with open(self.root / "streams" / "s0.jsonl", "a", encoding="utf-8") as fh:
            fh.write('{"stream": "s0", "seq": 2, "partial')  # no newline: a torn write

        backend = JsonlBackend(self.root, fsync=False)
        await backend.start()
        self.assertIn("s0", backend.recovered)
        self.assertEqual(backend._meta["s0"].head, 1)  # noqa: SLF001
        events = await backend.read("s0", from_seq=0, limit=None)
        self.assertEqual(len(events), 1)


class IdempotencySurvivesTheFastPathTestCase(unittest.IsolatedAsyncioTestCase):
    """A trusted stream is never read at start, so its keys are not in
    memory. They have to be loaded from the `.idx` cache on first use, or
    the fast path would silently break append deduplication."""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_a_key_written_before_restart_is_still_found_after_it(self):
        first = JsonlBackend(self.root, fsync=False)
        await first.start()
        seq = await first.append(_event("s0", 0, key="k-1"), expected_seq=None)
        await first.stop()

        second = JsonlBackend(self.root, fsync=False)
        await second.start()
        self.assertEqual(second.scanned_on_start, 0)  # the fast path really was taken
        self.assertEqual(await second.find_by_idempotency("s0", "k-1"), seq)

    async def test_an_unknown_key_on_a_trusted_stream_is_still_none(self):
        first = JsonlBackend(self.root, fsync=False)
        await first.start()
        await first.append(_event("s0", 0, key="k-1"), expected_seq=None)
        await first.stop()

        second = JsonlBackend(self.root, fsync=False)
        await second.start()
        self.assertIsNone(await second.find_by_idempotency("s0", "never-used"))

    async def test_appending_a_new_key_after_a_trusted_start_keeps_the_old_ones(self):
        first = JsonlBackend(self.root, fsync=False)
        await first.start()
        old = await first.append(_event("s0", 0, key="k-1"), expected_seq=None)
        await first.stop()

        second = JsonlBackend(self.root, fsync=False)
        await second.start()
        await second.append(_event("s0", 1, key="k-2"), expected_seq=None)
        self.assertEqual(await second.find_by_idempotency("s0", "k-1"), old)
        self.assertIsNotNone(await second.find_by_idempotency("s0", "k-2"))


if __name__ == "__main__":
    unittest.main()
