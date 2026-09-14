"""voice/repeat.py: the same question again, and a nudge (2026-09-13)."""

import unittest

from simorgh.voice.repeat import is_nudge, is_repeat


class RepeatTestCase(unittest.TestCase):
    def test_the_same_question_in_other_words_is_a_repeat(self):
        first = "Nvidia stock got dropped by 5% in 5 days last 5 days. What was the reason for that?"
        self.assertTrue(is_repeat("Sim, why did Nvidia stock drop 5% in the last 5 days?", first))
        self.assertTrue(is_repeat("What was the reason Nvidia dropped 5 percent in 5 days", first))
        self.assertTrue(is_repeat("nvidia stock got dropped by 5% in 5 days", first), "a part of it, said again")
        self.assertFalse(is_repeat("I'm eating strawberries, would you eat some with me?", first))
        self.assertFalse(is_repeat("yes", "yes"), "fragments are never repeats")
        self.assertFalse(is_repeat("Fix for what?", "what time is it"))

    def test_a_nudge_means_i_am_waiting(self):
        for text in ("Are you there?", "Sim, did you hear me?", "hello?", "Hey Sim, can you hear me", "You didn't answer."):
            self.assertTrue(is_nudge(text), text)
        for text in ("Can you hear us? The kids want a song", "hello Sim, play a song", "what is the time"):
            self.assertFalse(is_nudge(text), text)
