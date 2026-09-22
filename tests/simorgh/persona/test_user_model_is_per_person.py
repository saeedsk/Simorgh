"""Stage 6 item 4: the user model is per person, and a sentence nobody can
be named for is not extracted at all (World Model's side, and the two
services together, are in tests/simorgh/worldmodel/test_preferences_belong
_to_the_speaker.py)."""

import unittest

from simorgh.persona.user_model import OWNER, UserModel, attribute


class Attribution(unittest.TestCase):
    def test_a_named_speaker_is_that_person(self):
        self.assertEqual(attribute({"channel": "voice", "speaker": "Ira"}), "Ira")
        self.assertEqual(attribute({"channel": "telegram", "speaker": "Soodeh"}), "Soodeh")

    def test_the_console_is_the_owner(self):
        """Same convention as guardian/tiers.py::role_of."""
        self.assertEqual(attribute({"channel": "cli"}), OWNER)
        self.assertEqual(attribute({"channel": ""}), OWNER)

    def test_nobody_else_is_anybody(self):
        self.assertIsNone(attribute({"channel": "voice"}))                     # an unplaced voice
        self.assertIsNone(attribute({"channel": "api"}))                       # the dashboard
        self.assertIsNone(attribute({"channel": "chat"}))
        self.assertIsNone(attribute({"channel": "voice", "speaker": "Iris",
                                     "speaker_doubt": "Ira sounds almost the same"}))


    def test_the_console_is_the_one_in_contracts(self):
        """One convention (2026-09-22): `contracts/channels.py`."""
        from simorgh.contracts import channels
        from simorgh.persona.user_model import CONSOLE_CHANNELS
        self.assertIs(CONSOLE_CHANNELS, channels.CONSOLE_CHANNELS)
        for channel in channels.ALL + ("",):
            self.assertEqual(attribute({"channel": channel}) == OWNER, channels.is_console(channel), channel)

    def test_a_doubtful_voice_is_nobody_whoever_it_names(self):
        for doubt in ("Ira sounds almost the same", " maybe "):
            self.assertIsNone(attribute({"channel": "voice", "speaker": "Saeed", "speaker_doubt": doubt}))
        # ...and doubt on the console does not make the owner somebody else.
        self.assertIsNone(attribute({"channel": "cli", "speaker": "Ira", "speaker_doubt": "guessed"}))
        # A blank doubt is no doubt.
        self.assertEqual(attribute({"channel": "voice", "speaker": "Ira", "speaker_doubt": "  "}), "Ira")


class PerPerson(unittest.TestCase):
    def test_one_persons_facets_never_merge_with_anothers(self):
        model = UserModel()
        model.extract_from_text("call me Ira-bear", ts=0.0, source_ref="r", person="Ira")
        model.extract_from_text("call me Dad", ts=0.0, source_ref="r", person=OWNER)
        self.assertEqual(model.facets("Ira")["preferred_name"].value, "Ira-bear")
        self.assertEqual(model.facets(OWNER)["preferred_name"].value, "Dad")
        # Two different people saying two different names is not a
        # "conflicting observation" that halves anybody's confidence.
        self.assertEqual(model.facets("Ira")["preferred_name"].confidence, 0.7)

    def test_a_hyphenated_name_is_kept_whole(self):
        found = UserModel().extract_from_text("please call me Ira-bear!", ts=0.0, source_ref="r", person="Ira")
        self.assertIn(("preferred_name", "Ira-bear"), found)


if __name__ == "__main__":
    unittest.main()
