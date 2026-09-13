"""Who said which words of one turn (voice/diarize.py), with a fake
embedder that reads the speaker off the audio itself."""

from __future__ import annotations

import math
import unittest

from simorgh.voice.api import Word
from simorgh.voice.diarize import attribute, lines, speakers_in, windows
from simorgh.voice.speakers import Identification

RATE = 16000


def _pcm(*stretches: tuple[str, float]) -> bytes:
    """Audio whose sample VALUE says who is talking: Saeed's stretches
    are +1000, Soodeh's -1000, silence 0."""
    level = {"Saeed": 1000, "Soodeh": -1000, "": 0}
    out = bytearray()
    for who, seconds in stretches:
        out += level[who].to_bytes(2, "little", signed=True) * int(seconds * RATE)
    return bytes(out)


def _embed(samples, rate):
    mean = sum(samples) / max(1, len(samples))
    return [mean]


def _identify(vector):
    mean = vector[0]
    if mean > 0.01:
        return Identification(name="Saeed", score=0.9)
    if mean < -0.01:
        return Identification(name="Soodeh", score=0.9)
    return Identification(name="", score=0.1, reason="nobody")


def _words(spec: str) -> list[Word]:
    """`"hello there 0 2 | yes dear 2 4"` -> words spread evenly over each span."""
    out = []
    for part in spec.split("|"):
        tokens = part.split()
        start, end = float(tokens[-2]), float(tokens[-1])
        names = tokens[:-2]
        step = (end - start) / len(names)
        for i, name in enumerate(names):
            out.append(Word(name, start + i * step, start + (i + 1) * step))
    return out


class WindowsTestCase(unittest.TestCase):
    def test_windows_cover_the_audio_and_end_at_its_end(self):
        self.assertEqual(windows(1.0), [(0.0, 1.0)])
        w = windows(4.0)
        self.assertEqual(w[0], (0.0, 1.2))
        self.assertAlmostEqual(w[-1][1], 4.0)
        self.assertTrue(all(b - a <= 1.2 + 1e-9 for a, b in w))


class AttributeTestCase(unittest.TestCase):
    def test_one_speaker_is_one_stretch(self):
        pcm = _pcm(("Saeed", 4.0))
        segs = attribute(pcm, RATE, _words("the pool is warm tonight 0 4"), _embed, _identify)
        self.assertEqual([(s.speaker, s.text) for s in segs], [("Saeed", "the pool is warm tonight")])
        self.assertEqual(speakers_in(segs), ["Saeed"])

    def test_two_speakers_get_their_own_words(self):
        pcm = _pcm(("Saeed", 3.0), ("Soodeh", 3.0))
        segs = attribute(pcm, RATE, _words("should we eat outside tonight 0 3 | yes let us do that 3 6"), _embed, _identify)
        self.assertEqual([(s.speaker, s.text) for s in segs],
                         [("Saeed", "should we eat outside tonight"), ("Soodeh", "yes let us do that")])
        self.assertEqual(speakers_in(segs), ["Saeed", "Soodeh"])
        self.assertEqual(lines(segs), "Saeed: should we eat outside tonight\nSoodeh: yes let us do that")
        self.assertAlmostEqual(segs[1].start, 3.0, places=1)

    def test_a_stray_word_between_two_stretches_of_one_voice_is_theirs(self):
        # 4 s of Saeed with a 0.3 s blip of the other level in the middle: the
        # words there belong to Saeed, not to a one-word Soodeh
        pcm = _pcm(("Saeed", 2.0), ("Soodeh", 0.3), ("Saeed", 1.7))
        words = _words("one two three four five six seven eight 0 4")
        segs = attribute(pcm, RATE, words, _embed, _identify)
        self.assertEqual(len(segs), 1, [(s.speaker, s.text) for s in segs])
        self.assertEqual(segs[0].speaker, "Saeed")

    def test_silence_at_the_edges_joins_the_neighbour_and_untimed_words_give_nothing(self):
        pcm = _pcm(("", 1.0), ("Saeed", 3.0))
        segs = attribute(pcm, RATE, _words("um so the garden 0 4"), _embed, _identify)
        self.assertEqual([(s.speaker, s.text) for s in segs], [("Saeed", "um so the garden")])
        self.assertEqual(attribute(pcm, RATE, [Word("x", 0.0, 0.0)], _embed, _identify), [])
        self.assertEqual(attribute(pcm, RATE, [], _embed, _identify), [])

    def test_a_failing_window_is_nobody_not_a_crash(self):
        def _boom(samples, rate):
            raise RuntimeError("no model")
        pcm = _pcm(("Saeed", 3.0))
        segs = attribute(pcm, RATE, _words("a b c 0 3"), _boom, _identify)
        self.assertEqual([(s.speaker, s.text) for s in segs], [("", "a b c")])
        self.assertEqual(speakers_in(segs), [])
