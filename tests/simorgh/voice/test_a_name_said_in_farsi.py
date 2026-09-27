"""A name in a Farsi sentence is said the way its person says it.

2026-09-27: the Farsi voice read سعید's ع as the Arabic pharyngeal
(/saʕiːd/); the creator says /sæiːd/. `voice pronounce Saeed سَئید`
gives the Farsi voice its own spelling; the English one stands, and the
screen still shows the name as written.
"""

import tempfile
import unittest
from pathlib import Path

from simorgh.voice.planner import SpokenResponsePlanner
from simorgh.voice.speakers import SpeakerBook


class ANameSaidInFarsi(unittest.TestCase):
    def setUp(self):
        self.planner = SpokenResponsePlanner(pronunciations={"Saeed": "Sah-eed"},
                                             farsi_pronunciations=lambda: {"Saeed": "سَئید"})

    def test_the_persian_spelling_and_the_latin_name_are_both_replaced(self):
        self.assertEqual(self.planner.pronounced("آره سعید، صدات رو می‌شنوم."), "آره سَئید، صدات رو می‌شنوم.")
        self.assertEqual(self.planner.pronounced("آره Saeed، صدات رو می‌شنوم."), "آره سَئید، صدات رو می‌شنوم.")

    def test_a_longer_word_is_left_alone(self):
        self.assertIn("سعیدی", self.planner.pronounced("سعیدی نه، سعید."))

    def test_english_keeps_the_english_pronunciation(self):
        self.assertEqual(self.planner.pronounced("Hi Saeed."), "Hi Sah-eed.")

    def test_a_word_after_a_dash_is_the_sentence_going_on(self):
        """Live 2026-09-27: "Saeed — say it again" was said "sa'eed it again"."""
        from simorgh.voice.planner import _drop_self_respelling

        self.assertEqual(_drop_self_respelling("Saeed — say it again.", "Saeed"), "Saeed — say it again.")
        self.assertEqual(_drop_self_respelling("Saeed -- Saa-eed, hi", "Saeed"), "Saeed, hi")
        self.assertEqual(_drop_self_respelling("Saeed (SAH-eed) here", "Saeed"), "Saeed here")

    def test_the_book_keeps_the_two_apart(self):
        with tempfile.TemporaryDirectory() as folder:
            book = SpeakerBook(Path(folder))
            book.pronounce("Saeed", "Sah-eed")
            book.pronounce("Saeed", "سَئید")
            self.assertEqual(book.pronunciations(), {"Saeed": "Sah-eed"})
            self.assertEqual(SpeakerBook(Path(folder)).farsi_pronunciations(), {"Saeed": "سَئید"})


if __name__ == "__main__":
    unittest.main()
