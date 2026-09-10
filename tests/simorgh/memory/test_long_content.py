"""Memory keeps a long turn instead of throwing it away.

`MemoryEngine.store` appended content inline, and the Ledger refuses any
string over 4,096 characters -- so **the longer and more useful an
answer was, the more certain it was to be forgotten**. The refusal came
out of the `turn.completed` handler as an unhandled `ValidationError`,
which is not something a person can act on.

Caught live on 2026-09-09: a 5,165-character reply about Sim's own
architecture, which is exactly the kind of answer worth remembering."""

from __future__ import annotations

import unittest

from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config
from simorgh.memory.store import MemoryEngine

from tests.simorgh.helpers import FakeClock


class _MemoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.engine = MemoryEngine(self.ledger, Config(), clock=self.clock)

    async def asyncTearDown(self):
        await self.ledger.stop()

    async def _recall(self, query: str, k: int = 5):
        items, _ = await self.engine.retrieve(query=query, kinds=["episodic"], k=k, filters={})
        return items


class LongContentTestCase(_MemoryTestCase):
    LONG = "User: tell me about your architecture\nSim: " + ("subsystem detail. " * 400)

    async def test_a_turn_over_the_inline_limit_is_stored_rather_than_raising(self):
        self.assertGreater(len(self.LONG), 4096)
        ref = await self.engine.store(kind="episodic", content=self.LONG, tags=["s1"],
                                       source_ref="", confidence=None)
        self.assertTrue(ref)

    async def test_it_comes_back_whole(self):
        await self.engine.store(kind="episodic", content=self.LONG, tags=["s1"],
                                 source_ref="", confidence=None)
        items = await self._recall("architecture")
        self.assertEqual(items[0].content, self.LONG)

    async def test_the_ledger_row_itself_stays_under_the_inline_limit(self):
        await self.engine.store(kind="episodic", content=self.LONG, tags=["s1"],
                                 source_ref="", confidence=None)
        events = await self.ledger.read("memory:episodic")
        payload = events[0].payload
        self.assertLessEqual(len(payload["content"]), 4096)
        self.assertTrue(payload["content_ref"])
        self.assertEqual(payload["content_chars"], len(self.LONG))

    async def test_a_short_turn_is_still_stored_inline_with_no_blob(self):
        await self.engine.store(kind="episodic", content="a short exchange", tags=[],
                                 source_ref="", confidence=None)
        payload = (await self.ledger.read("memory:episodic"))[0].payload
        self.assertEqual(payload["content"], "a short exchange")
        self.assertNotIn("content_ref", payload)

    async def test_a_long_turn_is_still_findable_by_something_it_says(self):
        """The preview is what scoring sees, so a long item must not
        become unsearchable by being blobbed."""
        content = "User: what is the boiler model\nSim: it is a Vaillant ecoTEC. " + ("x " * 3000)
        await self.engine.store(kind="episodic", content=content, tags=[], source_ref="",
                                 confidence=None)
        items = await self._recall("Vaillant boiler")
        self.assertTrue(items)
        self.assertIn("Vaillant", items[0].content)

    async def test_several_long_turns_all_survive(self):
        for n in range(3):
            await self.engine.store(kind="episodic", content=f"turn {n} " + ("y " * 3000),
                                     tags=[], source_ref="", confidence=None)
        items = await self._recall("turn", k=5)
        self.assertEqual(len(items), 3)
        for item in items:
            self.assertGreater(len(item.content), 4096)

    async def test_a_blob_that_cannot_be_read_returns_the_preview_rather_than_nothing(self):
        """A memory that is half there beats one that raises during
        recall."""
        await self.engine.store(kind="episodic", content=self.LONG, tags=[], source_ref="",
                                 confidence=None)

        async def _broken(ref):
            raise RuntimeError("blob is gone")

        self.ledger.get_blob = _broken
        items = await self._recall("architecture")
        self.assertTrue(items[0].content)
        self.assertLess(len(items[0].content), len(self.LONG))

    async def test_a_ledger_that_will_not_blob_still_remembers_a_truncated_version(self):
        async def _broken(data):
            raise RuntimeError("no blobs today")

        self.ledger.put_blob = _broken
        ref = await self.engine.store(kind="episodic", content=self.LONG, tags=[],
                                       source_ref="", confidence=None)
        self.assertTrue(ref, "a truncated memory beats a lost one")


