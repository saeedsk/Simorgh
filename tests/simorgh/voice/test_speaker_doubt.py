"""Live 2026-09-19: with only Saeed, Ira and Iris in the room, Sim answered
the girls as "Soodeh" at 0.51, and at 0.57 with Iris at 0.54. A name at
the edge of the evidence reaches the model with its doubt, and the prompt
then asks for no name."""

import unittest

from simorgh.orchestration.scaffolds import who_is_here
from simorgh.voice.speakers import Identification, doubt_of


class Doubt(unittest.TestCase):
    def test_the_live_cases_are_doubted(self):
        self.assertIn("Iris", doubt_of(Identification("Soodeh", 0.57, "Iris", 0.54), threshold=0.5))
        self.assertTrue(doubt_of(Identification("Soodeh", 0.51), threshold=0.5))
        self.assertTrue(doubt_of(Identification("Saeed", 0.46, probable=True), threshold=0.5))

    def test_a_clear_match_is_not(self):
        self.assertEqual(doubt_of(Identification("Saeed", 0.74, "Aran", 0.31), threshold=0.5), "")
        self.assertEqual(doubt_of(None, threshold=0.5), "")
        self.assertEqual(doubt_of(Identification("", 0.2), threshold=0.5), "")

    def test_the_prompt_asks_for_no_name_when_unsure(self):
        unsure = who_is_here("Soodeh", "", "", doubt="Iris sounds almost the same")
        self.assertIn("PROBABLY Soodeh", unsure)
        self.assertIn("Do not call them by any name", unsure)
        self.assertNotIn("You are speaking with Soodeh", unsure)
        self.assertIn("You are speaking with Saeed", who_is_here("Saeed", "", ""))


if __name__ == "__main__":
    unittest.main()
