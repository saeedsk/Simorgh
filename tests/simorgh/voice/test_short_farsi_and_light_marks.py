"""Two live finds, 2026-09-28.

«سَعید، سَعید.» came out "سگیده": on a short line Pocket's G2P loops (the
name six times for two words), and the lexicon, which lines words and
sounds up by position, could not fix it. And a reply marked on nearly
every word was read mark by mark."""

import unittest

from simorgh.voice.planner import _lightly_marked
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


class LightMarks(unittest.TestCase):
    def test_an_over_marked_reply_keeps_the_ezafe_and_two_way_words(self):
        got = _lightly_marked("نه، اَصلاً دُرُست نیست؛ سیستمِ صِدا کَلَمه را غَلَط خواند و تُرک هَمان اَست.")
        self.assertIn("سیستمِ", got)
        self.assertIn("تُرک", got)
        for bare in ("درست", "صدا", "کلمه", "غلط", "همان"):
            self.assertIn(bare, got)

    def test_a_lightly_marked_reply_is_untouched(self):
        light = "امروز هوا خیلی دلپذیر بود؛ آفتابِ ملایم و یه نسیمِ خُنَک از سمتِ کوه."
        self.assertEqual(_lightly_marked(light), light)


if __name__ == "__main__":
    unittest.main()
