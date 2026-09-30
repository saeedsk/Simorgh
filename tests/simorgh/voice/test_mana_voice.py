"""The Mana voice: Piper on Mana-TTS, with ezafe, slowed and brightened --
the creator's pick of the fast Farsi voices, 2026-09-29."""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from simorgh.voice.config import Config
from simorgh.voice.tts import mana

_HERE = Path(Config().model_dir) / f"{mana.DEFAULT_MODEL}.onnx"


class TheShelf(unittest.TestCase):
    def _gain_db(self, freq: float, rate: int = 22050) -> float:
        b, a = mana._shelf(rate)                          # noqa: SLF001
        w = 2 * math.pi * freq / rate
        z = complex(math.cos(w), -math.sin(w))
        h = (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
        return 20 * math.log10(abs(h))

    def test_bass_is_left_alone_and_the_top_is_lifted_four_db(self):
        self.assertAlmostEqual(self._gain_db(100), 0.0, delta=0.3)
        self.assertAlmostEqual(self._gain_db(9000), mana.SHELF_DB, delta=0.4)


@unittest.skipUnless(_HERE.is_file(), "the Mana voice is not downloaded on this machine")
class TheEzafe(unittest.TestCase):
    def test_the_linking_e_is_said(self):
        voice = mana.ManaSynthesiser(Config())
        said = "".join(voice.phonemes("کتاب قرمز دوست من روی میز چوبی اتاق خواب است."))
        for linked in ("kˈetɑbe", "q1ˈermeze", "dˈuːste", "mˈize", "tʃˈuːbije", "ˈotɑːq1e"):
            self.assertIn(linked, said)


if __name__ == "__main__":
    unittest.main()
