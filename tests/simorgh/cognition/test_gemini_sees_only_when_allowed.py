"""Gemini looks at pictures, and only when this house allows it.

2026-09-29: the Router asked for a bare `supports_images` attribute, which
Gemini never had (it declares the capability in `capabilities`), and
Gemini's `complete` never took pictures at all -- so `look_at_image` in a
bench copy said "nothing here can look at a picture (tried: together,
gemini, floor)". Fixing only the Router would have sent camera stills of
the house to the cloud, so the pictures go only when `[cognition.providers.
gemini] images = true`."""

from __future__ import annotations

import asyncio
import tempfile
import types
import unittest
from pathlib import Path

from simorgh.cognition.api import ProviderUnavailable, capabilities_of
from simorgh.cognition.providers.gemini import GeminiProvider


class _Models:
    def __init__(self) -> None:
        self.contents = None

    def generate_content(self, *, model, contents, config=None):
        self.contents = contents
        return types.SimpleNamespace(text="a giant petrel and two chicks", usage_metadata=None, candidates=[])


def _gemini(images: bool) -> tuple[GeminiProvider, _Models]:
    models = _Models()
    return GeminiProvider(api_key="k", client=types.SimpleNamespace(models=models), images=images), models


class GeminiSeesOnlyWhenAllowed(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.png = Path(self._tmp.name) / "frame.png"
        self.png.write_bytes(b"\x89PNG fake")

    def test_off_by_default(self):
        gemini, models = _gemini(images=False)
        self.assertFalse(capabilities_of(gemini).supports_images)
        with self.assertRaises(ProviderUnavailable):
            asyncio.run(gemini.complete([{"role": "user", "content": "what is this?"}], tools=None,
                                        max_tokens=100, images=[str(self.png)]))
        self.assertIsNone(models.contents, "nothing was sent")

    def test_allowed_the_picture_travels_with_the_words(self):
        gemini, models = _gemini(images=True)
        self.assertTrue(capabilities_of(gemini).supports_images)
        reply = asyncio.run(gemini.complete([{"role": "user", "content": "what is this?"}], tools=None,
                                            max_tokens=100, images=[str(self.png)]))
        self.assertIn("petrel", reply.text)
        self.assertEqual(models.contents[0], "what is this?")
        self.assertEqual(models.contents[1], {"inline_data": {"mime_type": "image/png", "data": b"\x89PNG fake"}})

    def test_a_picture_that_cannot_be_read_is_refused_not_skipped(self):
        gemini, models = _gemini(images=True)
        with self.assertRaises(ProviderUnavailable):
            asyncio.run(gemini.complete([{"role": "user", "content": "?"}], tools=None, max_tokens=10,
                                        images=[str(self.png), "/nope/missing.png"]))
        self.assertIsNone(models.contents)

    def test_text_alone_is_unchanged(self):
        gemini, models = _gemini(images=False)
        asyncio.run(gemini.complete([{"role": "user", "content": "hi"}], tools=None, max_tokens=10))
        self.assertEqual(models.contents, "hi")


if __name__ == "__main__":
    unittest.main()
