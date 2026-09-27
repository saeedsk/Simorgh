"""An aside is said in the language Sim is answering in, or not at all.

2026-09-27, on the satellite: the creator asked in Farsi, turbo's draft
wrote "Sim, I'm not going to go.", the "aha" went out in English --
Kokoro, a woman's voice -- and the Farsi answer after it in Pocket's
cloned voice, a man's. "Why did you switch between a woman's and a
man's voice in Farsi?"
"""

import unittest
from types import SimpleNamespace

from simorgh.voice.session import VoiceSession


def _aside(heard: str, last_said: str, tts_farsi: str = "piper") -> str:
    fake = SimpleNamespace(_voice_room=SimpleNamespace(last_said=last_said),
                           _config=SimpleNamespace(tts_farsi=tts_farsi))
    return VoiceSession._aside_language(fake, heard)  # noqa: SLF001


class AnAsideKeepsTheVoice(unittest.TestCase):
    def test_a_farsi_conversation_misheard_as_english_says_nothing(self):
        self.assertEqual(_aside("Sim, I'm not going to go.", "باشه سعید، اشکالی نداره."), "")

    def test_an_english_conversation_misheard_as_farsi_says_nothing(self):
        self.assertEqual(_aside("سیم چراغ رو خاموش کن", "The kitchen lights are off."), "")

    def test_agreeing_languages_are_said(self):
        self.assertEqual(_aside("سیم هنوز صدامو میشنوی؟", "آره سعید."), "fa")
        self.assertEqual(_aside("Sim, what time is it?", "It's ten past nine."), "en")

    def test_before_sim_has_said_anything_the_heard_language_stands(self):
        self.assertEqual(_aside("سیم سلام", ""), "fa")
        self.assertEqual(_aside("Sim, hello", ""), "en")


    def test_no_farsi_aside_while_pocket_speaks_farsi(self):
        """Pocket says its reference clip's words for a line that short."""
        self.assertEqual(_aside("سیم هنوز صدامو میشنوی؟", "آره سعید.", tts_farsi="pocket"), "")
        self.assertEqual(_aside("سیم هنوز صدامو میشنوی؟", "آره سعید.", tts_farsi="auto"), "")
        self.assertEqual(_aside("Sim, what time is it?", "It's nine.", tts_farsi="pocket"), "en")


if __name__ == "__main__":
    unittest.main()
