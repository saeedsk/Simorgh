"""Chatterbox Persian: chosen over Pocket by ear (2026-09-29)."""

import unittest
from dataclasses import replace

from simorgh.contracts.settings import VOICE_SAFE_KEYS
from simorgh.voice.config import Config
from simorgh.voice.tts import chatterbox_fa


class ChatterboxFarsi(unittest.TestCase):
    def test_it_is_a_farsi_engine_choice(self):
        self.assertIn("chatterbox", VOICE_SAFE_KEYS["tts_farsi"][1])

    def test_the_authors_settings(self):
        self.assertEqual(chatterbox_fa.PARAMS, {"temperature": 0.7, "cfg_weight": 0.5, "top_p": 0.5, "exaggeration": 0.6})

    def test_missing_weights_are_said(self):
        with self.assertRaises(ImportError) as caught:
            chatterbox_fa.ChatterboxFarsiSynthesiser(replace(Config(), tts_farsi_chatterbox_weights="/nowhere/t3_fa.safetensors"))
        self.assertIn("Thomcles/Chatterbox-TTS-Persian-Farsi", str(caught.exception))

    def test_it_lives_in_the_chatterbox_venv(self):
        self.assertEqual(chatterbox_fa.ChatterboxFarsiSynthesiser.venv_name, "chatterbox")
        self.assertEqual(chatterbox_fa.ChatterboxFarsiSynthesiser.server, "chatterbox_fa_server.py")


if __name__ == "__main__":
    unittest.main()
