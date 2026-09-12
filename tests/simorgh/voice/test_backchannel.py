"""The sounds of having heard (voice/backchannel.py): picked by the
kind of turn, in the person's language, never repeating, and the reply
after one does not open with another."""

from __future__ import annotations

import unittest

from simorgh.voice.backchannel import (GREETING, HEARD, POOLS, QUESTION, REQUEST, STILL, Backchannel, addressed,
                                       classify, is_quiet, strip_lead)
from simorgh.voice.config import Config


class TestClassify(unittest.TestCase):
    def test_kinds(self) -> None:
        self.assertEqual(classify(""), HEARD)
        self.assertEqual(classify("the pool is exhausted"), HEARD)
        self.assertEqual(classify("what time is it"), QUESTION)
        self.assertEqual(classify("is the server up?"), QUESTION)
        self.assertEqual(classify("fix it"), REQUEST)
        self.assertEqual(classify("can you check the pool"), REQUEST)
        self.assertEqual(classify("hello"), GREETING)
        self.assertEqual(classify("thanks!"), GREETING)
        self.assertEqual(classify("لطفا اینو درست کن"), REQUEST)
        self.assertEqual(classify("چرا این کار نمی‌کنه"), QUESTION)


class TestPick(unittest.TestCase):
    def test_a_run_of_turns_never_repeats_itself(self) -> None:
        b = Backchannel(seed=7)
        picks = [b.pick(QUESTION) for _ in range(12)]
        for i in range(1, len(picks)):
            self.assertNotIn(picks[i], picks[max(0, i - Backchannel.RECENT):i], picks)

    def test_the_pools_are_wide(self) -> None:
        for kind in (HEARD, QUESTION, REQUEST):
            self.assertGreaterEqual(len(POOLS[kind]["en"]), 10, kind)
            self.assertGreaterEqual(len(POOLS[kind]["fa"]), 8, kind)
        self.assertGreaterEqual(len(STILL["en"]), 4)

    def test_nothing_a_synthesiser_cannot_say_or_a_person_would_not(self) -> None:
        # Kokoro read "Mm-hm." as letters (the creator, 2026-09-11); and
        # "Noted." / "Good question." / "Okay, okay." are not a listener.
        every = [t for pool in POOLS.values() for texts in pool.values() for t in texts]
        for bad in ("Mm-hm.", "Mm.", "Noted.", "Good question.", "Hmm, good question.", "Okay, okay.", "Right, right."):
            self.assertNotIn(bad, every)
        self.assertIn("Uh-huh.", POOLS[HEARD]["en"])
        self.assertIn("اوهوم.", POOLS[HEARD]["fa"])

    def test_a_greeting_falls_back_to_the_neutral_pool(self) -> None:
        self.assertIn(Backchannel(seed=1).pick(GREETING), POOLS[HEARD]["en"])


class TestAddressedAndQuiet(unittest.TestCase):
    def test_by_name_or_in_an_exchange_and_not_otherwise(self) -> None:
        self.assertTrue(addressed("hey sim, what time is it", since_sim_spoke_s=999.0, exchange_window_s=20.0))
        self.assertTrue(addressed("سیم ساعت چنده", since_sim_spoke_s=999.0, exchange_window_s=20.0))
        self.assertTrue(addressed("- Understood. - Shin.", since_sim_spoke_s=999.0, exchange_window_s=20.0))
        self.assertTrue(addressed("and the second one?", since_sim_spoke_s=4.0, exchange_window_s=20.0))
        self.assertFalse(addressed("and the second one?", since_sim_spoke_s=40.0, exchange_window_s=20.0))
        self.assertFalse(addressed("what time is it", since_sim_spoke_s=999.0, exchange_window_s=20.0))
        self.assertFalse(addressed("", since_sim_spoke_s=999.0, exchange_window_s=20.0))

    def test_quiet_is_the_word_alone_however_wrapped(self) -> None:
        for text in ("QUIET", "quiet.", "[QUIET]", " Quiet ", "*QUIET*"):
            self.assertTrue(is_quiet(text), text)
        for text in ("Quiet, the pool is fine.", "", "It is quiet in here."):
            self.assertFalse(is_quiet(text), text)

    def test_farsi_gets_farsi_and_an_unknown_language_gets_english(self) -> None:
        b = Backchannel(seed=1)
        self.assertIn(b.pick(HEARD, "fa"), POOLS[HEARD]["fa"])
        self.assertIn(b.pick(HEARD, "de"), POOLS[HEARD]["en"])
        self.assertIn(b.still("fa"), STILL["fa"])


class TestStripLead(unittest.TestCase):
    def test_a_repeated_okay_is_dropped_and_the_rest_kept(self) -> None:
        self.assertEqual(strip_lead("Okay, here it is."), "Here it is.")
        self.assertEqual(strip_lead("Yeah, the pool has 12 connections."), "The pool has 12 connections.")
        self.assertEqual(strip_lead("Sure. It is running."), "It is running.")
        self.assertEqual(strip_lead("باشه، الان."), "الان.")

    def test_a_reply_that_is_only_the_word_and_a_plain_reply_are_left_alone(self) -> None:
        self.assertEqual(strip_lead("Sure."), "Sure.")
        self.assertEqual(strip_lead("The pool has 12."), "The pool has 12.")
        self.assertEqual(strip_lead("Oh no, it crashed."), "No, it crashed.")


class TestEnabledAuto(unittest.TestCase):
    def test_auto_listens_only_for_a_person_with_a_real_microphone(self) -> None:
        cfg = Config()
        self.assertEqual(cfg.enabled, "auto")
        self.assertTrue(cfg.wants_listening(interactive=True, real_microphone=True))
        self.assertFalse(cfg.wants_listening(interactive=False, real_microphone=True))
        self.assertFalse(cfg.wants_listening(interactive=True, real_microphone=False))

    def test_a_plain_answer_in_the_config_is_taken_as_said(self) -> None:
        self.assertFalse(Config.from_mapping({"enabled": False}).wants_listening(interactive=True, real_microphone=True))
        self.assertTrue(Config.from_mapping({"enabled": True}).wants_listening(interactive=False, real_microphone=False))
        self.assertTrue(Config.from_mapping({"enabled": "on"}).wants_listening(interactive=False, real_microphone=False))
        self.assertEqual(Config.from_mapping({"enabled": "auto"}).enabled, "auto")


if __name__ == "__main__":
    unittest.main()
