"""A scrap of speech nobody addressed to Sim gets silence, not "say it again".

The creator, 2026-10-04: "sim can be annoying, multiple times asking can
you repeat it (in Farsi)" -- «جانم، دوباره می‌گی؟» answered «ش است»,
«پراپین», «تبشن», «ای ق», scraps a satellite's follow-up window caught."""

from __future__ import annotations

import types
import unittest

from simorgh.voice import session as sess


class ScrapsAreNotAskedBack(unittest.TestCase):
    def test_the_live_scraps_are_fragments(self):
        for heard in ("ش است", "پراپین", "تبشن", "ای ق"):
            with self.subTest(heard=heard):
                self.assertTrue(sess._fragment(heard))       # noqa: SLF001

    def test_requests_are_not(self):
        for heard in ("what time is it", "about nine", "سعید کجاست", "چراغ آشپزخونه رو خاموش کن", "که ک کجاست همون نو کاستایی"):
            with self.subTest(heard=heard):
                self.assertFalse(sess._fragment(heard))      # noqa: SLF001

    def test_a_short_answer_to_sims_question_is_an_answer(self):
        fake = types.SimpleNamespace(_now=lambda: 100.0,
                                     _room=[("Sim", "می‌خوای ساعت پنج یادت بندازم؟", 90.0, "reply")])
        self.assertTrue(sess.VoiceSession._sim_just_asked(fake))          # noqa: SLF001
        fake._room = [("Sim", "باشه، خاموشش کردم.", 90.0, "reply")]      # noqa: SLF001
        self.assertFalse(sess.VoiceSession._sim_just_asked(fake))         # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
