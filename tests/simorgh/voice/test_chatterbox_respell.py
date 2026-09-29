"""`tts_farsi_respell`: words Chatterbox Persian says wrong, respelled.

The creator, 2026-09-29: "chera mige 'asrat', bayad bege 'asret'". Vowel
marks did not move it (عَصرِت stayed "Asrat" in every take); spelled with
an alef, اَسرِت, both takes came back "Asred" / "Astrid" through whisper.
"""

from __future__ import annotations

import unittest

from simorgh.voice.config import Config
from simorgh.voice.tts.chatterbox_fa import respelled
from simorgh.voice.tts.pocket import parse_lexicon


class RespellTestCase(unittest.TestCase):
    table = {"عصرت": "اَسرِت"}

    def test_the_word_is_respelled_marked_or_not(self):
        self.assertEqual(respelled("سلام عصرت جان", self.table), "سلام اَسرِت جان")
        self.assertEqual(respelled("سلام عَصرِت جان", self.table), "سلام اَسرِت جان")

    def test_persian_punctuation_is_not_part_of_the_word(self):
        self.assertEqual(respelled("عصرت، بیا؟ عصرت؟", self.table), "اَسرِت، بیا؟ اَسرِت؟")

    def test_only_whole_words(self):
        self.assertEqual(respelled("عصرتان", self.table), "عصرتان")

    def test_nothing_to_respell_leaves_the_text_alone(self):
        self.assertEqual(respelled("سلام", {}), "سلام")

    def test_the_default_carries_the_creators_word(self):
        self.assertEqual(parse_lexicon(Config().tts_farsi_respell).get("عصرت"), "اَسرِت")


if __name__ == "__main__":
    unittest.main()
