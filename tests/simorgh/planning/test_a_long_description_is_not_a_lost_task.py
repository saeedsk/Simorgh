"""A 5,564-character description used to destroy the task silently.

Live, 2026-09-10, from the creator's terminal:

    [bus] handler for task.create raised ValidationError:
      $.description: 5564 chars inline exceeds 4096; store it with
      put_blob and reference it
      ...
      File "simorgh/planning/store.py", line 186, in create
        seq = await self._ledger.append(stream, event)
      → final answer  ok

Three things went wrong at once and only the middle one is Planning's:

  1. the Ledger's inline limit is real and correct -- a long string
     belongs in a blob -- and nothing on the Planning side had ever
     obeyed it, though a long description is the ORDINARY case for a
     decomposed step or a pasted brief;
  2. so `task.create` raised out of the Bus handler and no task was
     created; and
  3. the Bus logs a raising handler rather than answering, so the
     session that asked went on to print `final answer  ok`. The
     system said it had made a task it had not.

The fix here is (1)/(2): the full text goes to a blob, the event keeps
a preview that says so, and `Worker` reads the ref back before it
prompts -- so the model is not handed an instruction that stops
mid-sentence with nothing saying it was cut.
"""

from __future__ import annotations

import unittest

from simorgh.ledger.backends.memory import InMemoryBackend
from simorgh.ledger.blobs import is_ref
from simorgh.ledger.client import LedgerClient
from simorgh.planning.store import TaskStore
from tests.simorgh.helpers import FakeClock


class _Ledger(LedgerClient):
    pass


def _client() -> LedgerClient:
    return LedgerClient(InMemoryBackend(), source="test")


class LongDescriptionTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.ledger = _client()
        self.store = TaskStore(self.ledger, FakeClock())

    async def test_the_exact_length_that_broke_it(self) -> None:
        brief = "x" * 5564
        task = await self.store.create(kind="patch", description=brief, origin="human")
        self.assertTrue(task.id)
        self.assertTrue(is_ref(task.description_ref))
        whole = (await self.ledger.get_blob(task.description_ref)).decode("utf-8")
        self.assertEqual(whole, brief)

    async def test_the_preview_says_it_is_one(self) -> None:
        task = await self.store.create(kind="patch", description="y" * 9000, origin="human")
        self.assertLessEqual(len(task.description), self.ledger.inline_threshold)
        self.assertIn("9000 chars in total", task.description)
        self.assertIn(task.description_ref, task.description)

    async def test_a_short_description_is_untouched(self) -> None:
        task = await self.store.create(kind="patch", description="fix the thing", origin="human")
        self.assertEqual(task.description, "fix the thing")
        self.assertEqual(task.description_ref, "")

    async def test_a_description_exactly_at_the_limit_stays_inline(self) -> None:
        exact = "z" * self.ledger.inline_threshold
        task = await self.store.create(kind="patch", description=exact, origin="human")
        self.assertEqual(task.description, exact)
        self.assertEqual(task.description_ref, "")

    async def test_the_ref_survives_a_rebuild_from_the_ledger(self) -> None:
        # The index is a projection. A ref the projection drops is a
        # brief the worker cannot find after a restart.
        task = await self.store.create(kind="patch", description="w" * 8000, origin="human")
        fresh = TaskStore(self.ledger, FakeClock())
        await fresh.rebuild()
        self.assertEqual(fresh.index.tasks[task.id].description_ref, task.description_ref)

    async def test_a_blob_store_that_refuses_still_yields_a_task(self) -> None:
        """A task with a shortened brief beats no task and a traceback --
        but the shortening is stated, never silent."""
        async def _no(*_a, **_k):
            raise RuntimeError("blob store down")

        self.ledger.put_blob = _no  # type: ignore[method-assign]
        task = await self.store.create(kind="patch", description="q" * 7000, origin="human")
        self.assertEqual(task.description_ref, "")
        self.assertIn("could not be stored", task.description)
        self.assertIn("7000 chars", task.description)


class WorkerReadsTheWholeBriefTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_the_worker_prompts_with_the_full_text_not_the_preview(self) -> None:
        from simorgh.orchestration.worker import Worker

        ledger = _client()
        store = TaskStore(ledger, FakeClock())
        brief = "the whole brief. " * 500
        task = await store.create(kind="patch", description=brief, origin="human")

        worker = Worker.__new__(Worker)
        worker._ledger = ledger  # noqa: SLF001
        worker._bus = None  # noqa: SLF001
        resolved = await worker._full_description(  # noqa: SLF001
            {"task_id": task.id, "description": task.description,
             "description_ref": task.description_ref})
        self.assertEqual(resolved, brief)

    async def test_an_unreadable_ref_falls_back_to_the_preview(self) -> None:
        from simorgh.orchestration.worker import Worker

        ledger = _client()
        worker = Worker.__new__(Worker)
        worker._ledger = ledger  # noqa: SLF001
        worker._bus = None  # noqa: SLF001
        resolved = await worker._full_description(  # noqa: SLF001
            {"task_id": "t1", "description": "preview...", "description_ref": "blob:sha256:deadbeef"})
        self.assertEqual(resolved, "preview...")

    async def test_no_ref_is_the_description_itself(self) -> None:
        from simorgh.orchestration.worker import Worker

        worker = Worker.__new__(Worker)
        worker._ledger = None  # noqa: SLF001
        worker._bus = None  # noqa: SLF001
        self.assertEqual(
            await worker._full_description({"description": "short"}),  # noqa: SLF001
            "short")


if __name__ == "__main__":
    unittest.main()
