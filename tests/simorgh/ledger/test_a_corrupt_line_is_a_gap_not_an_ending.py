"""One unreadable record must not delete, hide, or renumber the rest.

The jsonl backend had three places that treated the first line it could
not parse as the end of the stream. None of them said so:

* `read()` returned everything before the bad line and stopped. No
  exception, no log, no counter -- while `head()` still answered the
  real head. A projection rebuilt from it (`TaskStore.rebuild`, Memory's
  recall index, every `materialize`) silently rebuilt a shorter history
  than the ledger holds.
* `_scan_stream()` truncated the FILE at that line on the next boot, so
  every record after one flipped byte was deleted from disk. That rule
  exists for a genuine crash artifact -- a trailing line with no
  newline, whose seq was never handed to anybody -- and it was being
  applied to durable, already-acked data in the middle of the file.
* `truncate_below()` (retention) rewrites the stream from what `read()`
  returned, so the first compaction pass after a corruption made the
  loss permanent, as housekeeping, with nothing to see afterwards.

Measured 2026-09-10: five events appended, one byte flipped in record 3.
`head()` said 5, `read()` returned `[1, 2]`, `backend.recovered` was
empty, and the next boot's scan cut records 4 and 5 off the file.

And separately: a stream whose tail is lost some other way (a partial
fsync, a truncated copy, an editor) reissued a sequence number that had
already been fsync'd and returned to a caller -- head fell from 5 to 4
and the next append handed out 5 a second time. The durable high-water
mark existed but only compaction ever wrote it.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.envelope import Event
from simorgh.ledger.backends.jsonl import JsonlBackend


def _event(n: int) -> Event:
    return Event(stream="task:t1", type="step", ts=float(n), trace_id="t1", causation_id=None,
                 payload={"n": n})


class ACorruptLineTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "streams" / "task%3At1.jsonl"
        backend = await self._open()
        for n in range(1, 6):
            await backend.append(_event(n), expected_seq=None)
        self.assertEqual(await backend.head("task:t1"), 5)
        await backend.stop()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def _open(self) -> JsonlBackend:
        backend = JsonlBackend(self.root, fsync=False)
        await backend.start()
        self.addAsyncCleanup(backend.stop)
        return backend

    def _lines(self) -> list[bytes]:
        return [line for line in self.path.read_bytes().split(b"\n") if line]

    def _corrupt(self, index: int) -> None:
        """Break one line's JSON without changing the file's length --
        which is also what makes it invisible to the size check
        `start()` uses to decide whether to rescan."""
        lines = self._lines()
        broken = bytearray(lines[index])
        broken[0:1] = b"x"
        lines[index] = bytes(broken)
        self.path.write_bytes(b"\n".join(lines) + b"\n")

    def _seqs_on_disk(self) -> list[int | str]:
        return [json.loads(line)["seq"] if line[:1] == b"{" else "corrupt" for line in self._lines()]

    async def test_reading_skips_the_bad_line_and_returns_the_rest(self):
        self._corrupt(2)
        backend = await self._open()
        self.assertEqual([e.seq for e in await backend.read("task:t1", from_seq=0, limit=None)],
                         [1, 2, 4, 5])

    async def test_the_bad_line_is_counted_where_a_caller_can_see_it(self):
        self._corrupt(2)
        backend = await self._open()
        await backend.read("task:t1", from_seq=0, limit=None)
        self.assertEqual(backend.corrupt.get("task:t1"), 1)

    async def test_head_and_read_still_agree_about_the_end_of_the_stream(self):
        self._corrupt(2)
        backend = await self._open()
        events = await backend.read("task:t1", from_seq=0, limit=None)
        self.assertEqual(await backend.head("task:t1"), events[-1].seq)

    async def test_the_next_boot_does_not_delete_what_follows_it(self):
        self._corrupt(2)
        # A scan is what the next boot does when the size does not match
        # the index; force it by removing the index entirely.
        (self.root / "index.json").unlink()
        backend = await self._open()
        self.assertEqual(self._seqs_on_disk(), [1, 2, "corrupt", 4, 5])
        self.assertEqual(await backend.head("task:t1"), 5)
        self.assertEqual(await backend.append(_event(99), expected_seq=None), 6)

    async def test_compaction_refuses_to_rewrite_a_stream_it_cannot_fully_read(self):
        self._corrupt(2)
        backend = await self._open()
        self.assertEqual(await backend.truncate_below("task:t1", 4), 0)
        self.assertEqual(self._seqs_on_disk(), [1, 2, "corrupt", 4, 5])

    async def test_a_clean_stream_still_compacts(self):
        backend = await self._open()
        self.assertEqual(await backend.truncate_below("task:t1", 4), 3)
        self.assertEqual(self._seqs_on_disk(), [4, 5])
        self.assertFalse(backend.corrupt)


class ALostTailTestCase(unittest.IsolatedAsyncioTestCase):
    """A trailing partial line is a crash mid-append: its seq was never
    returned to anybody, so removing it and reusing the number is right.
    A tail that goes missing any OTHER way took acked records with it --
    and the head must not follow it down."""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "streams" / "task%3At1.jsonl"
        backend = await self._open()
        for n in range(1, 6):
            await backend.append(_event(n), expected_seq=None)
        await backend.stop()  # a clean stop: index.json records head 5

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def _open(self) -> JsonlBackend:
        backend = JsonlBackend(self.root, fsync=False)
        await backend.start()
        self.addAsyncCleanup(backend.stop)
        return backend

    async def test_a_truncated_tail_does_not_reissue_an_acked_seq(self):
        raw = self.path.read_bytes()
        self.path.write_bytes(raw[: len(raw) - 20])  # chopped mid-record
        backend = await self._open()
        self.assertEqual(await backend.head("task:t1"), 5, "head regressed below what was acked")
        self.assertEqual(await backend.append(_event(99), expected_seq=None), 6,
                         "seq 5 was handed out twice")

    async def test_the_floor_survives_losing_index_json_too(self):
        raw = self.path.read_bytes()
        self.path.write_bytes(raw[: len(raw) - 20])
        first = await self._open()  # writes the durable mark
        await first.stop()
        (self.root / "index.json").unlink()  # the module treats this as disposable
        second = await self._open()
        self.assertEqual(await second.head("task:t1"), 5)
        self.assertEqual(await second.append(_event(99), expected_seq=None), 6)

    async def test_an_untouched_stream_writes_no_mark(self):
        """The mark is written only when the file can no longer prove
        the head -- one small file per stream on every boot would be
        192,000 of them on the creator's own ledger."""
        await self._open()
        self.assertEqual(list((self.root / "heads").glob("*.head")), [])


