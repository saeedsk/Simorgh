"""The creator heard "awful noise" before replies (2026-09-19) while every
synthesised piece measured offline was speech. What goes to the speaker is
checked: noise is refused, logged and kept for inspection."""

import asyncio
import unittest

import numpy as np

from simorgh.voice import audio as audio_mod
from simorgh.voice.api import Audio


class NoiseIsRefused(unittest.TestCase):
    def test_white_noise_is_caught_and_speech_like_audio_is_not(self):
        noise = (np.random.default_rng(1).standard_normal(24000) * 6000).astype(np.int16).tobytes()
        self.assertTrue(audio_mod.noise_report(Audio(noise, 24000)))
        t = np.arange(24000) / 24000
        voiced = (np.sin(2 * np.pi * 180 * t) * 6000).astype(np.int16).tobytes()
        self.assertEqual(audio_mod.noise_report(Audio(voiced, 24000)), "")
        self.assertIn("odd byte count", audio_mod.noise_report(Audio(voiced + b"\x00", 24000)))

    def test_the_command_speaker_does_not_play_it(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        speaker = audio_mod.CommandSpeaker.__new__(audio_mod.CommandSpeaker)
        speaker._cmd = ["/bin/false"]  # noqa: SLF001
        noise = (np.random.default_rng(2).standard_normal(24000) * 6000).astype(np.int16).tobytes()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(audio_mod, "NOISE_DIR", Path(tmp) / "noise"), \
                mock.patch.object(audio_mod, "PLAYED_DIR", Path(tmp) / "played"), \
                mock.patch("asyncio.create_subprocess_exec") as spawn:
            asyncio.run(speaker.play(Audio(noise, 24000)))
            spawn.assert_not_called()
            self.assertEqual(len(list((Path(tmp) / "noise").glob("*.wav"))), 1)
            # What went to the speaker -- refused or not -- is kept for inspection.
            self.assertTrue((Path(tmp) / "played" / "latest.txt").is_file())


if __name__ == "__main__":
    unittest.main()
