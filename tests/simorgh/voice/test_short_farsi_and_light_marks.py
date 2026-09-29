"""Two live finds, 2026-09-28.

«سَعید، سَعید.» came out "سگیده": on a short line Pocket's G2P loops (the
name six times for two words), and the lexicon, which lines words and
sounds up by position, could not fix it. And a reply marked on nearly
every word was read mark by mark."""

import unittest

from simorgh.voice.tts.servers.pocket_server import aligned_sounds, with_lexicon


def _looping_g2p(text):
    if " " in text.strip():
        return "s/@id " * 6
    return "s/@id" if "سعید" in text else "x"


class ShortFarsi(unittest.TestCase):
    def test_a_looping_line_is_redone_word_by_word(self):
        sounds = aligned_sounds("سعید، سعید.", _looping_g2p)
        self.assertEqual(sounds, "s/@id s/@id")
        self.assertEqual(with_lexicon("سعید، سعید.", sounds, {"سعید": "s/id"}), "s/id s/id")

    def test_a_good_line_is_left_as_the_g2p_gave_it(self):
        self.assertEqual(aligned_sounds("a b", lambda t: "1 2"), "1 2")


class AFarsiVerseIsOnePiece(unittest.TestCase):
    """Live 2026-09-28: a fully marked verse came out "in three pieces,
    choppy" -- the marks counted as length, and the first piece was kept
    short on purpose."""

    def test_a_marked_verse_is_one_chunk(self):
        from simorgh.voice.planner import chunk

        verse = "اَگَر آن تُرکِ شیرازی به دَست آرَد دِلِ ما را، به خالِ هِندویَش بَخشَم سَمَرقَند و بُخارا را."
        self.assertEqual(len(chunk(verse)), 1)

    def test_marks_are_not_letters(self):
        from simorgh.voice.planner import _letters

        self.assertEqual(_letters("دِلِ"), _letters("دل"))


if __name__ == "__main__":
    unittest.main()
