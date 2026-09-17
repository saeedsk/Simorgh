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


class ATagIsLettersInAnyScriptTestCase(unittest.TestCase):
    """`_TAG` matched `[A-Za-z]` only, so a tag with one accented or
    non-Latin letter never matched at all -- and an unmatched tag is
    spoken aloud, word for word.

    Live 2026-09-16: "[código is wrong] Nothing's running right now..."
    The `c` matched; the `ó` did not; the whole tag went to the speaker.
    The Farsi "[گرم]" (2026-09-13) never had a chance either, and Farsi
    is a language this house speaks.
    """

    def test_an_accented_tag_is_not_read_out(self):
        self.assertEqual(split_tone("[código is wrong] Nothing's running."),
                         ("", "Nothing's running."))

    def test_a_farsi_feeling_is_understood_not_just_dropped(self):
        self.assertEqual(split_tone("[گرم] سلام"), ("warm", "سلام"))
        self.assertEqual(split_tone("[آرام] سلام"), ("calm", "سلام"))

    def test_a_full_stop_inside_the_tag_does_not_defeat_it(self):
        """"[loud and clear.]" was the entire reply, and was spoken."""
        self.assertEqual(strip_tone("[loud and clear.]"), "")
        self.assertEqual(split_tone("[calm.] Breathe."), ("calm", "Breathe."))

    def test_an_upper_case_bracket_is_still_text(self):
        """A ticker is not a feeling -- the rule this must not break."""
        self.assertEqual(split_tone("[NVDA] is up two percent."),
                         ("", "[NVDA] is up two percent."))
