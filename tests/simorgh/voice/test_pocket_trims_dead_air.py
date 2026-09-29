"""A Pocket piece loses its dead air at each end.

Measured 2026-09-28: 0.2 s of silence before and 0.35-0.7 s after every
piece; a reply is said a sentence at a time, and on the satellite that was
one to one and a half seconds between sentences -- "hop hop"."""

import math
import struct
import unittest

from simorgh.voice.api import Audio
from simorgh.voice.tts.pocket import KEEP_LEAD_S, KEEP_TAIL_S, trim_silence

RATE = 24000


def _audio(silence_before: float, speech: float, silence_after: float) -> Audio:
    quiet = b"\x00\x00"
    tone = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / RATE)))
                    for i in range(int(speech * RATE)))
    return Audio(quiet * int(silence_before * RATE) + tone + quiet * int(silence_after * RATE), RATE)


class PocketTrimsDeadAir(unittest.TestCase):
    def test_edges_come_down_to_a_breath(self):
        trimmed = trim_silence(_audio(0.2, 1.0, 0.7))
        self.assertAlmostEqual(trimmed.seconds, 1.0 + KEEP_LEAD_S + KEEP_TAIL_S, delta=0.05)

    def test_speech_is_never_cut(self):
        trimmed = trim_silence(_audio(0.0, 1.0, 0.0))
        self.assertAlmostEqual(trimmed.seconds, 1.0, delta=0.03)

    def test_silence_alone_is_left_as_it_is(self):
        audio = _audio(0.5, 0.0, 0.0)
        self.assertEqual(trim_silence(audio).pcm, audio.pcm)


if __name__ == "__main__":
    unittest.main()