class TheLockTableIsBoundedTestCase(unittest.IsolatedAsyncioTestCase):
    """`_locks` kept one `asyncio.Lock` per stream ever appended to, for
    the life of the process. Measured 2026-09-10: 20,000 one-event
    `trace:` streams left 20,000 locks behind -- ~34 MB extrapolated to
    the creator's own 192,456-stream ledger, all of it mutexes for
    streams written once and never touched again."""

    async def test_writing_many_streams_does_not_grow_the_lock_table(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        backend = JsonlBackend(Path(tmp.name), fsync=False)
        await backend.start()
        self.addAsyncCleanup(backend.stop)
        for i in range(JsonlBackend._MAX_LOCKS + 500):  # noqa: SLF001
            event = Event(stream=f"trace:{i:08d}", type="msg", ts=1.0, trace_id=str(i),
                          causation_id=None, payload={"i": i})
            await backend.append(event, expected_seq=None)
        self.assertLessEqual(len(backend._locks), JsonlBackend._MAX_LOCKS)  # noqa: SLF001
        self.assertEqual(len(backend._meta), JsonlBackend._MAX_LOCKS + 500)  # noqa: SLF001

    async def test_a_lock_in_use_is_never_evicted(self):
        """Eviction handing two writers of one stream two different
        locks would be worse than the leak it fixes."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        backend = JsonlBackend(Path(tmp.name), fsync=False)
        await backend.start()
        self.addAsyncCleanup(backend.stop)
        held = backend._lock_for("task:busy")  # noqa: SLF001
        await held.acquire()
        try:
            for i in range(JsonlBackend._MAX_LOCKS + 200):  # noqa: SLF001
                backend._lock_for(f"trace:{i:08d}")  # noqa: SLF001
            self.assertIs(backend._lock_for("task:busy"), held)  # noqa: SLF001
        finally:
            held.release()


if __name__ == "__main__":
    unittest.main()
