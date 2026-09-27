"""A turn whisper hears as a language the house does not speak is
transcribed again in one it does.

Live, 2026-09-27: the creator's Farsi came back as Turkish-looking Latin
("Emris Şeruziye") and Sim could not understand it; earlier "Stop the
music." was labelled Icelandic.
"""

from __future__ import annotations

import unittest

from simorgh.voice.api import Audio, Utterance
from simorgh.voice.stt.whisper_server import WhisperServerRecogniser


class TheHouseLanguagesWin(unittest.IsolatedAsyncioTestCase):
    def _recogniser(self, answers):
        rec = WhisperServerRecogniser.__new__(WhisperServerRecogniser)
        rec._house = ("en", "fa")                          # noqa: SLF001
        asked = []
        real = WhisperServerRecogniser._in_a_house_language

        async def transcribe(audio, *, language=""):
            asked.append(language)
            text, lang = answers[language]
            if not language:
                got = Utterance(text=text, confidence=1.0, seconds=audio.seconds, engine="w", language=lang)
                again = await real(rec, audio, lang) if text else None
                return again or got
            return Utterance(text=text, confidence=1.0, seconds=audio.seconds, engine="w", language=lang)

        rec.transcribe = transcribe
        return rec, asked

    async def test_turkish_is_heard_again_as_farsi_first(self):
        rec, asked = self._recogniser({"": ("Emris Şeruziye", "tr"), "fa": ("امروز چه روزیه", "fa"),
                                       "en": ("Emris", "en")})
        got = await rec.transcribe(Audio(b"\x00\x00" * 16000))
        self.assertEqual((got.text, asked), ("امروز چه روزیه", ["", "fa"]))

    async def test_a_house_language_is_left_alone(self):
        rec, asked = self._recogniser({"": ("Stop the music.", "en")})
        got = await rec.transcribe(Audio(b"\x00\x00" * 16000))
        self.assertEqual((got.text, asked), ("Stop the music.", [""]))

    async def test_english_when_farsi_gives_nothing(self):
        rec, asked = self._recogniser({"": ("Stoppa tónlistina.", "is"), "fa": ("", "fa"),
                                       "en": ("Stop the music.", "en")})
        got = await rec.transcribe(Audio(b"\x00\x00" * 16000))
        self.assertEqual((got.text, asked), ("Stop the music.", ["", "fa", "en"]))


class NoEnglishPromptOnFarsi(unittest.TestCase):
    """Measured 2026-09-27 on a kept satellite take: forced Farsi with the
    English prompt gave "سَدَيْمَنْ مِشْنَا بِي", without it "سلام آمیشنی بیدی."."""

    def test_the_prompt_is_for_english_and_auto_only(self):
        from simorgh.voice.stt.whisper_server import _not_english

        self.assertTrue(_not_english("fa"))
        self.assertTrue(_not_english("persian"))
        for language in ("", "auto", "en", "English"):
            self.assertFalse(_not_english(language), language)
