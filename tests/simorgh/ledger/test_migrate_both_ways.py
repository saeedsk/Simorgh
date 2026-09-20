"""Stage 9 item 5: a ledger moves between JSONL and SQLite without losing
a seq, a head, a key or a blob.

The property that matters is the one `append` would break: seqs are
preserved exactly, gaps included. A corrupt line is a gap, not an
ending, and a migration that closed the gap would renumber every event
after it -- the one thing the ledger contract forbids.

`ensure_migrated` is the safety net under the default flip: the live
config names no backend, so a new default would otherwise have booted
Sim against an empty database.
"""

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.envelope import Event
from simorgh.ledger.backends.jsonl import JsonlBackend
from simorgh.ledger.backends.sqlite import SqliteBackend
from simorgh.ledger.migrate import SQLITE_NAME, compare, ensure_migrated, jsonl_to_sqlite, sqlite_to_jsonl
from simorgh.ledger.streams import escape


def _event(stream, seq_hint, key=None):
    return Event(stream=stream, type="t", ts=float(seq_hint), trace_id=f"tr{seq_hint}", causation_id=None,
                 payload={"n": seq_hint}, idempotency_key=key)


async def _seed(root: Path) -> None:
    jsonl = JsonlBackend(root, fsync=False)
    await jsonl.start()
    for i in range(1, 6):
        await jsonl.append(_event("task:a", i, key=f"k{i}" if i % 2 else None), expected_seq=None)
    await jsonl.append(_event("memory:episodic", 1), expected_seq=None)
    await jsonl.put_blob(b"hello blob", content_type="text/plain")
    await jsonl.stop()
    # A corrupt line in the middle: seq 3 becomes a gap, not an ending.
    path = root / "streams" / f"{escape('task:a')}.jsonl"
    lines = path.read_text().splitlines(keepends=True)
    lines[2] = "{not json\n"
    path.write_text("".join(lines))


class BothWays(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "ledger"
        await _seed(self.root)
        self.db = self.root / SQLITE_NAME

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def test_to_sqlite_preserves_seqs_gaps_included(self):
        report = jsonl_to_sqlite(self.root, self.db)
        self.assertTrue(report.ok, report.problems)
        conn = sqlite3.connect(str(self.db))
        seqs = [r[0] for r in conn.execute("SELECT seq FROM events WHERE stream='task:a' ORDER BY seq")]
        head = conn.execute("SELECT seq FROM heads WHERE stream='task:a'").fetchone()[0]
        keys = dict(conn.execute("SELECT key, seq FROM idempotency WHERE stream='task:a'"))
        blobs = conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0]
        conn.close()
        self.assertEqual(seqs, [1, 2, 4, 5], "seq 3 is a gap, and stays one")
        self.assertEqual(head, 5)
        self.assertEqual(keys, {"k1": 1, "k5": 5})
        self.assertEqual(blobs, 1)
        self.assertEqual(compare(self.root, self.db), [])

    def test_it_is_idempotent(self):
        jsonl_to_sqlite(self.root, self.db)
        again = jsonl_to_sqlite(self.root, self.db)
        self.assertTrue(again.ok)
        conn = sqlite3.connect(str(self.db))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM events WHERE stream='task:a'").fetchone()[0], 4)
        conn.close()

    async def test_the_sqlite_backend_reads_what_was_imported(self):
        jsonl_to_sqlite(self.root, self.db)
        sq = SqliteBackend(self.db)
        await sq.start()
        try:
            self.assertEqual([e.seq for e in await sq.read("task:a", from_seq=1, limit=None)], [1, 2, 4, 5])
            self.assertEqual(await sq.head("task:a"), 5)
            self.assertEqual(await sq.find_by_idempotency("task:a", "k5"), 5)
            self.assertEqual(await sq.get_blob(f"blob:{__import__('hashlib').sha256(b'hello blob').hexdigest()}"),
                             b"hello blob")
            seq = await sq.append(_event("task:a", 6), expected_seq=5)
            self.assertEqual(seq, 6, "the next append continues from the carried head")
        finally:
            await sq.stop()

    async def test_back_to_jsonl_round_trips(self):
        jsonl_to_sqlite(self.root, self.db)
        out = Path(self.tmp.name) / "back"
        report = sqlite_to_jsonl(self.db, out)
        self.assertTrue(report.ok, report.problems)
        back = JsonlBackend(out, fsync=False)
        await back.start()
        try:
            self.assertEqual([e.seq for e in await back.read("task:a", from_seq=1, limit=None)], [1, 2, 4, 5])
            self.assertEqual(await back.head("task:a"), 5)
            self.assertEqual(await back.find_by_idempotency("task:a", "k1"), 1)
            self.assertEqual(await back.get_blob(f"blob:{__import__('hashlib').sha256(b'hello blob').hexdigest()}"),
                             b"hello blob")
        finally:
            await back.stop()
        self.assertEqual(compare(out, self.db), [])

    def test_a_head_the_file_cannot_prove_is_carried_as_a_mark(self):
        """After compaction a stream can have a head above its last event.
        That head must survive both directions or the next append reuses
        a seq readers have already folded."""
        (self.root / "heads").mkdir(exist_ok=True)
        (self.root / "heads" / f"{escape('task:a')}.head").write_text("40\n")
        jsonl_to_sqlite(self.root, self.db)
        conn = sqlite3.connect(str(self.db))
        self.assertEqual(conn.execute("SELECT seq FROM heads WHERE stream='task:a'").fetchone()[0], 40)
        conn.close()
        out = Path(self.tmp.name) / "back"
        sqlite_to_jsonl(self.db, out)
        self.assertEqual((out / "heads" / f"{escape('task:a')}.head").read_text().strip(), "40")


class TheSafetyNet(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_migrated_imports_once_and_leaves_jsonl_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ledger"
            await _seed(root)
            first = ensure_migrated(root)
            self.assertIsNotNone(first)
            self.assertEqual(first.events, 5)
            self.assertIsNone(ensure_migrated(root), "the database exists now; nothing to do")
            self.assertTrue((root / "streams").is_dir(), "JSONL stays available")

    def test_an_empty_dir_is_nothing_to_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(ensure_migrated(Path(tmp)))

    async def test_the_factory_migrates_before_opening_sqlite(self):
        from simorgh.ledger.config import Config
        from simorgh.ledger.factory import make_ledger

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ledger"
            await _seed(root)
            ledger = make_ledger(Config(backend="sqlite", data_dir=str(root)))
            await ledger.start()
            try:
                self.assertEqual(await ledger.head("task:a"), 5, "Sim remembers what it knew")
            finally:
                await ledger.stop()


if __name__ == "__main__":
    unittest.main()
