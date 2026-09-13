"""The feeling tag at the head of a spoken reply (contracts/tone.py)."""

import unittest

from simorgh.contracts.tone import TONES, split_tone, strip_tone


class ToneTestCase(unittest.TestCase):
    def test_a_tag_is_split_off_and_synonyms_map(self):
        self.assertEqual(split_tone("[warm] It's three o'clock."), ("warm", "It's three o'clock."))
        self.assertEqual(split_tone("[Happy]: Yes!"), ("bright", "Yes!"))
        self.assertEqual(split_tone("(tone: sad) I cannot do that."), ("sorry", "I cannot do that."))
        self.assertEqual(split_tone("<calm> Breathe."), ("calm", "Breathe."))
        self.assertEqual(strip_tone("[playful] Nice try."), "Nice try.")

    def test_no_tag_or_not_a_tone_leaves_the_text_alone(self):
        self.assertEqual(split_tone("It's three o'clock."), ("", "It's three o'clock."))
        self.assertEqual(split_tone("[NVDA] is up two percent."), ("", "[NVDA] is up two percent."))
        self.assertEqual(split_tone(""), ("", ""))
        self.assertIn("neutral", TONES)
