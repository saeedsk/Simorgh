"""Pluggable embeddings (memory/embedders.py) and the guard in
`store.py::_similarity`.

No test here calls an embedding API: each injects an opener or an
encoder. What is pinned is the behaviour with NOTHING configured --
the state the code ships in -- and the two ways a better embedder could
quietly make recall worse instead of better.
"""

from __future__ import annotations

import json
import unittest

from simorgh.memory.embed import EMBED_DIM, cosine_similarity, embed_text
from simorgh.memory.embedders import (
    HASHING,
    Embedder,
    EmbeddingUnavailable,
    available_providers,
    choose_provider,
    comparable,
    dimension_of,
)

NO_LOCAL = {"local_check": lambda: False}


class _Response:
    def __init__(self, body):
        self._body = json.dumps(body).encode()

    def read(self, _n=None):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Opener:
    def __init__(self, body, raises=None):
        self.body, self.raises, self.calls = body, raises, []

    def __call__(self, request, timeout=None):
        self.calls.append(request)
        if self.raises:
            raise self.raises
        return _Response(self.body)


def _openai_body(dim=1536):
    return {"data": [{"embedding": [0.1] * dim}]}


class WhatHashingCannotDoTestCase(unittest.TestCase):
    """The motivating measurement, kept as a test so the claim in the
    docstrings stays true rather than becoming folklore."""

    def test_a_paraphrase_with_no_shared_words_scores_zero(self):
        score = cosine_similarity(
            embed_text("how do I stop the loop"),
            embed_text("halting a runaway iteration"),
        )
        self.assertEqual(score, 0.0)

    def test_shared_vocabulary_is_what_it_does_capture(self):
        score = cosine_similarity(embed_text("the car is fast"), embed_text("the car is slow"))
        self.assertGreater(score, 0.0)


class ChoosingTestCase(unittest.TestCase):
    def test_with_nothing_configured_it_still_works(self):
        # Memory must never be unable to embed: worse recall is a bad
        # day, no recall is a broken system.
        self.assertEqual(choose_provider("auto", {}, **NO_LOCAL), HASHING)

    def test_a_key_is_preferred_over_hashing(self):
        self.assertEqual(choose_provider("auto", {"OPENAI_API_KEY": "k"}, **NO_LOCAL), "openai")

    def test_a_local_model_is_used_when_installed_and_needs_no_key(self):
        self.assertEqual(choose_provider("auto", {}, local_check=lambda: True), "local")

    def test_gemini_accepts_either_of_its_two_variable_names(self):
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            with self.subTest(variable=name):
                self.assertIn("gemini", available_providers({name: "k"}, **NO_LOCAL))

    def test_a_blank_key_does_not_count(self):
        self.assertEqual(choose_provider("auto", {"OPENAI_API_KEY": "  "}, **NO_LOCAL), HASHING)

    def test_a_named_provider_without_its_key_is_reported(self):
        with self.assertRaises(EmbeddingUnavailable) as caught:
            choose_provider("openai", {}, **NO_LOCAL)
        self.assertIn("OPENAI_API_KEY", str(caught.exception))

    def test_an_unknown_name_lists_the_real_ones(self):
        with self.assertRaises(EmbeddingUnavailable) as caught:
            choose_provider("word2vec", {}, **NO_LOCAL)
        self.assertIn("hashing", str(caught.exception))

    def test_a_misconfigured_embedder_degrades_rather_than_raising(self):
        embedder = Embedder("openai", env={}, **NO_LOCAL)
        self.assertEqual(embedder.provider, HASHING)
        self.assertIn("OPENAI_API_KEY", embedder.degraded)


class EmbeddingTestCase(unittest.TestCase):
    def test_hashing_returns_its_own_name_and_dimension(self):
        provider, vector = Embedder("auto", env={}, **NO_LOCAL).embed("hello")
        self.assertEqual(provider, HASHING)
        self.assertEqual(len(vector), EMBED_DIM)

    def test_a_real_provider_is_called_and_its_vector_normalised(self):
        opener = _Opener(_openai_body())
        provider, vector = Embedder(
            "auto", env={"OPENAI_API_KEY": "k"}, opener=opener, **NO_LOCAL).embed("hello")
        self.assertEqual(provider, "openai")
        self.assertEqual(len(vector), 1536)
        self.assertAlmostEqual(sum(c * c for c in vector), 1.0, places=6)

    def test_the_api_key_travels_in_a_header_never_the_url(self):
        opener = _Opener(_openai_body())
        Embedder("auto", env={"OPENAI_API_KEY": "sk-secret"}, opener=opener, **NO_LOCAL).embed("hi")
        request = opener.calls[0]
        self.assertNotIn("sk-secret", request.full_url)
        self.assertIn("sk-secret", json.dumps(dict(request.headers)))

    def test_gemini_puts_its_key_in_a_header_too(self):
        opener = _Opener({"embedding": {"values": [0.5] * 768}})
        provider, vector = Embedder(
            "auto", env={"GEMINI_API_KEY": "g-secret"}, opener=opener, **NO_LOCAL).embed("hi")
        self.assertEqual(provider, "gemini")
        self.assertNotIn("g-secret", opener.calls[0].full_url)

    def test_a_provider_failure_falls_back_instead_of_raising(self):
        embedder = Embedder("auto", env={"OPENAI_API_KEY": "k"},
                            opener=_Opener(None, raises=OSError("down")), **NO_LOCAL)
        provider, vector = embedder.embed("hello")
        self.assertEqual(provider, HASHING)
        self.assertEqual(len(vector), EMBED_DIM)

    def test_an_empty_vector_from_a_provider_is_a_failure_not_an_answer(self):
        embedder = Embedder("auto", env={"OPENAI_API_KEY": "k"},
                            opener=_Opener({"data": [{"embedding": []}]}), **NO_LOCAL)
        self.assertEqual(embedder.embed("hello")[0], HASHING)

    def test_repeated_text_is_embedded_once(self):
        # One `retrieve` embeds every candidate's content; without a
        # cache a paid provider would be billed for the whole store on
        # every query.
        opener = _Opener(_openai_body())
        embedder = Embedder("auto", env={"OPENAI_API_KEY": "k"}, opener=opener, **NO_LOCAL)
        for _ in range(5):
            embedder.embed("the same text")
        self.assertEqual(len(opener.calls), 1)

    def test_a_local_encoder_is_used_when_given(self):
        embedder = Embedder("local", env={}, encoder=_FakeEncoder(), local_check=lambda: True)
        provider, vector = embedder.embed("hello")
        self.assertEqual(provider, "local")
        self.assertEqual(len(vector), 384)


