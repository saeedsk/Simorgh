"""A long answer used to leave its task unfinished (arm 25, 2026-09-15).

`_on_task_completed` passes the answer as the status note; a 14,359-character
GAIA answer exceeded the Ledger's inline limit, the append raised inside the
Bus handler, and the task never became `completed`."""

from __future__ import annotations

import unittest

from simorgh.ledger.backends.memory import InMemoryBackend
from simorgh.ledger.blobs import is_ref
from simorgh.ledger.client import LedgerClient
from simorgh.planning.model import AVAILABLE, CLAIMED, COMPLETED, IN_PROGRESS
from simorgh.planning.store import TaskStore
from tests.simorgh.helpers import FakeClock


class LongAnswerTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.ledger = LedgerClient(InMemoryBackend(), source="test")
        self.store = TaskStore(self.ledger, FakeClock())

    async def _to_in_progress(self):
        task = await self.store.create(kind="research", description="q", origin="benchmark")
        if task.status != AVAILABLE:
            await self.store.transition(task.id, AVAILABLE)
        await self.store.claim(task.id, "w1", 600)
        if self.store.index.tasks[task.id].status == CLAIMED:
            await self.store.transition(task.id, IN_PROGRESS)
        return task

    async def test_the_length_that_broke_it(self) -> None:
        task = await self._to_in_progress()
        answer = "FINAL ANSWER: " + "y" * 14345
        done = await self.store.transition(task.id, COMPLETED, note=answer)
        self.assertEqual(done.status, COMPLETED)
        self.assertLessEqual(len(done.note), 4096)
        self.assertIn("14359 chars in total", done.note)
        events = await self.ledger.read(f"task:{task.id}")
        ref = next(e.payload["note_ref"] for e in events if e.type == "status_changed" and e.payload.get("note_ref"))
        self.assertTrue(is_ref(ref))
        self.assertEqual((await self.ledger.get_blob(ref)).decode("utf-8"), answer)

    async def test_a_short_note_keeps_its_shape(self) -> None:
        task = await self._to_in_progress()
        await self.store.transition(task.id, COMPLETED, note="FINAL ANSWER: 3")
        events = await self.ledger.read(f"task:{task.id}")
        last = [e for e in events if e.type == "status_changed"][-1]
        self.assertEqual(last.payload, {"status": COMPLETED, "note": "FINAL ANSWER: 3", "attempt": False})


if __name__ == "__main__":
    unittest.main()
