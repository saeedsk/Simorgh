"""Stage 5 item 2: with a dense embedder, recall fuses the dense ranking
(one matrix product) and BM25 over words by reciprocal rank. Measured with
the real local model on 500 records (2026-09-19): paraphrased facts in the
top 3, hashing 0/10, dense+BM25 10/10, p50 13 ms. This test uses a stand-in
model that encodes meaning by concept, so it runs without the dependency."""

import unittest

from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config
from simorgh.memory.embedders import Embedder
from simorgh.memory.recall import _words, fused
from simorgh.memory.store import MemoryEngine

CONCEPTS = {"kettle": 0, "boil": 0, "tea": 0, "plumber": 1, "pipe": 1, "boiler": 1, "heater": 1,
            "insurance": 2, "policy": 2, "car": 3, "auto": 3}


class _Meaning:
    def encode(self, text):
        if isinstance(text, list):
            return [self.encode(t) for t in text]
        vector = [0.0] * 5
        for word in text.lower().replace(".", " ").split():
            if word in CONCEPTS:
                vector[CONCEPTS[word]] += 1.0
        vector[4] = 0.05
        return vector


class _Clock:
    def now(self):
        return 1_790_000_000.0


class HybridRecall(unittest.IsolatedAsyncioTestCase):
    async def test_a_paraphrase_finds_its_record_among_500(self):
        ledger = make_ledger({"backend": "memory"})
        await ledger.start()
        embedder = Embedder("local", local_check=lambda: True, encoder=_Meaning())
        engine = MemoryEngine(ledger, Config(embedder="local", recency_weight=0.0), clock=_Clock(), embedder=embedder)
        for i in range(497):
            await engine.store(kind="episodic", content=f"asked about the weather again ({i})", tags=[], source_ref="",
                               confidence=1.0)
        for fact in ("The plumber said the water heater needs a new anode rod.",
                     "The car insurance renews in November.", "Put the kettle on."):
            await engine.store(kind="episodic", content=fact, tags=[], source_ref="", confidence=1.0)
        await engine.warm()
        found, _ = await engine.retrieve(query="what did the pipe guy say about the boiler", kinds=["episodic"], k=3,
                                         filters=None)
        self.assertIn("plumber", " ".join(item.content for item in found))
        exact, _ = await engine.retrieve(query="anode rod", kinds=["episodic"], k=1, filters=None)
        self.assertIn("anode", exact[0].content, "BM25 carries an exact rare word the model may not")


class Parts(unittest.TestCase):
    def test_stopwords_do_not_vote(self):
        self.assertEqual(_words("What did the pipe guy say about the boiler"), ["pipe", "guy", "say", "boiler"])

    def test_first_in_both_is_one_and_a_lexical_only_match_still_counts(self):
        scores = fused([0.9, 0.1, 0.5], {0: 3.0, 1: 5.0})
        self.assertAlmostEqual(scores[0], (1 / 61 + 1 / 62) / (2 / 61))
        self.assertGreater(scores[1], 0.0)
        self.assertLessEqual(max(scores), 1.0)


if __name__ == "__main__":
    unittest.main()
