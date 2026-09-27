"""A Farsi sentence of a word or two is said with the next one.

Measured 2026-09-27: Pocket, cloning its voice from a reference clip,
said the clip's own opening words -- "khoob, Fahimeh o Azadeh koja
raftand" -- instead of "آره." about half the time. The creator heard a
stranger's sentence in the middle of Sim's answers.
"""

import unittest

from simorgh.voice.streamreply import SentenceStream


class AShortFarsiSentenceWaits(unittest.TestCase):
    def test_joined_to_the_next(self):
        s = SentenceStream(max_sentences=5)
        for piece in ("آره سعید.", " صدات رو می‌شنوم و می‌شناسم.", " "):
            s.feed(piece)
        self.assertEqual(s.spoken, ["آره سعید. صدات رو می‌شنوم و می‌شناسم."])

    def test_a_full_farsi_sentence_goes_alone(self):
        s = SentenceStream(max_sentences=5)
        for piece in ("هوا امروز آفتابیه و گرمه.", " فردا بارون میاد.", " "):
            s.feed(piece)
        self.assertEqual(s.spoken[0], "هوا امروز آفتابیه و گرمه.")

    def test_english_is_unchanged(self):
        s = SentenceStream(max_sentences=5)
        for piece in ("Yes, I hear you.", " Loud and clear.", " "):
            s.feed(piece)
        self.assertEqual(s.spoken[0], "Yes, I hear you.")


if __name__ == "__main__":
    unittest.main()
