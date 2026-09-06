"""jsonl-specific durability behavior (02-ledger sections 5.1, 8, and
scenario S3): a crash mid-write leaves at most the record that was
being written unrecoverable, never a corrupted stream, and restart
truncates the trailing partial line rather than failing to start.
"""

import tempfile
import unittest
from pathlib import Path

from .helpers import make_event
from simorgh.ledger.streams import escape


class TestJsonlCrashSafety(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_truncated_trailing_line_is_recovered_not_fatal(self) -> None:
        from simorgh.ledger.backends.jsonl import JsonlBackend

        backend = JsonlBackend(self.root)
        await backend.start()
        await backend.append(make_event("task:z", payload={"a": 1}), expected_seq=None)
        await backend.append(make_event("task:z", payload={"a": 2}), expected_seq=1)
        await backend.stop()

        path = self.root / "streams" / f"{escape('task:z')}.jsonl"
        with open(path, "ab") as fh:  # simulate a crash mid-write: no closing brace, no newline
            fh.write(b'{"stream":"task:z","seq":3,"type":"test.event","ts":0.0')

        backend2 = JsonlBackend(self.root)
        await backend2.start()  # must not raise

        self.assertIn("task:z", backend2.recovered)
        events = await backend2.read("task:z", from_seq=0, limit=None)
        self.assertEqual([e.seq for e in events], [1, 2])
        self.assertEqual(await backend2.head("task:z"), 2)
        await backend2.stop()

    async def test_a_clean_stream_reports_no_recovery(self) -> None:
        from simorgh.ledger.backends.jsonl import JsonlBackend

        backend = JsonlBackend(self.root)
        await backend.start()
        await backend.append(make_event("task:ok"), expected_seq=None)
        await backend.stop()

        backend2 = JsonlBackend(self.root)
        await backend2.start()
        self.assertEqual(backend2.recovered, [])
        await backend2.stop()

    async def test_atomic_rewrite_never_leaves_a_dangling_tmp_file(self) -> None:
        from simorgh.ledger.backends.jsonl import JsonlBackend

        backend = JsonlBackend(self.root)
        await backend.start()
        for i in range(3):
            await backend.append(make_event("task:r", payload={"i": i}), expected_seq=i)
        await backend.truncate_below("task:r", 2)
        leftovers = list(self.root.rglob("*.tmp"))
        self.assertEqual(leftovers, [])
        events = await backend.read("task:r", from_seq=0, limit=None)
        self.assertEqual([e.seq for e in events], [2, 3])
        await backend.stop()

    async def test_head_never_regresses_after_truncation(self) -> None:
        from simorgh.ledger.backends.jsonl import JsonlBackend

        backend = JsonlBackend(self.root)
        await backend.start()
        for i in range(5):
            await backend.append(make_event("task:s"), expected_seq=i)
        await backend.truncate_below("task:s", 4)
        self.assertEqual(await backend.head("task:s"), 5)  # a new append still continues from 6, not from 1
        seq = await backend.append(make_event("task:s"), expected_seq=None)
        self.assertEqual(seq, 6)
        await backend.stop()

    async def test_unwritable_directory_raises_ledger_unavailable_on_start(self) -> None:
        import os

        from simorgh.ledger.api import LedgerUnavailable
        from simorgh.ledger.backends.jsonl import JsonlBackend

        blocked = self.root / "blocked_file_not_a_dir"
        blocked.write_text("x")  # a file where the backend wants a directory
        backend = JsonlBackend(blocked / "nested")
        with self.assertRaises(LedgerUnavailable):
            await backend.start()


if __name__ == "__main__":
    unittest.main()
