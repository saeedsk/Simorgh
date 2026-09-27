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

    async def test_the_likelier_house_language_by_whispers_own_odds(self):
        """"Stop the music." heard as Icelandic: English is the likelier of
        the house's two, so it is tried first -- not forced into Farsi."""
        rec = WhisperServerRecogniser.__new__(WhisperServerRecogniser)
        rec._house = ("en", "fa")                          # noqa: SLF001
        asked = []

        async def transcribe(audio, *, language=""):
            asked.append(language)
            return Utterance(text={"en": "Stop the music.", "fa": "استاپ د میوزیک"}[language], confidence=1.0,
                             seconds=audio.seconds, engine="w", language=language)

        rec.transcribe = transcribe
        got = await WhisperServerRecogniser._in_a_house_language(
            rec, Audio(b"\x00\x00" * 16000), "is", probabilities={"is": 0.4, "en": 0.3, "fa": 0.01})
        self.assertEqual((got.text, asked), ("Stop the music.", ["en"]))

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


class ForcedEnglishThatIsNotEnglish(unittest.IsolatedAsyncioTestCase):
    """Live, 2026-09-27: a Farsi turn heard as Czech, English the likelier
    by whisper's odds, and forced English wrote "A da se demanem již
    neví." -- accepted, so Farsi never got its turn."""

    async def test_farsi_gets_its_turn(self):
        rec = WhisperServerRecogniser.__new__(WhisperServerRecogniser)
        rec._house = ("en", "fa")                          # noqa: SLF001
        asked = []

        async def transcribe(audio, *, language=""):
            asked.append(language)
            return Utterance(text={"en": "A da se demanem již neví.", "fa": "آره، دیگه نمی‌دونم."}[language],
                             confidence=1.0, seconds=audio.seconds, engine="w", language=language)

        rec.transcribe = transcribe
        got = await WhisperServerRecogniser._in_a_house_language(
            rec, Audio(b"\x00\x00" * 16000), "cs", probabilities={"cs": 0.5, "en": 0.2, "fa": 0.05})
        self.assertEqual((got.text, asked), ("آره، دیگه نمی‌دونم.", ["en", "fa"]))

    def test_what_counts_as_english_letters(self):
        from simorgh.voice.stt.whisper_server import _english_letters

        self.assertTrue(_english_letters("Stop the music."))
        self.assertFalse(_english_letters("A da se demanem již neví."))
        self.assertFalse(_english_letters("سلام"))
        self.assertTrue(_english_letters("A café, please.", allow=1))


class FarsiGoesToTheFarsiModel(unittest.IsolatedAsyncioTestCase):
    """Measured on 18 Farsi satellite takes, 2026-09-27: large-v3 got most
    right that large-v3-turbo turned to nonsense. A Farsi turn goes to the
    Farsi model; a draft never does."""

    def _recogniser(self):
        rec = WhisperServerRecogniser.__new__(WhisperServerRecogniser)
        asked = []

        class _Farsi:
            async def transcribe(self, audio, *, language=""):
                asked.append(language)
                return Utterance(text="الان صدای منو میشنوی؟", confidence=1.0, seconds=audio.seconds,
                                 engine="whisper_server:large-v3", language="fa")

        rec._farsi = _Farsi()                                  # noqa: SLF001
        return rec, asked

    async def test_a_turn_asked_in_farsi_goes_to_the_farsi_model(self):
        rec, asked = self._recogniser()
        got = await rec.transcribe(Audio(b"\\x00\\x00" * 16000), language="fa")
        self.assertEqual((got.text, got.engine, asked), ("الان صدای منو میشنوی؟", "whisper_server:large-v3", ["fa"]))

    async def test_a_farsi_conversation_sends_every_turn_to_the_farsi_model(self):
        """Live 2026-09-27: turbo labelled the creator's Farsi as English
        ("Sustu Farsi? Only speak Farsi."); no retry ever ran."""
        rec, asked = self._recogniser()
        rec._conversation = ("", 0.0)                          # noqa: SLF001
        rec.conversing_in("fa")
        got = await rec.transcribe(Audio(b"\x00\x00" * 16000))
        self.assertEqual((got.text, asked), ("الان صدای منو میشنوی؟", [""]))

    async def test_not_after_an_english_answer_or_a_long_pause(self):
        from unittest import mock

        from simorgh.voice.stt import whisper_server as ws

        rec, _ = self._recogniser()
        rec.conversing_in("en")
        self.assertFalse(rec._in_a_farsi_conversation())       # noqa: SLF001
        rec.conversing_in("fa")
        with mock.patch.object(ws.time, "monotonic", return_value=ws.time.monotonic() + ws.CONVERSATION_LANGUAGE_S + 1):
            self.assertFalse(rec._in_a_farsi_conversation())   # noqa: SLF001

    def test_the_setting_defaults_to_large_v3(self):
        from simorgh.contracts.settings import VOICE_SAFE_KEYS
        from simorgh.voice.config import Config

        self.assertEqual(Config().stt_model_farsi, "large-v3")
        self.assertIn("stt_model_farsi", VOICE_SAFE_KEYS)

    def test_a_draft_takes_the_quick_pass(self):
        import inspect

        self.assertIn("route=False", inspect.getsource(WhisperServerRecogniser.draft))
