"""`MemoryEngine` (docs/blueprint/subsystems/05-memory.md sections 4-5):
retrieval scoring, confidence decay, contradiction flagging, and
forgetting as tombstone events -- append-only stays append-only even for
"pruning" (principle 4.4)."""

from __future__ import annotations

import unittest

from simorgh.ledger.factory import make_ledger
from simorgh.memory.api import MemoryItem
from simorgh.memory.config import Config
from simorgh.memory.store import CONTRADICTION_STREAM, TOMBSTONE_STREAM, MemoryEngine, WorkingMemory, stream_for
from tests.simorgh.helpers import FakeClock


class TestMemoryItemConfidenceDecay(unittest.TestCase):
    def test_no_elapsed_time_is_full_confidence(self):
        item = MemoryItem(ref="r", kind="semantic", content="x", tags=(), confidence=1.0, ts=1000.0)
        self.assertAlmostEqual(item.score_confidence(now=1000.0, half_life_seconds=100.0), 1.0)

    def test_one_half_life_elapsed_halves_confidence(self):
        item = MemoryItem(ref="r", kind="semantic", content="x", tags=(), confidence=1.0, ts=1000.0)
        self.assertAlmostEqual(item.score_confidence(now=1100.0, half_life_seconds=100.0), 0.5)

    def test_two_half_lives_quarters_confidence(self):
        item = MemoryItem(ref="r", kind="semantic", content="x", tags=(), confidence=1.0, ts=1000.0)
        self.assertAlmostEqual(item.score_confidence(now=1200.0, half_life_seconds=100.0), 0.25)

    def test_penalty_multiplies_in(self):
        item = MemoryItem(ref="r", kind="semantic", content="x", tags=(), confidence=1.0, ts=1000.0)
        self.assertAlmostEqual(item.score_confidence(now=1000.0, half_life_seconds=100.0, penalty=0.5), 0.5)

    def test_zero_half_life_is_no_decay_at_all(self):
        item = MemoryItem(ref="r", kind="semantic", content="x", tags=(), confidence=0.8, ts=0.0)
        self.assertAlmostEqual(item.score_confidence(now=1_000_000.0, half_life_seconds=0.0), 0.8)


class TestWorkingMemory(unittest.TestCase):
    def test_bounded_by_max_turns(self):
        wm = WorkingMemory(max_turns=2, max_chars=10_000)
        for i in range(5):
            wm.add("s1", f"q{i}", f"a{i}", ts=float(i))
        turns = wm.recent("s1")
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[-1].request_text, "q4")

    def test_bounded_by_max_chars_evicts_oldest_first(self):
        wm = WorkingMemory(max_turns=100, max_chars=20)
        wm.add("s1", "x" * 10, "y" * 10, ts=0.0)
        wm.add("s1", "z" * 10, "w" * 10, ts=1.0)
        turns = wm.recent("s1")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].request_text, "z" * 10)

    def test_sessions_are_independent(self):
        wm = WorkingMemory(max_turns=5, max_chars=10_000)
        wm.add("a", "q", "a-answer", ts=0.0)
        self.assertEqual(wm.recent("b"), [])
        self.assertEqual(len(wm.recent("a")), 1)


