"""Shenava hears the turns already known to be Farsi; large-v3 still
settles "Farsi or English?".

Measured 2026-09-29 on 12 of the creator's Farsi turns: Shenava 1.1 s for
all twelve, large-v3 24.3 s, and Shenava at least as right."""

from __future__ import annotations

import unittest

from simorgh.voice.api import Audio, Utterance
from simorgh.voice.config import Config
from simorgh.voice.stt.whisper_server import WhisperServerRecogniser


def _engine(name: str, asked: list):
    class _Engine:
        last_logprob = -0.2 if name == "large-v3" else None

        async def transcribe(self, audio, *, language="", route=True):
            asked.append(name)
            return Utterance(text=f"{name} heard it", confidence=1.0, seconds=audio.seconds,
                             engine=name, language="fa")
    return _Engine()


class ShenavaHearsKnownFarsi(unittest.IsolatedAsyncioTestCase):
    def _recogniser(self):
        rec = WhisperServerRecogniser.__new__(WhisperServerRecogniser)
        asked: list = []
        rec._farsi = _engine("large-v3", asked)          # noqa: SLF001
        rec._farsi_fast = _engine("shenava", asked)      # noqa: SLF001
        rec._conversation = ("", 0.0)                    # noqa: SLF001
        return rec, asked

    async def test_a_turn_asked_in_farsi_goes_to_shenava(self):
        rec, asked = self._recogniser()
        got = await rec.transcribe(Audio(b"\x00\x00" * 16000), language="fa")
        self.assertEqual((got.engine, asked), ("shenava", ["shenava"]))

    async def test_a_farsi_conversation_goes_to_shenava(self):
        rec, asked = self._recogniser()
        rec.conversing_in("fa")
        got = await rec.transcribe(Audio(b"\x00\x00" * 16000))
        self.assertEqual((got.engine, asked), ("shenava", ["shenava"]))

    async def test_comparing_languages_keeps_large_v3(self):
        rec, asked = self._recogniser()
        rec._comparing = True                             # noqa: SLF001
        got = await rec.transcribe(Audio(b"\x00\x00" * 16000), language="fa")
        self.assertEqual((got.engine, asked), ("large-v3", ["large-v3"]))

    async def test_without_shenava_large_v3_as_before(self):
        rec, asked = self._recogniser()
        rec._farsi_fast = None                            # noqa: SLF001
        got = await rec.transcribe(Audio(b"\x00\x00" * 16000), language="fa")
        self.assertEqual(got.engine, "large-v3")

    def test_the_default_names_the_model_folder(self):
        self.assertEqual(Config().stt_farsi_fast, "workspace/voice/models/shenava-koochik")


if __name__ == "__main__":
    unittest.main()
