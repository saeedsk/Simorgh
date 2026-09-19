""""I've noted it" about a name's pronunciation, with nothing written
(live 2026-09-15). The spelling the creator then saw was the one built
into contracts/household.py all along."""

from __future__ import annotations

import types
import unittest

from simorgh.orchestration.stophook import claimed_to_note_a_pronunciation


def _session(*tools: str, summary: str = 'voice: Ira is said "Eye-raa" from now on'):
    steps = [types.SimpleNamespace(tool=t, ok=True, summary=summary) for t in tools]
    return types.SimpleNamespace(steps=steps)


class NotedNothing(unittest.TestCase):
    def test_the_live_wording_is_caught(self):
        for text in ("Got it, Saeed — I'll say it as \"Sah-eed\". I've noted it so I keep saying your name right.",
                     "Noted, that's how I'll pronounce your name from now on.",
                     "I've saved the pronunciation of your name."):
            self.assertTrue(claimed_to_note_a_pronunciation(text, _session()), text)

    def test_a_turn_that_stored_it_is_left_alone(self):
        text = "I've noted the pronunciation of your name."
        self.assertEqual(claimed_to_note_a_pronunciation(text, _session("sim_command")), "")

    def test_a_tool_that_stored_nothing_does_not_back_it(self):
        """Live 2026-09-19: the voices were listed, and the reply said "Ira's
        pronunciation is set to EYE-ra"."""
        listing = _session("voice_setting", summary="styletts2: 3 voices, current af_bella")
        for text in ("Ira's pronunciation is set to \"EYE-ra\" (ˈaɪɹə) in my voice profile.",
                     "I've noted the pronunciation of your name.", "Ira is now pronounced EYE-ra."):
            with self.subTest(text=text):
                self.assertTrue(claimed_to_note_a_pronunciation(text, listing))

    def test_ordinary_talk_is_not_a_claim(self):
        for text in ("Your name is said sah-EED, isn't it?",
                     "I noted the shopping list you gave me.",
                     "Sah-EED."):
            self.assertEqual(claimed_to_note_a_pronunciation(text, _session()), "", text)


if __name__ == "__main__":
    unittest.main()
