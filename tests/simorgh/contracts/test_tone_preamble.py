"""A plan the model wrote before its tone tag is not part of the answer.

Live 2026-09-15: "Calm answer, then compress offer.\n\n[calm] Mostly our
conversations..." was spoken aloud, plan first, and the [calm] tag was
ignored because it did not open the reply."""

import unittest

from simorgh.contracts.tone import split_tone


class TonePreamble(unittest.TestCase):
    def test_the_live_case(self):
        tone, rest = split_tone("Calm answer, then compress offer.\n\n[calm] Mostly our conversations, Saeed.")
        self.assertEqual(tone, "calm")
        self.assertEqual(rest, "Mostly our conversations, Saeed.")

    def test_a_tag_at_the_head_is_unchanged(self):
        self.assertEqual(split_tone("[warm] It's three o'clock."), ("warm", "It's three o'clock."))

    def test_prose_with_brackets_is_untouched(self):
        for text in ("I read [1] of the docs\nand the rest tomorrow.",
                     "First line.\n\n[not-a-tone] second line.",
                     "A long first paragraph " + "x" * 200 + "\n\n[calm] still not a preamble."):
            self.assertEqual(split_tone(text), ("", text), text[:40])


if __name__ == "__main__":
    unittest.main()


class MetaTag(unittest.TestCase):
    """GLM wrote "[sd:0.55, sv:0.45] Sah-EED." and the scores were spoken
    aloud, "zero point five five" and all (live 2026-09-15)."""

    def test_a_numeric_head_tag_is_dropped(self):
        self.assertEqual(split_tone("[sd:0.55, sv:0.45] Sah-EED."), ("", "Sah-EED."))
        self.assertEqual(split_tone("[turn 4] hello"), ("", "hello"))

    def test_a_feeling_is_still_a_feeling(self):
        self.assertEqual(split_tone("[warm] hello"), ("warm", "hello"))
        self.assertEqual(split_tone("[calm] 12 o'clock"), ("calm", "12 o'clock"))

    def test_any_head_tag_is_dropped_not_spoken(self):
        """The long-standing contract: a bracket at the head is never said
        aloud, feeling or not. The numeric case above is the one the old
        pattern could not match."""
        self.assertEqual(split_tone("[the kitchen] is warm"), ("", "is warm"))


class TwoTagsAndDashes(unittest.TestCase):
    """"[loud and clear — calm, warm] [calm] Loud and clear." -- the first
    tag was spoken aloud, em dash and all (live 2026-09-15)."""

    def test_the_live_case(self):
        tone, rest = split_tone("[loud and clear — calm, warm] [calm] Loud and clear.")
        self.assertEqual(tone, "calm")
        self.assertEqual(rest, "Loud and clear.")

    def test_a_dashed_tag_alone(self):
        self.assertEqual(split_tone("[warm — gentle] hello"), ("warm", "hello"))

    def test_prose_is_untouched(self):
        self.assertEqual(split_tone("Loud and clear."), ("", "Loud and clear."))
