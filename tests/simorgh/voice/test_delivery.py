"""How a thing is said (voice/delivery.py): pace, loudness and room
chosen from the situation, and the empathy sound."""

from __future__ import annotations

import array
import unittest

from simorgh.voice.backchannel import EMPATHY, HEARD, POOLS, QUESTION, REQUEST, Backchannel, classify
from simorgh.voice.delivery import REGISTERS, Delivery, apply_gain, register_for_backchannel, register_for_reply


class TestRegisterForReply(unittest.TestCase):
    def test_a_hurt_is_answered_warm_whatever_the_answer_says(self) -> None:
        d = register_for_reply("I am so tired today, my dog died", "Twelve o'clock.")
        self.assertEqual(d.register, "warm")
        self.assertLess(d.speed, 1.0)
        self.assertLess(d.gain, 1.0)
        self.assertGreater(d.pause_scale, 1.0)
        self.assertEqual(register_for_reply("امروز خیلی خسته‌ام", "باشه").register, "warm")

    def test_good_news_is_bright_and_a_plain_question_is_neutral(self) -> None:
        self.assertEqual(register_for_reply("we did it! the tests pass", "Yes.").register, "bright")
        self.assertGreater(register_for_reply("great news", "Yes.").speed, 1.0)
        self.assertEqual(register_for_reply("what time is it", "Twelve."), REGISTERS["neutral"])
        self.assertEqual(register_for_reply("the pool is exhausted and the build failed", "Yes.").register, "neutral")

    def test_an_error_is_gentle_and_the_mood_only_nudges(self) -> None:
        self.assertEqual(register_for_reply("do it", "Sorry, I couldn't.", is_error=True).register, "warm")
        low = register_for_reply("what time is it", "Twelve.", valence=-0.6)
        high = register_for_reply("what time is it", "Twelve.", arousal=0.6)
        self.assertLess(low.speed, 1.0)
        self.assertGreater(high.speed, 1.0)
        self.assertLessEqual(abs(low.speed - 1.0), 0.05)
        self.assertLessEqual(abs(high.speed - 1.0), 0.05)
        extreme = register_for_reply("my dog died", "Sorry.", valence=-1.0, arousal=-1.0)
        self.assertGreaterEqual(extreme.speed, 0.8, "never slower than the floor")

    def test_the_base_speed_and_volume_scale_the_register(self) -> None:
        d = REGISTERS["warm"].with_base(1.1, 0.5)
        self.assertAlmostEqual(d.speed, 0.92 * 1.1, places=3)
        self.assertAlmostEqual(d.gain, 0.85 * 0.5, places=3)


class TestRegisterForBackchannel(unittest.TestCase):
    def test_aha_is_slow_got_it_is_quick_i_know_is_warm(self) -> None:
        self.assertLess(register_for_backchannel(QUESTION).speed, 1.0)   # "Aha…" for something new
        self.assertGreater(register_for_backchannel(REQUEST).speed, 1.0)  # "Got it." once the ask is clear
        self.assertEqual(register_for_backchannel(EMPATHY).register, "warm")
        self.assertEqual(register_for_backchannel(HEARD).register, "unsure")
        self.assertLess(REGISTERS["hum"].gain, 0.5, "the listener's uh-huh is half loud")

    def test_a_hurt_is_classified_as_empathy_and_gets_the_warm_words(self) -> None:
        self.assertEqual(classify("my dog died yesterday"), EMPATHY)
        self.assertEqual(classify("I'm so tired of this"), EMPATHY)
        self.assertEqual(classify("what time is it"), QUESTION)
        self.assertIn(Backchannel(seed=1).pick(EMPATHY), POOLS[EMPATHY]["en"])
        self.assertIn("I know.", POOLS[EMPATHY]["en"])


class TestApplyGain(unittest.TestCase):
    def test_scales_and_clips(self) -> None:
        pcm = array.array("h", [1000, -1000, 30000]).tobytes()
        self.assertEqual(array.array("h", apply_gain(pcm, 0.45)).tolist(), [450, -450, 13500])
        self.assertEqual(array.array("h", apply_gain(pcm, 2.0)).tolist(), [2000, -2000, 32767])
        self.assertIs(apply_gain(pcm, 1.0), pcm)


if __name__ == "__main__":
    unittest.main()
