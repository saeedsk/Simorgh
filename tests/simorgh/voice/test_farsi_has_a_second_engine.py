"""Farsi can be spoken by Pocket, Piper or MMS, and naming one means it.

The creator, 2026-09-22: "i don't like the farsi voice model, what are
my options?". Piper's five Persian voices are all VITS-medium and share
a family resemblance; MMS (`facebook/mms-tts-fas`) is a different model
on different data -- a real alternative rather than another take on the
same one, at 16 kHz against Piper's 22.05 kHz.

What matters here is the ROUTING, which is testable without either
model on disk: "auto" prefers Piper and falls back, and naming an
engine means it or nothing -- a person who asked for MMS and silently
got Piper would conclude MMS sounds exactly like Piper.
"""

from __future__ import annotations

import dataclasses
import unittest
from unittest import mock

from simorgh.voice import tts as tts_mod
from simorgh.voice.config import Config


class _Pocket:
    def __init__(self, config):
        pass


class _Piper:
    def __init__(self, config, voice=""):
        self.voice = voice


class _Mms:
    def __init__(self, config, model_id=""):
        self.model_id = model_id


class _Refuses:
    def __init__(self, *a, **kw):
        raise ImportError("piper-tts is not installed")


def _config(**kw) -> Config:
    return dataclasses.replace(Config(model_dir="/nowhere"), **kw)


class ChoosingAFarsiEngine(unittest.TestCase):
    def _open(self, config, *, pocket=_Pocket, piper=_Piper, mms=_Mms):
        """Every engine faked: which one `auto` picks must not depend on
        what happens to be installed on the machine running the test."""
        with mock.patch("simorgh.voice.tts.pocket.PocketSynthesiser", pocket), \
             mock.patch("simorgh.voice.tts.piper.PiperSynthesiser", piper), \
             mock.patch("simorgh.voice.tts.mms.MmsSynthesiser", mms):
            return tts_mod._farsi_synthesiser(config)      # noqa: SLF001

    def test_auto_prefers_the_one_the_creator_chose(self):
        """2026-09-22, having heard all three: "I like
        pocket-farsi-v2.wav, make it as default farsi tts voice and
        model"."""
        self.assertIsInstance(self._open(_config(tts_farsi="auto")), _Pocket)

    def test_auto_falls_back_to_piper_when_pocket_is_not_installed(self):
        """Pocket needs a venv, a 438 MB model and a reference clip. A
        house whose Farsi has gone SILENT because a download did not
        happen is worse than one whose Farsi sounds like Piper."""
        engine = self._open(_config(tts_farsi="auto"), pocket=_Refuses)
        self.assertIsInstance(engine, _Piper)
        self.assertEqual(engine.voice, "fa_IR-amir-medium")

    def test_auto_falls_back_again_to_mms(self):
        engine = self._open(_config(tts_farsi="auto"), pocket=_Refuses, piper=_Refuses)
        self.assertIsInstance(engine, _Mms)

    def test_naming_pocket_means_pocket(self):
        self.assertIsInstance(self._open(_config(tts_farsi="pocket")), _Pocket)

    def test_naming_mms_means_mms(self):
        engine = self._open(_config(tts_farsi="mms"))
        self.assertIsInstance(engine, _Mms)
        self.assertEqual(engine.model_id, "facebook/mms-tts-fas")

    def test_naming_piper_means_piper_even_when_it_refuses(self):
        """Silently swapping the engine somebody chose is how a person
        concludes that both engines sound the same."""
        with self.assertRaises(ImportError):
            self._open(_config(tts_farsi="piper"), piper=_Refuses)

    def test_a_chosen_piper_voice_is_the_one_opened(self):
        engine = self._open(_config(tts_farsi="piper", tts_farsi_voice="fa_IR-ganji-medium"))
        self.assertEqual(engine.voice, "fa_IR-ganji-medium")


class TheMmsEngineIsOptional(unittest.TestCase):
    def test_it_refuses_by_name_without_its_model(self):
        """Every engine here refuses by name rather than failing at the
        first spoken word."""
        from simorgh.voice.tts.mms import MmsSynthesiser

        with mock.patch("transformers.VitsModel.from_pretrained", side_effect=OSError("not cached")):
            with self.assertRaises(ImportError) as caught:
                MmsSynthesiser(_config(), model_id="facebook/mms-tts-fas")
        self.assertIn("voice models mms-fa", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
