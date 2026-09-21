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


class AHouseholdNameKeepsItsSpelling(unittest.TestCase):
    """The creator, out loud on 2026-09-20, correcting Sim: "Ira and
    not Aira."

    Whisper writes a short unusual name the way it sounds, and one
    misspelling costs three things at once -- the vocative rule stops
    recognising her, the memory stores a person who does not exist,
    and the screen shows the wrong name to the person who chose it.

    Rewriting what somebody actually said is the rudest thing this
    module does, so the rule is narrow: one letter from a name of
    somebody who lives here, added or dropped only at three letters,
    and never an ordinary English word.
    """

    NAMES = ("Ira", "Iris", "Aran", "Soodeh", "Saeed")

    def _spell(self, text):
        from simorgh.voice.backchannel import spell_household_names

        return spell_household_names(text, self.NAMES)

    def test_the_name_the_creator_corrected(self):
        self.assertEqual(self._spell("Aira, put your shoes on"), "Ira, put your shoes on")

    def test_somebody_else_is_never_renamed_into_the_family(self):
        """A substitution in a three-letter name turns one person into
        another, which is worse than any misspelling."""
        for text in ("Ida called me", "I met Aaron yesterday", "tell Iran about it"):
            self.assertEqual(self._spell(text), text)

    def test_ordinary_words_are_left_alone(self):
        for text in ("a new era began", "the air is cold", "Irish coffee", "the iris is open"):
            self.assertEqual(self._spell(text), text)

    def test_a_correct_spelling_survives_untouched(self):
        self.assertEqual(self._spell("Ira is singing and Aran is asleep"),
                         "Ira is singing and Aran is asleep")

    def test_no_names_means_no_rewriting(self):
        from simorgh.voice.backchannel import spell_household_names

        self.assertEqual(spell_household_names("Aira, put your shoes on", ()), "Aira, put your shoes on")
