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



LONG = ("سعید، نکته‌ی جالب اینه. خیام و حافظ دو تا جواب متضاد به یک سؤال واحد هستن: سؤال «دنیا چیه و ما کی "
        "هستیم»، خیام ویرانه‌گره — برای او دنیا یک چرخ بی‌رحمه و جوابش فایده نداره، پس فقط «حضور» باقی "
        "می‌مونه: شراب، لحظه‌ی حال، و پذیرفتن مرگ. تمام.")


class ALongFarsiSentenceIsSaidAClauseAtATime(unittest.TestCase):
    """Live 2026-09-27: a long Farsi answer turned to babble at the end."""

    def test_streamed(self):
        from simorgh.voice.planner import FARSI_MAX_LETTERS, _letters

        s = SentenceStream(max_sentences=8)
        s.feed(LONG)
        s.feed(" ")
        self.assertTrue(all(_letters(x) <= FARSI_MAX_LETTERS for x in s.spoken), [len(x) for x in s.spoken])
        self.assertGreaterEqual(len(s.spoken), 2)

    def test_said_to_the_phone(self):
        from simorgh.voice.planner import FARSI_MAX_LETTERS, _letters
        from simorgh.voice.service import _speech_pieces

        pieces = _speech_pieces(LONG)
        self.assertTrue(all(_letters(x) <= FARSI_MAX_LETTERS for x in pieces), [len(x) for x in pieces])
        self.assertTrue(all(len(x.split()) >= 4 for x in pieces), pieces)
        self.assertEqual(" ".join(pieces).replace(" ", "").replace("—", ""), LONG.replace(" ", "").replace("—", ""))


if __name__ == "__main__":
    unittest.main()
