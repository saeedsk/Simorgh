"""Sim's own aside, heard back inside the person's turn, is not a second
speaker (live 2026-10-28).

Sim hummed "Yep." while the creator was saying "Hey Sim, I'm talking to
you. Check my email box for past 30 days ...". The "Yep." came back
through the microphone scored as Iris, and `diarize.answering` gives the
turn to the last voice heard for sure: the request went to Iris's
conversation as "Iris: Saeed: Sim, I'm talking to you ... / Iris: Yep.",
and the model, reading Iris quote Saeed, stayed QUIET."""

import unittest

from simorgh.voice.diarize import Attributed, answering, lines
from simorgh.voice.session import without_own_asides

ASKED = "Sim, I'm talking to you. Check my email box for past 30 days and find all the promo email senders."


class SimsOwnAsideIsNotASpeaker(unittest.TestCase):
    def test_the_creator_keeps_his_turn(self):
        segments = [Attributed("Saeed", ASKED, 0.0, 6.0), Attributed("Iris", "Yep.", 6.1, 6.5)]
        kept = without_own_asides(segments, ["Right.", "Yep."])
        self.assertEqual(answering(kept), "Saeed")
        self.assertEqual(lines(kept), f"Saeed: {ASKED}")

    def test_a_real_second_voice_stays(self):
        segments = [Attributed("Saeed", ASKED, 0.0, 6.0), Attributed("Iris", "Can I watch TV?", 6.1, 7.5)]
        self.assertEqual(without_own_asides(segments, ["Yep."]), segments)

    def test_a_turn_is_never_emptied(self):
        segments = [Attributed("Iris", "Yep.", 0.0, 0.4), Attributed("", "Yep.", 0.5, 0.9)]
        self.assertEqual(without_own_asides(segments, ["Yep."]), segments)


if __name__ == "__main__":
    unittest.main()
