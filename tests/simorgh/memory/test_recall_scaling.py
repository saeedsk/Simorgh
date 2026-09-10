"""Recall has to scale without recall changing.

`MemoryEngine.retrieve` used to read every event of every requested
kind out of the Ledger and embed every one of them on every call --
~25 ms at 1,000 records per kind, ~1,010 ms at 10,000, against the
0.25 s `orchestration/context.py` allows for the whole recall. These
tests pin both halves of the fix: that the work is no longer done
(the counts below), and that not doing it changed nothing about what
comes back (the ranking comparison, which is the one that matters).

Every test here fails on the pre-index `retrieve`.
"""

from __future__ import annotations

import unittest

from simorgh.contracts.envelope import Event
from simorgh.ledger.factory import make_ledger
from simorgh.memory.api import MemoryItem
from simorgh.memory.config import Config
from simorgh.memory.embed import cosine_similarity, embed_text, sparse_cosine, sparse_embed_text
from simorgh.memory.store import MemoryEngine, stream_for
from tests.simorgh.helpers import FakeClock

WORDS = ("ledger kernel guardian curiosity reflection persona embedding vector prune tombstone "
         "consolidation session skill patch commit branch timeout budget observer recall").split()


def _content(i: int) -> str:
    return f"record {i}: " + " ".join(WORDS[(i + j) % len(WORDS)] for j in range(8))


