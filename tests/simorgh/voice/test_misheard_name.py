"""'Hey Sim' misheard as 'A-seam.' is still Sim's name (live 2026-09-15)."""

import unittest

from simorgh.orchestration import profiles, scaffolds
from simorgh.voice.session import VoiceSession


class MisheardName(unittest.TestCase):
    def test_seam_forms_name_sim(self):
        for heard in ("A-seam.", "Hey seam", "Seam, are you there?", "Seem?", "Sima",
                      "Hey Seym are you there?", "Syme, what time is it"):
            self.assertTrue(VoiceSession._names_sim(heard), heard)

    def test_ordinary_words_do_not(self):
        for heard in ("the seamstress came", "similar to that", "AC is on", "simple"):
            self.assertFalse(VoiceSession._names_sim(heard), heard)

    def test_the_voice_rules_say_a_bare_name_is_a_call(self):
        text = scaffolds.render(profiles.CHAT, channel="voice")
        self.assertIn('"A-seam"', text)
        self.assertIn("never QUIET", text)


class CourtesyAside(unittest.TestCase):
    """"- I'm sorry." said to someone on a call was answered aloud (2026-09-15)."""

    @staticmethod
    def _aside(text: str) -> bool:
        session = VoiceSession.__new__(VoiceSession)
        session._now = lambda: 1000.0                      # noqa: SLF001
        session._sim_spoke_at = -1e9                       # noqa: SLF001
        session._config = type("C", (), {"exchange_window_s": 20.0})()   # noqa: SLF001
        return VoiceSession._courtesy_aside(session, text)

    def test_apologies_and_thanks_are_asides(self):
        for text in ("- I'm sorry.", "I'm so sorry", "my bad", "thank you so much", "okay, sure"):
            self.assertTrue(self._aside(text), text)

    def test_real_turns_are_not(self):
        for text in ("I'm hungry", "sorry, what did you say about the lights", "Sim, thank you"):
            self.assertFalse(self._aside(text), text)


if __name__ == "__main__":
    unittest.main()


class NotANameTestCase(unittest.TestCase):
    """"Myself" was enrolled as a person (live 2026-09-15): asked "what is
    your name?", a bare word answer is taken as the name, and the reflexive
    pronouns were not on the list of words that are not names."""

    def test_pronouns_are_not_names(self):
        from simorgh.voice.introduce import name_in

        for text in ("Myself.", "myself", "It's myself", "yourself", "This is himself", "mine"):
            self.assertEqual(name_in(text), "", text)

    def test_real_names_still_pass(self):
        from simorgh.voice.introduce import name_in

        self.assertEqual(name_in("my name is Aran"), "Aran")
        self.assertEqual(name_in("Iris."), "Iris")
        self.assertEqual(name_in("I'm Soodeh"), "Soodeh")
