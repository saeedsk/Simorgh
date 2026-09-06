"""`simorgh/kernel/migrate_v1.py`'s `migrate()` orchestration -- distinct
from `tests/simorgh/ledger/test_migrate_v1.py`, which covers
`simorgh.ledger.migrate_v1`'s pure record-shape/routing logic. This file
covers the part that actually talks to a real `LedgerClient`: append
counts/dedup reporting, and the oversized-inline-field fallback below.

Live-caught running `simorgh migrate-v1` against the creator's real
`~/.simorgh/memory.jsonl` for the first time (06-migration section 5's
own caveat: only ever proven against a small hand-written fixture
before) -- a real `applied_source_patch` record's `metadata.code` field
(full patch source, routinely >4096 chars) blew straight through the
Ledger's inline-size validation, since no fixture record happened to be
that large.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.ledger.backends.memory import InMemoryBackend
from simorgh.ledger.blobs import is_ref
from simorgh.ledger.client import LedgerClient
from simorgh.kernel.migrate_v1 import migrate


class TestMigrate(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "memory.jsonl"
        self.ledger = LedgerClient(InMemoryBackend())

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, *records: dict) -> None:
        self.path.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    async def test_missing_file_is_a_no_op(self):
        report = await migrate(self.ledger, self.path)
        self.assertEqual(report.read, 0)
        self.assertEqual(report.appended, 0)

    async def test_normal_record_appends_and_is_reported(self):
        self._write({"id": "a1", "kind": "interest", "content": "rocketry",
                      "created_at": 1.0, "metadata": {}})
        report = await migrate(self.ledger, self.path)
        self.assertEqual(report.read, 1)
        self.assertEqual(report.appended, 1)
        self.assertEqual(report.by_stream["curiosity:interests"], 1)

    async def test_running_twice_dedupes_the_second_time(self):
        self._write({"id": "a1", "kind": "interest", "content": "rocketry",
                      "created_at": 1.0, "metadata": {}})
        await migrate(self.ledger, self.path)
        report = await migrate(self.ledger, self.path)
        self.assertEqual(report.appended, 0)
        self.assertEqual(report.skipped_duplicate, 1)

    async def test_oversized_inline_field_is_blob_stored_not_rejected(self):
        # The live-caught bug itself: a real v1 patch record's code field
        # routinely exceeds the Ledger's 4096-char inline threshold.
        big_code = "x = 1\n" * 2000  # well over 4096 chars
        self._write({"id": "p1", "kind": "applied_source_patch", "content": "patched",
                      "created_at": 1.0, "metadata": {"subject": "src/x.py", "code": big_code}})
        report = await migrate(self.ledger, self.path)
        self.assertEqual(report.appended, 1)
        [event] = await self.ledger.backend.read("learn:patches", from_seq=0, limit=None)
        self.assertNotIn("code", event.payload)
        self.assertIn("code_ref", event.payload)
        self.assertTrue(is_ref(event.payload["code_ref"]))
        stored = await self.ledger.backend.get_blob(event.payload["code_ref"])
        self.assertEqual(stored.decode("utf-8"), big_code)

    async def test_small_fields_are_left_inline(self):
        self._write({"id": "a1", "kind": "interest", "content": "rocketry",
                      "created_at": 1.0, "metadata": {"note": "short"}})
        report = await migrate(self.ledger, self.path)
        self.assertEqual(report.appended, 1)
        [event] = await self.ledger.backend.read("curiosity:interests", from_seq=0, limit=None)
        self.assertEqual(event.payload["note"], "short")
        self.assertNotIn("note_ref", event.payload)


if __name__ == "__main__":
    unittest.main()
