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