class TestMemoryEngineStoreAndRetrieve(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.engine = MemoryEngine(self.ledger, Config(half_life_seconds=100.0, recency_weight=0.0), clock=self.clock)

    async def test_store_then_retrieve_round_trip(self):
        ref = await self.engine.store(kind="semantic", content="the sky is blue", tags=["fact"], source_ref="", confidence=1.0)
        self.assertTrue(ref.startswith(stream_for("semantic")))
        items, truncated = await self.engine.retrieve(query="sky", kinds=["semantic"], k=5, filters=None)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].content, "the sky is blue")
        self.assertFalse(truncated)

    async def test_retrieve_ranks_the_more_similar_item_first(self):
        await self.engine.store(kind="semantic", content="cats are small mammals", tags=[], source_ref="", confidence=1.0)
        await self.engine.store(kind="semantic", content="the stock market fell today", tags=[], source_ref="", confidence=1.0)
        items, _ = await self.engine.retrieve(query="small mammals cats", kinds=["semantic"], k=5, filters=None)
        self.assertEqual(items[0].content, "cats are small mammals")

    async def test_k_truncates_and_reports_truncated_true(self):
        for i in range(5):
            await self.engine.store(kind="episodic", content=f"event {i}", tags=[], source_ref="", confidence=1.0)
        items, truncated = await self.engine.retrieve(query="", kinds=["episodic"], k=2, filters=None)
        self.assertEqual(len(items), 2)
        self.assertTrue(truncated)

    async def test_filters_by_tag(self):
        await self.engine.store(kind="semantic", content="tagged one", tags=["a"], source_ref="", confidence=1.0)
        await self.engine.store(kind="semantic", content="tagged two", tags=["b"], source_ref="", confidence=1.0)
        items, _ = await self.engine.retrieve(query="", kinds=["semantic"], k=5, filters={"tags": ["a"]})
        self.assertEqual([i.content for i in items], ["tagged one"])

    async def test_filters_by_since(self):
        await self.engine.store(kind="episodic", content="old event", tags=[], source_ref="", confidence=1.0)
        self.clock.advance(1000.0)
        await self.engine.store(kind="episodic", content="new event", tags=[], source_ref="", confidence=1.0)
        items, _ = await self.engine.retrieve(query="", kinds=["episodic"], k=10, filters={"since": self.clock.now() - 1.0})
        self.assertEqual([i.content for i in items], ["new event"])

    async def test_working_memory_kind_reads_from_the_session_not_the_ledger(self):
        self.engine.working.add("sess1", "how are you", "doing well", ts=self.clock.now())
        items, _ = await self.engine.retrieve(query="", kinds=["working"], k=5, filters={"session_id": "sess1"})
        self.assertEqual(len(items), 1)
        self.assertIn("doing well", items[0].content)

    async def test_confidence_decay_pulls_an_old_item_below_a_fresh_one_of_equal_relevance(self):
        await self.engine.store(kind="semantic", content="widget facts widget facts", tags=[], source_ref="", confidence=1.0)
        self.clock.advance(500.0)  # 5 half-lives -- old item decays hard
        await self.engine.store(kind="semantic", content="widget facts widget facts", tags=[], source_ref="", confidence=1.0)
        items, _ = await self.engine.retrieve(query="widget facts", kinds=["semantic"], k=5, filters=None)
        self.assertEqual(items[0].ts, self.clock.now())  # the fresher, higher-confidence one ranks first


