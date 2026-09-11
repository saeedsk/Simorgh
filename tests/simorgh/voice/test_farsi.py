"""Sim speaks Farsi (2026-09-11): a reply in the Arabic script is
routed to Piper's Persian voice instead of being read by Kokoro as
English gibberish. Script detection, the per-language router with
fakes, the Piper adapter's refusals, and -- when piper and its voice
are installed -- one real synthesis."""

from __future__ import annotations

import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.api import Audio
from simorgh.voice.config import Config
from simorgh.voice.fakes import FakeSynthesiser
from simorgh.voice.lang import ENGLISH, FARSI, language_of
from simorgh.voice.tts import PolyglotSynthesiser, open_synthesiser
from simorgh.voice.tts.piper import PIPER_VOICES, PiperSynthesiser, voice_urls

FA = "سلام، من سیمرغ هستم. حال شما چطور است؟"
EN = "Hello, I am Simorgh. How are you?"


class TestLanguageOf(unittest.TestCase):
    def test_persian_is_fa(self) -> None:
        self.assertEqual(language_of(FA), FARSI)

    def test_english_is_en(self) -> None:
        self.assertEqual(language_of(EN), ENGLISH)

    def test_empty_and_punctuation_are_en(self) -> None:
        self.assertEqual(language_of(""), ENGLISH)
        self.assertEqual(language_of("123 ... !?"), ENGLISH)

    def test_a_persian_word_quoted_in_english_stays_en(self) -> None:
        self.assertEqual(language_of('The word for hello is "سلام" in Farsi.'), ENGLISH)

    def test_mostly_persian_with_a_latin_name_is_fa(self) -> None:
        self.assertEqual(language_of("من Simorgh هستم و به شما کمک می‌کنم"), FARSI)

    def test_the_four_persian_only_letters_count(self) -> None:
        self.assertEqual(language_of("پ چ ژ گ"), FARSI)


class _NamedFake(FakeSynthesiser):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name


class TestPolyglotRouting(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.primary = _NamedFake("kokoro")
        self.farsi = _NamedFake("piper")
        self.config = Config(tts="fake")

    def _router(self, openers: dict | None = None) -> PolyglotSynthesiser:
        return PolyglotSynthesiser(self.primary, self.config,
                                   openers={FARSI: lambda cfg: self.farsi} if openers is None else openers)

    async def test_farsi_goes_to_the_farsi_engine_and_english_to_the_primary(self) -> None:
        router = self._router()
        await router.synthesise(FA, voice="af_jessica")
        self.assertEqual(self.farsi.spoken, [FA])
        self.assertEqual(self.primary.spoken, [])
        self.assertEqual(router.last_engine, "piper")
        await router.synthesise(EN, voice="af_jessica")
        self.assertEqual(self.primary.spoken, [EN])
        self.assertEqual(router.last_engine, "kokoro")
        self.assertEqual(router.name, "kokoro")

    async def test_the_farsi_engine_is_opened_once(self) -> None:
        opened = []

        def opener(cfg):
            opened.append(cfg)
            return self.farsi

        router = self._router({FARSI: opener})
        await router.synthesise(FA)
        await router.synthesise(FA)
        self.assertEqual(len(opened), 1)

    async def test_a_language_with_no_engine_is_excused_aloud_in_the_primary_voice(self) -> None:
        def opener(cfg):
            raise ImportError("piper voice 'fa_IR-amir-medium' not found under workspace/voice/models")

        router = self._router({FARSI: opener})
        await router.synthesise(FA)
        self.assertEqual(self.farsi.spoken, [])
        self.assertEqual(len(self.primary.spoken), 1)
        self.assertIn("I cannot speak Farsi yet", self.primary.spoken[0])
        self.assertIn("not found", self.primary.spoken[0])
        self.assertIn(FARSI, router.problems)

    async def test_voices_lists_every_opened_engine(self) -> None:
        router = self._router()
        await router.synthesise(FA)
        self.assertEqual(router.voices(), ["fake", "fake"])

    def test_open_synthesiser_wraps_the_primary_unless_told_not_to(self) -> None:
        # `fake` is the primary here; the router is what wraps it in
        # production (`auto`), and off means the one engine as before.
        primary, _ = open_synthesiser(Config(tts="fake"))
        self.assertIsInstance(primary, FakeSynthesiser)
        self.assertIn("piper", str(open_synthesiser(Config(tts="nope"))[1]))


class TestPiperAdapter(unittest.TestCase):
    def test_voice_urls_follow_the_huggingface_layout(self) -> None:
        files = dict(voice_urls("fa_IR-amir-medium"))
        self.assertEqual(set(files), {"fa_IR-amir-medium.onnx", "fa_IR-amir-medium.onnx.json"})
        self.assertIn("/fa/fa_IR/amir/medium/fa_IR-amir-medium.onnx", files["fa_IR-amir-medium.onnx"])

    def test_the_farsi_voice_is_in_the_table(self) -> None:
        self.assertEqual(PIPER_VOICES[FARSI], "fa_IR-amir-medium")

    def test_a_missing_voice_is_refused_by_name(self) -> None:
        if importlib.util.find_spec("piper") is None:
            with self.assertRaises(ImportError) as caught:
                PiperSynthesiser(Config(model_dir="/nonexistent"))
            self.assertIn("piper-tts", str(caught.exception))
            return
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ImportError) as caught:
                PiperSynthesiser(Config(model_dir=tmp))
        self.assertIn("fa_IR-amir-medium", str(caught.exception))
        self.assertIn("voice models piper-fa", str(caught.exception))


@unittest.skipUnless(
    importlib.util.find_spec("piper") is not None
    and Path("workspace/voice/models/fa_IR-amir-medium.onnx").is_file(),
    "piper-tts and the Persian voice are not installed here",
)
class TestRealPiper(unittest.TestCase):
    def test_a_farsi_sentence_becomes_real_audio(self) -> None:
        engine = PiperSynthesiser(Config())
        audio: Audio = asyncio.run(engine.synthesise(FA))
        self.assertGreater(audio.seconds, 1.5)
        self.assertEqual(audio.sample_rate, 22050)
        samples = memoryview(audio.pcm).cast("h")
        self.assertGreater(max(abs(s) for s in samples), 2000)  # not silence
        self.assertEqual(engine.voices(), ["fa_IR-amir-medium"])


if __name__ == "__main__":
    unittest.main()
