"""Stage 5 item 5: the turn's recall starts at the percept, beside session
setup, so Memory is off the critical path -- and a slow Memory that would
miss the 0.25 s blocking budget is still there when the session asks."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.context import Assembler, _MEMORY_MATCHED_K

from .harness import Harness, run


class SpeculativeRecall(unittest.TestCase):
    @run
    async def test_a_prefetched_recall_is_used_and_not_repeated(self):
        async with Harness() as h:
            memory_bus, asked = h.client("memory"), []

            async def _memory(message):
                asked.append(message.payload["query"])
                if message.payload["query"]:
                    await asyncio.sleep(0.4)      # slower than the 0.25 s blocking budget
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={
                    "items": [{"ref": "episodic:1", "content": "the boiler was serviced in May",
                               "kind": "episodic", "score": 0.9, "confidence": 1.0, "ts": 5.0}],
                    "truncated": False})

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _memory)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="s1", kind="chat", mode="execute", profile=profiles.CHAT,
                              user_text="when was the boiler serviced")
            assembler.prefetch("s1", "when was the boiler serviced",
                               kinds=["episodic", "semantic"], k=_MEMORY_MATCHED_K)
            await asyncio.sleep(0.45)            # the session is being built meanwhile
            mem, why, _facts = await assembler._memory_block("when was the boiler serviced", session)  # noqa: SLF001
            await sub.unsubscribe()

        self.assertIn("boiler was serviced", mem, "the slow recall was ready by the time it was needed")
        self.assertEqual(asked.count("when was the boiler serviced"), 1, "asked once, not twice")

    @run
    async def test_without_a_prefetch_the_ordinary_recall_still_happens(self):
        async with Harness() as h:
            memory_bus, asked = h.client("memory"), []

            async def _memory(message):
                asked.append(message.payload["query"])
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY,
                                       payload={"items": [], "truncated": False})

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _memory)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="s2", kind="chat", mode="execute", profile=profiles.CHAT)
            await assembler._memory_block("anything", session)  # noqa: SLF001
            await sub.unsubscribe()
        self.assertIn("anything", asked)

    @run
    async def test_a_prefetch_for_a_turn_that_never_ran_is_dropped(self):
        async with Harness() as h:
            assembler = Assembler(h.client("orchestration"))
            assembler.prefetch("s3", "x", kinds=["episodic"], k=3)
            assembler.forget_prefetched("s3")
            self.assertEqual(assembler._prefetched, {})  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