class _CountingLedger:
    """Wraps a real ledger and records what was asked of it."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.reads: list[tuple[str, int]] = []

    async def read(self, stream, *, from_seq: int = 0, limit=None):
        self.reads.append((stream, from_seq))
        return await self._inner.read(stream, from_seq=from_seq, limit=limit)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _CountingEmbedder:
    """The default hashing embedder, counting calls."""

    provider = "hashing"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str):
        self.calls += 1
        return "hashing", embed_text(text)


async def _seeded(n: int, *, kinds=("episodic", "semantic"), clock=None):
    clock = clock or FakeClock()
    ledger = make_ledger({"backend": "memory"}, clock=clock)
    await ledger.start()
    for kind in kinds:
        stream = stream_for(kind)
        for i in range(n):
            await ledger.append(stream, Event(
                stream=stream, type="item.stored", ts=clock.now() - (n - i),
                trace_id="", causation_id=None, idempotency_key=f"{stream}:{i}",
                payload={"tags": [f"t{i % 5}"], "source_ref": "", "confidence": 1.0,
                         "content": _content(i)},
            ))
    return ledger, clock


async def _reference_ranking(ledger, clock, config, query: str, kinds, k: int):
    """What the pre-index `retrieve` returned, recomputed here from the
    Ledger directly: read every event, embed every content, score, sort.

    This is the whole point of the exercise -- the fast path has to
    agree with this, record for record and score for score, or the
    speedup bought nothing worth having.
    """
    now = clock.now()
    query_vec = embed_text(query) if query else None
    scored = []
    for kind in kinds:
        for event in await ledger.read(stream_for(kind)):
            ref = f"{stream_for(kind)}:{event.seq}"
            item = MemoryItem(ref=ref, kind=kind, content=event.payload.get("content", ""),
                              tags=tuple(event.payload.get("tags", [])),
                              confidence=float(event.payload.get("confidence", 1.0)), ts=event.ts)
            similarity = 1.0 if query_vec is None else cosine_similarity(
                query_vec, embed_text(item.content))
            confidence = item.score_confidence(now=now, half_life_seconds=config.half_life_seconds)
            age_days = max(0.0, now - item.ts) / 86400.0
            recency_bonus = 1.0 / (1.0 + age_days)
            scored.append((similarity * confidence + config.recency_weight * recency_bonus, ref))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[:k]


class RecallQualityTestCase(unittest.IsolatedAsyncioTestCase):
    """Recall quality must not silently drop. These compare the indexed
    path against a full-scan reference, not against a snapshot."""

    async def test_the_indexed_ranking_is_the_full_scan_ranking(self):
        config = Config()
        ledger, clock = await _seeded(400)
        engine = MemoryEngine(ledger, config, clock=clock)
        for query in ("prune the ledger after a failed commit",
                      "guardian budget timeout",
                      "nothing here shares a single word with anything",
                      "record 17"):
            with self.subTest(query=query):
                items, _ = await engine.retrieve(
                    query=query, kinds=["episodic", "semantic"], k=8, filters=None)
                expected = await _reference_ranking(
                    ledger, clock, config, query, ["episodic", "semantic"], 8)
                self.assertEqual([i.ref for i in items], [ref for _, ref in expected])
                # Not `assertAlmostEqual`: the sparse cosine is summed in
                # ascending bucket order precisely so it is the same
                # float, and "the same float" is a claim worth pinning.
                for item, (score, _) in zip(items, expected):
                    self.assertEqual(item.score, score)

    async def test_the_same_query_returns_the_same_top_record_across_calls(self):
        ledger, clock = await _seeded(120)
        engine = MemoryEngine(ledger, Config(), clock=clock)
        query = "prune the tombstone stream"
        first, _ = await engine.retrieve(query=query, kinds=["episodic"], k=5, filters=None)
        second, _ = await engine.retrieve(query=query, kinds=["episodic"], k=5, filters=None)
        self.assertEqual([i.ref for i in first], [i.ref for i in second])
        self.assertEqual(first[0].score, second[0].score)

    async def test_an_empty_query_still_ranks_by_recency_over_everything(self):
        config = Config()
        ledger, clock = await _seeded(50)
        engine = MemoryEngine(ledger, config, clock=clock)
        items, truncated = await engine.retrieve(query="", kinds=["episodic"], k=5, filters=None)
        expected = await _reference_ranking(ledger, clock, config, "", ["episodic"], 5)
        self.assertEqual([i.ref for i in items], [ref for _, ref in expected])
        self.assertTrue(truncated)

    async def test_the_sparse_cosine_is_the_dense_cosine_exactly(self):
        for a, b in (("prune the ledger", "prune the ledger"),
                     ("prune the ledger", "a totally different sentence"),
                     ("guardian budget timeout", "budget timeout guardian guardian"),
                     ("", "anything"),
                     ("only-one-token", "")):
            with self.subTest(a=a, b=b):
                self.assertEqual(
                    sparse_cosine(sparse_embed_text(a), sparse_embed_text(b)),
                    cosine_similarity(embed_text(a), embed_text(b)))


class RecallCostTestCase(unittest.IsolatedAsyncioTestCase):
    """The work that used to be repeated per call. Counted rather than
    timed: a timing assertion on a shared machine is a flake."""

    async def test_a_repeat_recall_does_not_re_read_the_whole_stream(self):
        ledger, clock = await _seeded(200, kinds=("episodic",))
        counting = _CountingLedger(ledger)
        engine = MemoryEngine(counting, Config(), clock=clock)
        await engine.retrieve(query="prune", kinds=["episodic"], k=5, filters=None)
        counting.reads.clear()
        await engine.retrieve(query="prune", kinds=["episodic"], k=5, filters=None)
        episodic = [from_seq for stream, from_seq in counting.reads if stream == stream_for("episodic")]
        self.assertEqual(episodic, [201], "the second recall re-read the stream from the start")

    async def test_a_recall_embeds_the_query_and_nothing_else(self):
        ledger, clock = await _seeded(200, kinds=("episodic",))
        embedder = _CountingEmbedder()
        engine = MemoryEngine(ledger, Config(), clock=clock, embedder=embedder)
        await engine.retrieve(query="prune", kinds=["episodic"], k=5, filters=None)
        self.assertEqual(embedder.calls, 1, "the store was re-embedded record by record")
        await engine.retrieve(query="prune again", kinds=["episodic"], k=5, filters=None)
        self.assertEqual(embedder.calls, 2)


class IndexFreshnessTestCase(unittest.IsolatedAsyncioTestCase):
    """A cache that answers from yesterday is a worse bug than the one
    it was built to fix, so each way memory changes gets its own test."""

    async def test_a_record_stored_after_the_first_recall_is_recalled(self):
        ledger, clock = await _seeded(20, kinds=("semantic",))
        engine = MemoryEngine(ledger, Config(), clock=clock)
        await engine.retrieve(query="anything", kinds=["semantic"], k=3, filters=None)
        await engine.store(kind="semantic", content="the umbrella is in the hall cupboard",
                           tags=["place"], source_ref="", confidence=1.0)
        items, _ = await engine.retrieve(
            query="umbrella hall cupboard", kinds=["semantic"], k=3, filters=None)
        self.assertEqual(items[0].content, "the umbrella is in the hall cupboard")

    async def test_a_forgotten_record_stops_coming_back(self):
        ledger, clock = await _seeded(20, kinds=("semantic",))
        engine = MemoryEngine(ledger, Config(), clock=clock)
        items, _ = await engine.retrieve(query="record 19", kinds=["semantic"], k=1, filters=None)
        doomed = items[0].ref
        await engine.forget([doomed], reason="test")
        after, _ = await engine.retrieve(query="record 19", kinds=["semantic"], k=5, filters=None)
        self.assertNotIn(doomed, [i.ref for i in after])

    async def test_a_contradiction_penalty_applies_to_a_record_already_indexed(self):
        ledger, clock = await _seeded(0, kinds=("semantic",))
        engine = MemoryEngine(ledger, Config(recency_weight=0.0), clock=clock)
        await engine.store(kind="semantic", content="the cat is black", tags=["cat"],
                           source_ref="", confidence=1.0)
        await engine.store(kind="semantic", content="the cat is white", tags=["cat"],
                           source_ref="", confidence=1.0)
        before, _ = await engine.retrieve(query="the cat is black", kinds=["semantic"], k=2, filters=None)
        await engine.flag_contradictions(kind="semantic")
        after, _ = await engine.retrieve(query="the cat is black", kinds=["semantic"], k=2, filters=None)
        self.assertLess(after[0].score, before[0].score)

    async def test_a_record_written_by_another_process_is_picked_up(self):
        """The index syncs from the Ledger, not from this engine's own
        `store` calls -- a second Worker's writes have to appear."""
        ledger, clock = await _seeded(5, kinds=("episodic",))
        engine = MemoryEngine(ledger, Config(), clock=clock)
        await engine.retrieve(query="x", kinds=["episodic"], k=1, filters=None)
        other = MemoryEngine(ledger, Config(), clock=clock)
        await other.store(kind="episodic", content="written elsewhere entirely",
                          tags=[], source_ref="", confidence=1.0)
        items, _ = await engine.retrieve(
            query="written elsewhere entirely", kinds=["episodic"], k=1, filters=None)
        self.assertEqual(items[0].content, "written elsewhere entirely")

    async def test_filters_still_apply_after_the_records_are_indexed(self):
        ledger, clock = await _seeded(50, kinds=("procedural",))
        engine = MemoryEngine(ledger, Config(), clock=clock)
        items, _ = await engine.retrieve(query="record", kinds=["procedural"], k=50,
                                         filters={"tags": ["t3"]})
        self.assertTrue(items)
        self.assertTrue(all("t3" in i.tags for i in items))


class WarmTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_warming_means_the_first_recall_reads_nothing_new(self):
        ledger, clock = await _seeded(120, kinds=("episodic",))
        counting = _CountingLedger(ledger)
        engine = MemoryEngine(counting, Config(), clock=clock)
        self.assertEqual(await engine.warm(("episodic",)), 120)
        counting.reads.clear()
        await engine.retrieve(query="prune", kinds=["episodic"], k=5, filters=None)
        episodic = [from_seq for stream, from_seq in counting.reads if stream == stream_for("episodic")]
        self.assertEqual(episodic, [121])


class EmbedderCacheTestCase(unittest.TestCase):
    def test_the_cache_evicts_least_recently_used_not_first_inserted(self):
        """FIFO eviction at exactly the wrong size was the second half of
        the original measurement: past `_cache_max` records, one recall
        evicted everything the previous one had cached, and the second
        call to `retrieve` was SLOWER than the first."""
        from simorgh.memory.embedders import Embedder

        embedder = Embedder("hashing")
        embedder._cache_max = 3
        for text in ("a", "b", "c"):
            embedder.embed(text)
        embedder.embed("a")   # a is now the most recently used
        embedder.embed("d")   # evicts something
        self.assertIn("a", embedder._cache, "the hot entry was evicted for being old")
        self.assertNotIn("b", embedder._cache)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
