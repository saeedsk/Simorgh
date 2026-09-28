"""Short-vowel marks reach the Farsi voice, and the model writes them.

2026-09-27, the creator: in «یکی ترک می‌گه» the voice said "ta-ra-k" where
"tork" was meant. The G2P reads «تُرک» as tork and «عکسِ رخِ» with its ezafe
-- but Pocket's normaliser dropped every mark before the G2P saw it."""

import re
import unittest
from types import SimpleNamespace

from simorgh.voice.tts.servers.pocket_server import VOWEL_MARKS, keep_vowel_marks, with_lexicon


class FarsiVowelMarks(unittest.TestCase):
    def test_the_normaliser_keeps_the_four_and_drops_the_rest(self):
        fake = SimpleNamespace(DIACRITICS=re.compile(r"[ً-ٟ]"), ALLOWED=set("abc"))
        keep_vowel_marks(fake)
        text = "تُرکَ عکسِ رخّ" + "ً" + "ْ"
        kept = fake.DIACRITICS.sub("", text)
        for mark in VOWEL_MARKS:
            if mark in text:
                self.assertIn(mark, kept)
        self.assertNotIn("ً", kept)            # tanwin still goes
        self.assertNotIn("ْ", kept)            # sukun still goes
        self.assertTrue(set(VOWEL_MARKS) <= fake.ALLOWED)

    def test_a_marked_word_still_finds_its_lexicon_entry(self):
        self.assertEqual(with_lexicon("سلام سَعید، خوبی؟", "s/lam s/@id xubi", {"سعید": "s/id"}), "s/lam s/id xubi")


if __name__ == "__main__":
    unittest.main()
