"""`Assembler._memory_retrieve` (16-orchestration.md section 5):
live-caught, real use (07-post-cutover-review.md section 3.4d/3.3) --
a single oversized or many small retrieved memory records could make
the elastic "conversation" block too large for Cognition's compaction
to shrink under budget, producing a real `context_too_large` failure
even with `allow_summarize=True`. Bounding what's handed to Cognition
in the first place, distinct from `tests/simorgh/orchestration/
test_session_flows.py`'s end-to-end session-state-machine coverage."""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.context import Assembler, _MEMORY_BLOCK_MAX_CHARS, _MEMORY_ITEM_MAX_CHARS

from .harness import Harness, run


class TestMemoryRetrieveSizeCap(unittest.TestCase):
    @run
    async def test_a_single_oversized_item_is_truncated_not_passed_through_whole(self):
        async with Harness() as h:
            memory_bus = h.client("memory")
            huge = "x" * 50_000  # far over any reasonable single-item budget

            async def _responder(message):
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={
                    "items": [{"ref": "episodic:1", "content": huge, "kind": "episodic",
                               "score": 1.0, "confidence": 1.0, "ts": 0.0}],
                    "truncated": False,
                })

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT)
            mem = await assembler._memory_retrieve("query", session)  # noqa: SLF001
            await sub.unsubscribe()

            self.assertLess(len(mem), len(huge))
            self.assertLessEqual(len(mem), _MEMORY_ITEM_MAX_CHARS + 10)
            self.assertTrue(huge.startswith(mem.removeprefix("- ").removesuffix("…")))  # real prefix, not fabricated

    @run
    async def test_many_items_are_bounded_in_aggregate(self):
        async with Harness() as h:
            memory_bus = h.client("memory")
            # 8 items, each under the per-item cap alone, but well over the
            # aggregate cap together.
            items = [{"ref": f"episodic:{i}", "content": f"item {i}: " + "y" * 700, "kind": "episodic",
                      "score": 1.0, "confidence": 1.0, "ts": 0.0} for i in range(8)]

            async def _responder(message):
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={"items": items, "truncated": False})

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t2", kind="chat", mode="execute", profile=profiles.CHAT)
            mem = await assembler._memory_retrieve("query", session)  # noqa: SLF001
            await sub.unsubscribe()

            self.assertLessEqual(len(mem), _MEMORY_BLOCK_MAX_CHARS + 800)  # one item's worth of slack at the boundary
            self.assertIn("item 0:", mem)  # the strongest (highest-ranked) match is kept, not dropped

    @run
    async def test_small_items_are_untouched(self):
        async with Harness() as h:
            memory_bus = h.client("memory")

            async def _responder(message):
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={
                    "items": [{"ref": "semantic:1", "content": "the sky is blue", "kind": "semantic",
                               "score": 1.0, "confidence": 1.0, "ts": 0.0}],
                    "truncated": False,
                })

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t3", kind="chat", mode="execute", profile=profiles.CHAT)
            mem = await assembler._memory_retrieve("query", session)  # noqa: SLF001
            await sub.unsubscribe()

            self.assertEqual(mem, "- the sky is blue")


if __name__ == "__main__":
    unittest.main()
