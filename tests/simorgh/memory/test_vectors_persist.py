"""Stage 5 item 1: a local embedder warms in a thread while recall answers
from hashing; each record's dense vector is computed once and persisted,
so a restart embeds nothing twice."""

import asyncio
import unittest

from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config
from simorgh.memory.embedders import Embedder
from simorgh.memory.recall import VECTOR_STREAM, decode_vector, encode_vector
from simorgh.memory.store import MemoryEngine


class _Clock:
    def now(self):
        return 1_790_000_000.0


class _Encoder:
    """A stand-in model: 4 dims keyed on a few words, counting its calls."""

    calls = 0
    loaded = False

    def encode(self, text):
        _Encoder.calls += 1
        if isinstance(text, list):
            return [self.encode(t) for t in text]
        words = text.lower()
        return [float("kettle" in words or "boil" in words), float("light" in words or "lamp" in words),
                float("warm" in words), 0.1]


def _local(encoder=None):
    embedder = Embedder("local", local_check=lambda: True)
    if encoder is not None:
        embedder._encoder = encoder  # noqa: SLF001 -- loaded, but not yet declared warm
    return embedder


class VectorsPersist(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ledger = make_ledger({"backend": "memory"})
        await self.ledger.start()

    async def test_recall_answers_before_warm_then_upgrades_and_persists(self):
        engine = MemoryEngine(self.ledger, Config(embedder="local"), clock=_Clock(), embedder=_local(_Encoder()))
        await engine.store(kind="episodic", content="put the kettle on to boil", tags=[], source_ref="", confidence=1.0)
        await engine.store(kind="episodic", content="the lamp in the hall", tags=[], source_ref="", confidence=1.0)
        await engine.warm()
        self.assertFalse(engine._embedder.ready)  # noqa: SLF001
        before, _ = await engine.retrieve(query="kettle", kinds=["episodic"], k=2, filters=None)
        self.assertTrue(before, "recall answers from hashing before the model is warm")
        self.assertEqual(await self.ledger.read(VECTOR_STREAM), [], "nothing hashed is persisted")

        await engine.warm_embedder()
        persisted = await self.ledger.read(VECTOR_STREAM)
        self.assertEqual(len(persisted), 2)
        self.assertEqual({e.payload["provider"] for e in persisted}, {"local"})

        # A restart: a new engine over the same ledger embeds nothing.
        _Encoder.calls = 0
        again = MemoryEngine(self.ledger, Config(embedder="local"), clock=_Clock(), embedder=_local(_Encoder()))
        again._embedder.ready = True  # noqa: SLF001 -- as if warm
        await again.warm()
        self.assertEqual(_Encoder.calls, 0, "persisted vectors are read, not recomputed")
        found, _ = await again.retrieve(query="boil water in the kettle", kinds=["episodic"], k=1, filters=None)
        self.assertIn("kettle", found[0].content)

    async def test_a_record_stored_after_warm_is_persisted_once(self):
        engine = MemoryEngine(self.ledger, Config(embedder="local"), clock=_Clock(), embedder=_local(_Encoder()))
        engine._embedder.ready = True  # noqa: SLF001
        await engine.warm()
        await engine.store(kind="episodic", content="warm light in the lamp", tags=[], source_ref="", confidence=1.0)
        await engine.retrieve(query="lamp", kinds=["episodic"], k=1, filters=None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(len(await self.ledger.read(VECTOR_STREAM)), 1)

    def test_a_vector_round_trips_through_its_text(self):
        vector = decode_vector(encode_vector([0.5, -0.25, 1.0]))
        self.assertEqual(list(vector), [0.5, -0.25, 1.0])
        self.assertIsNone(decode_vector("not base64!"))
        self.assertLess(len(encode_vector([0.1] * 384)), 4096, "fits the Ledger's inline limit")


if __name__ == "__main__":
    unittest.main()