class _FakeEncoder:
    def encode(self, text):
        return [0.2] * 384


class ComparabilityTestCase(unittest.TestCase):
    def test_vectors_from_different_embedders_are_not_comparable(self):
        self.assertFalse(comparable(HASHING, "openai"))
        self.assertFalse(comparable("", "openai"))

    def test_vectors_from_the_same_embedder_are(self):
        self.assertTrue(comparable("openai", "openai"))

    def test_every_provider_declares_a_dimension(self):
        from simorgh.memory.embedders import PROVIDERS

        for name, _keys, _model, dim in PROVIDERS:
            with self.subTest(provider=name):
                self.assertGreater(dim, 0)
                self.assertEqual(dimension_of(name), dim)


class MixedProviderRecallTestCase(unittest.IsolatedAsyncioTestCase):
    """The trap: a provider may fail ONE call and fall back. Within a
    single retrieve the query can then be a 1536-dim vector while an
    item's content is a 256-dim hashed one -- and `zip()` compares them
    happily over the first 256 components, returning a number that means
    nothing. Silently wrong recall, not an error."""

    class _FlakyEmbedder:
        """Real vectors for the query, hashing for everything after."""

        def __init__(self):
            self.calls = 0

        def embed(self, text):
            self.calls += 1
            if self.calls == 1:
                return "openai", tuple([0.1] * 1536)
            return HASHING, embed_text(text)

    async def _engine(self, embedder):
        from simorgh.ledger.factory import make_ledger
        from simorgh.memory.config import Config
        from simorgh.memory.store import MemoryEngine
        from tests.simorgh.helpers import FakeClock

        clock = FakeClock()
        ledger = make_ledger({"backend": "memory"}, clock=clock)
        await ledger.start()
        return MemoryEngine(ledger, Config(recency_weight=0.0), clock=clock, embedder=embedder)

    async def test_a_mid_retrieval_fallback_does_not_produce_nonsense_scores(self):
        engine = await self._engine(self._FlakyEmbedder())
        await engine.store(kind="semantic", content="halting a runaway iteration",
                           tags=["x"], source_ref="", confidence=1.0)
        await engine.store(kind="semantic", content="the price of tea in china",
                           tags=["x"], source_ref="", confidence=1.0)
        items, _ = await engine.retrieve(
            query="halting a runaway iteration", kinds=["semantic"], k=2, filters=None)
        # Both sides fall back to hashing, so the exact-match item wins.
        # Compared across dimensions, the two scores would be identical
        # (the query vector is constant) and the order arbitrary.
        self.assertEqual(items[0].content, "halting a runaway iteration")


    async def test_the_guard_restores_a_correct_ordering(self):
        """Measured 2026-09-09, comparing a 1536-dim query vector with
        256-dim hashed content across the truncation `zip` performs:

            exact match -> 0.2000
            unrelated   -> 0.2449   <-- ranks HIGHER

        The ordering inverts. That is the failure being prevented: not
        an exception, just the wrong memory recalled. Re-embedding both
        sides with hashing gives 1.0 and 0.0.
        """
        class _AlwaysHashing:
            def embed(self, text):
                return HASHING, embed_text(text)

        engine = await self._engine(_AlwaysHashing())
        # A query embedded by a provider that then became unavailable.
        pair = ("openai", tuple([0.1] * 1536), "halting a runaway iteration")
        self.assertAlmostEqual(engine._similarity(pair, "halting a runaway iteration"), 1.0)
        self.assertAlmostEqual(engine._similarity(pair, "the price of tea in china"), 0.0)

    async def test_similarity_stays_bounded(self):
        class _AlwaysHashing:
            def embed(self, text):
                return HASHING, embed_text(text)

        engine = await self._engine(_AlwaysHashing())
        pair = ("openai", tuple([0.1] * 1536), "anything at all")
        for content in ("anything at all", "something else", ""):
            with self.subTest(content=content):
                # 1e-9 of slack: a normalised cosine lands on
                # 1.0000000000000002 for an exact match, which is
                # floating point, not an unbounded score.
                self.assertLessEqual(engine._similarity(pair, content), 1.0 + 1e-9)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
