"""Farsi words said in the house's own sounds (`tts_farsi_lexicon`).

Measured 2026-09-27: Pocket's G2P reads سعید as s/@id -- the ع a glottal
stop, the Arabic sound the creator did not want in his name -- and no
vowel marks change that (its normaliser drops them, and in a sentence
the G2P already resolves homographs from context)."""

import unittest

from simorgh.voice.config import Config
from simorgh.voice.tts.pocket import parse_lexicon
from simorgh.voice.tts.servers.pocket_server import with_lexicon


class FarsiLexicon(unittest.TestCase):
    def test_the_default_says_the_name_without_the_stop(self):
        self.assertEqual(parse_lexicon(Config().tts_farsi_lexicon), {"سعید": "s/id"})

    def test_a_malformed_entry_is_skipped(self):
        self.assertEqual(parse_lexicon("سعید=s/id; nonsense; =x; y="), {"سعید": "s/id"})

    def test_replaced_by_position_punctuation_aside(self):
        got = with_lexicon("سلام سعید، امروز هوا آفتابیه و گرمه.",
                           "s/lam s/@id @emruz h/va @aftabiye v/ g/rme", {"سعید": "s/id"})
        self.assertEqual(got, "s/lam s/id @emruz h/va @aftabiye v/ g/rme")

    def test_nothing_replaced_when_the_words_do_not_line_up(self):
        self.assertEqual(with_lexicon("سلام سعید", "s/lam s/@id x", {"سعید": "s/id"}), "s/lam s/@id x")

    def test_it_is_a_safe_setting(self):
        from simorgh.contracts.settings import VOICE_SAFE_KEYS

        self.assertIn("tts_farsi_lexicon", VOICE_SAFE_KEYS)


if __name__ == "__main__":
    unittest.main()
