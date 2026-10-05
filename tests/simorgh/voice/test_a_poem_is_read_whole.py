"""A poem or a story asked for is told whole -- in Farsi too.

The creator, 2026-10-04: "when I ask sim to read a poem, I expect it to
continue reading instead of saying a short part and stop". «حالا از حافظ
بخون» got one couplet: the narration pattern knew only English, and the
streaming path (which speaks every live reply) never asked it."""

from __future__ import annotations

import unittest

from simorgh.voice.planner import asked_to_continue, narration_wanted


class APoemIsReadWhole(unittest.TestCase):
    def test_the_creators_own_requests_are_narration(self):
        for asked in ("حالا از حافظ بخون", "یه شعر از حافظ بگو", "برام قصه بگو", "شعر حافظ بخون",
                      "read me a poem", "tell me a story from the Arabian Nights"):
            with self.subTest(asked=asked):
                self.assertTrue(narration_wanted(asked))

    def test_ordinary_turns_are_not(self):
        for asked in ("چراغ رو خاموش کن", "ساعت چنده؟", "what time is it", "turn the light off"):
            with self.subTest(asked=asked):
                self.assertFalse(narration_wanted(asked))

    def test_go_on_in_farsi(self):
        for asked in ("ادامه بده", "بقیه‌ش رو بخون", "بقیه‌اش را بخوان", "go on"):
            with self.subTest(asked=asked):
                self.assertTrue(asked_to_continue(asked))
        self.assertFalse(asked_to_continue("continue the washing machine"))

    def test_the_voice_prompt_asks_for_the_whole_poem(self):
        from simorgh.orchestration.scaffolds import VOICE

        self.assertIn("give the whole of it", VOICE)
        self.assertIn("Never say the rest is on the screen", VOICE)


if __name__ == "__main__":
    unittest.main()