class TestMemoryEngineContradictionsAndPruning(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.engine = MemoryEngine(self.ledger, Config(half_life_seconds=1_000_000.0), clock=self.clock)

    async def test_two_records_with_the_same_first_tag_but_different_content_are_flagged(self):
        await self.engine.store(kind="semantic", content="the sky is blue", tags=["sky-color"], source_ref="", confidence=1.0)
        self.clock.advance(1.0)
        await self.engine.store(kind="semantic", content="the sky is green", tags=["sky-color"], source_ref="", confidence=1.0)
        flagged = await self.engine.flag_contradictions(kind="semantic")
        self.assertEqual(len(flagged), 1)
        ref_a, ref_b, evidence = flagged[0]
        self.assertIn("sky-color", evidence)
        self.assertIn("blue", evidence)
        self.assertIn("green", evidence)

    async def test_records_with_the_same_content_are_not_flagged(self):
        await self.engine.store(kind="semantic", content="the sky is blue", tags=["sky-color"], source_ref="", confidence=1.0)
        await self.engine.store(kind="semantic", content="the sky is blue", tags=["sky-color"], source_ref="", confidence=1.0)
        flagged = await self.engine.flag_contradictions(kind="semantic")
        self.assertEqual(flagged, [])

    async def test_records_without_tags_are_never_flagged(self):
        await self.engine.store(kind="semantic", content="a", tags=[], source_ref="", confidence=1.0)
        await self.engine.store(kind="semantic", content="b", tags=[], source_ref="", confidence=1.0)
        flagged = await self.engine.flag_contradictions(kind="semantic")
        self.assertEqual(flagged, [])

    async def test_a_flagged_pair_never_mutates_the_original_records(self):
        # Append-only, always -- contradictions are a *separate* durable
        # stream, never a rewrite of the original event (05 section 5).
        await self.engine.store(kind="semantic", content="the sky is blue", tags=["sky-color"], source_ref="", confidence=1.0)
        self.clock.advance(1.0)
        await self.engine.store(kind="semantic", content="the sky is green", tags=["sky-color"], source_ref="", confidence=1.0)
        await self.engine.flag_contradictions(kind="semantic")
        events = await self.ledger.read(stream_for("semantic"))
        self.assertEqual(len(events), 2)
        self.assertEqual({e.payload["content"] for e in events}, {"the sky is blue", "the sky is green"})
        contradiction_events = await self.ledger.read(CONTRADICTION_STREAM)
        self.assertEqual(len(contradiction_events), 1)

    async def test_a_flagged_item_ranks_below_an_equally_relevant_clean_one(self):
        engine = MemoryEngine(self.ledger, Config(half_life_seconds=1_000_000.0, recency_weight=0.0), clock=self.clock)
        await engine.store(kind="semantic", content="contested topic alpha", tags=["dispute"], source_ref="", confidence=1.0)
        self.clock.advance(1.0)
        await engine.store(kind="semantic", content="contested topic beta", tags=["dispute"], source_ref="", confidence=1.0)
        await engine.flag_contradictions(kind="semantic")
        await engine.store(kind="semantic", content="contested topic gamma", tags=[], source_ref="", confidence=1.0)
        items, _ = await engine.retrieve(query="contested topic", kinds=["semantic"], k=10, filters=None)
        order = [i.content for i in items]
        self.assertLess(order.index("contested topic gamma"), order.index("contested topic alpha"))
        self.assertLess(order.index("contested topic gamma"), order.index("contested topic beta"))

    async def test_forget_tombstones_refs_so_they_are_excluded_from_retrieval(self):
        ref = await self.engine.store(kind="semantic", content="to be forgotten", tags=[], source_ref="", confidence=1.0)
        await self.engine.forget([ref], reason="test")
        items, _ = await self.engine.retrieve(query="", kinds=["semantic"], k=10, filters=None)
        self.assertEqual(items, [])
        # tombstoning is an event, not a physical delete -- the original record still exists in the stream.
        events = await self.ledger.read(stream_for("semantic"))
        self.assertEqual(len(events), 1)
        tombstones = await self.ledger.read(TOMBSTONE_STREAM)
        self.assertEqual(len(tombstones), 1)
        self.assertEqual(tombstones[0].payload["refs"], [ref])

    async def test_prune_keeps_only_the_top_scoring_n_and_tombstones_the_rest(self):
        for i in range(5):
            await self.engine.store(kind="episodic", content=f"event {i}", tags=[], source_ref="", confidence=1.0)
        pruned_count = await self.engine.prune(kind="episodic", keep=2)
        self.assertEqual(pruned_count, 3)
        items, _ = await self.engine.retrieve(query="", kinds=["episodic"], k=10, filters=None)
        self.assertEqual(len(items), 2)

    async def test_prune_below_the_keep_count_is_a_no_op(self):
        await self.engine.store(kind="episodic", content="only one", tags=[], source_ref="", confidence=1.0)
        pruned_count = await self.engine.prune(kind="episodic", keep=5)
        self.assertEqual(pruned_count, 0)


if __name__ == "__main__":
    unittest.main()
