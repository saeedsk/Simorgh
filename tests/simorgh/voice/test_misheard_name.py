"""'Hey Sim' misheard as 'A-seam.' is still Sim's name (live 2026-09-15)."""

import unittest

from simorgh.orchestration import profiles, scaffolds
from simorgh.voice.session import VoiceSession


class MisheardName(unittest.TestCase):
    def test_seam_forms_name_sim(self):
        for heard in ("A-seam.", "Hey seam", "Seam, are you there?", "Seem?", "Sima"):
            self.assertTrue(VoiceSession._names_sim(heard), heard)

    def test_ordinary_words_do_not(self):
        for heard in ("the seamstress came", "similar to that", "AC is on", "simple"):
            self.assertFalse(VoiceSession._names_sim(heard), heard)

    def test_the_voice_rules_say_a_bare_name_is_a_call(self):
        text = scaffolds.render(profiles.CHAT, channel="voice")
        self.assertIn('"A-seam"', text)
        self.assertIn("never QUIET", text)


if __name__ == "__main__":
    unittest.main()