class APartialRecallSaysSoTestCase(LongContentTestCase):
    """A memory system that quietly shortens what it remembers is the
    worst place for "succeeds while saying nothing true".

    `content_chars` has been written at store time since the blob split
    landed, and nothing ever read it. Both partial paths -- a blob that
    could not be WRITTEN, and a blob that cannot now be READ -- returned
    a 3,500-character prefix cut mid-sentence, indistinguishable from a
    memory that was genuinely that short. Observed 2026-09-10: a 6,513
    character record recalled as 3,500 characters ending "...Per-case
    detail line with scoring,".
    """

    async def test_an_unreadable_blob_admits_the_memory_is_partial(self):
        await self.engine.store(kind="episodic", content=self.LONG, tags=[], source_ref="",
                                confidence=None)

        async def _broken(ref):
            raise RuntimeError("blob is gone")

        self.ledger.get_blob = _broken
        items = await self._recall("architecture")
        self.assertIn("memory truncated", items[0].content)
        self.assertIn(str(len(self.LONG)), items[0].content)

    async def test_a_memory_that_never_got_its_blob_admits_it_too(self):
        async def _broken(data):
            raise RuntimeError("no blobs today")

        self.ledger.put_blob = _broken
        await self.engine.store(kind="episodic", content=self.LONG, tags=[], source_ref="",
                                confidence=None)
        items = await self._recall("architecture")
        self.assertIn("memory truncated", items[0].content)

    async def test_a_whole_memory_says_nothing_extra(self):
        """The notice must appear only when something is actually
        missing -- a marker on every recall would be noise, and noise
        gets ignored."""
        await self.engine.store(kind="episodic", content=self.LONG, tags=[], source_ref="",
                                confidence=None)
        items = await self._recall("architecture")
        self.assertNotIn("memory truncated", items[0].content)
        self.assertEqual(items[0].content, self.LONG)

    async def test_a_short_memory_is_untouched(self):
        await self.engine.store(kind="episodic", content="a short note about boilers", tags=[],
                                source_ref="", confidence=None)
        items = await self._recall("boilers")
        self.assertEqual(items[0].content, "a short note about boilers")


class TheNoticeReachesTheReaderTestCase(LongContentTestCase):
    """The notice was appended to the tail, and the only consumer trims
    each recalled item to 800 characters -- so it was cut off the end of
    every memory long enough to need it.

    The fix was invisible exactly where it mattered. And a blob cut
    mid-character decoded with `errors="replace"` came back at the SAME
    character count, so the length check saw nothing wrong and the
    memory read as whole, ending in a replacement character (observer,
    2026-09-10, on the fix from the same morning).
    """

    async def test_the_notice_survives_a_reader_that_trims_the_tail(self):
        from simorgh.orchestration.context import _MEMORY_ITEM_MAX_CHARS

        await self.engine.store(kind="episodic", content=self.LONG, tags=[], source_ref="",
                                confidence=None)

        async def _broken(ref):
            raise RuntimeError("blob is gone")

        self.ledger.get_blob = _broken
        items = await self._recall("architecture")
        self.assertIn("memory truncated", items[0].content[:_MEMORY_ITEM_MAX_CHARS])

    async def test_a_blob_cut_mid_character_is_not_read_as_whole(self):
        stored = await self.engine.store(kind="episodic", content=self.LONG + "é" * 200,
                                         tags=[], source_ref="", confidence=None)
        self.assertTrue(stored)
        whole = (self.LONG + "é" * 200).encode("utf-8")

        async def _cut(ref):
            return whole[:-1]       # ends mid-character

        self.ledger.get_blob = _cut
        items = await self._recall("architecture")
        self.assertIn("memory truncated", items[0].content)

    async def test_a_whole_memory_still_says_nothing(self):
        await self.engine.store(kind="episodic", content=self.LONG, tags=[], source_ref="",
                                confidence=None)
        items = await self._recall("architecture")
        self.assertNotIn("memory truncated", items[0].content)
