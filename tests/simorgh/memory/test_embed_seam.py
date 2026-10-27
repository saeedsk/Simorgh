"""`memory.embed` (stage 17): Memory lends its configured embedder over the
bus, so the tool router never loads a second model. Answered with the
embedder's model and dimension; refused, with no vectors, when that
embedder is the hashing floor, a model still loading, a mixed batch or too
many texts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.messages.memory import EMBED_MAX_CHARS, EMBED_MAX_TEXTS
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config as MemoryConfig
from simorgh.memory.embedders import Embedder
from simorgh.memory.service import Service
from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class _Encoder:
    """A 384-wide stand-in for the local model: one call per batch."""

    def __init__(self) -> None:
        self.calls: list = []

    def encode(self, text):
        self.calls.append(text)
        if isinstance(text, list):
            return [self._one(t) for t in text]
        return self._one(text)

    @staticmethod
    def _one(text: str) -> list[float]:
        vec = [0.0] * 384
        vec[len(text) % 384] = 3.0
        vec[(len(text) * 7) % 384] += 4.0
        return vec


class EmbedSeamTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=clock)
        self.bus = make_client(backend, source="memory", ledger=self.ledger, clock=clock)
        await self.bus.start()
        ctx = Context(name="memory", instance_id="", run_id="test", mode="single", bus=self.bus,
                      ledger=self.ledger, config={}, secrets={}, clock=clock, logger=_Logger(),
                      data_dir=Path(self._tmp.name) / "data")
        self.service = Service(config=MemoryConfig(embedder="hashing"))
        await self.service.start(ctx)

    async def asyncTearDown(self):
        await self.service.stop()
        await self.bus.stop()
        self._tmp.cleanup()

    async def _embed(self, texts) -> dict:
        reply = await self.bus.request(
            Message.new(topics.MEMORY_EMBED, source="orchestration", payload={"texts": list(texts)}), timeout=5.0)
        self.assertEqual(reply.type, topics.MEMORY_EMBED_REPLY)
        return reply.payload

    def _local(self) -> _Encoder:
        encoder = _Encoder()
        self.service.engine._embedder = Embedder("local", env={}, encoder=encoder, local_check=lambda: True)  # noqa: SLF001
        return encoder

    async def test_answers_with_the_configured_model_and_its_dimension(self):
        encoder = self._local()
        payload = await self._embed(["turn the kitchen light off", "what's on today"])
        self.assertNotIn("refused", payload)
        self.assertEqual(payload["model"], "local")
        self.assertEqual(payload["dimension"], 384)
        self.assertEqual(len(payload["vectors"]), 2)
        for vector in payload["vectors"]:
            self.assertEqual(len(vector), 384)
            self.assertAlmostEqual(sum(x * x for x in vector), 1.0, places=6)
        self.assertEqual(len(encoder.calls), 1, "one batched model call, not one per text")

    async def test_a_long_text_is_cut(self):
        encoder = self._local()
        await self._embed(["x" * (EMBED_MAX_CHARS + 500)])
        self.assertEqual(len(encoder.calls[0][0]), EMBED_MAX_CHARS)

    async def test_the_hashing_floor_is_refused(self):
        payload = await self._embed(["hello"])
        self.assertEqual(payload["model"], "hashing")
        self.assertEqual(payload["vectors"], [])
        self.assertIn("hashing", payload["refused"])

    async def test_too_many_texts_are_refused(self):
        encoder = self._local()
        payload = await self._embed(["t"] * (EMBED_MAX_TEXTS + 1))
        self.assertEqual(payload["vectors"], [])
        self.assertIn(str(EMBED_MAX_TEXTS), payload["refused"])
        self.assertEqual(encoder.calls, [])

    async def test_a_model_still_loading_is_refused(self):
        self._local()
        self.service.engine.embedder.ready = False
        payload = await self._embed(["hello"])
        self.assertEqual(payload["vectors"], [])
        self.assertIn("loading", payload["refused"])

    async def test_a_mixed_batch_is_refused(self):
        class _Half:
            provider = "openai"
            ready = True
            degraded = ""

            def dimension(self):
                return 1536

            def embed_many(self, texts):
                return [("openai", (1.0,) + (0.0,) * 1535), ("hashing", (1.0,) + (0.0,) * 255)][:len(texts)]

        self.service.engine._embedder = _Half()  # noqa: SLF001
        payload = await self._embed(["a", "b"])
        self.assertEqual(payload["vectors"], [])
        self.assertIn("fell back", payload["refused"])

    async def test_an_empty_text_is_refused(self):
        self._local()
        payload = await self._embed(["hello", "  "])
        self.assertEqual(payload["vectors"], [])
        self.assertIn("empty", payload["refused"])


if __name__ == "__main__":
    unittest.main()
