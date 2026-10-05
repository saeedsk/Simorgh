"""A turn from someone's own paired phone says so in the prompt.

Live, 2026-09-27: once the creator's phone had an owner, the model still
answered "this channel can't verify you" -- its own earlier refusals were
all it had to go on."""

import unittest

from simorgh.orchestration.scaffolds import own_phone_note


class OwnPhoneNote(unittest.TestCase):
    def test_names_the_owner_and_does_not_refuse_ahead_of_guardian(self):
        note = own_phone_note("Saeed")
        self.assertIn("Saeed's own paired phone", note)
        self.assertIn("never refuse ahead of it", note)



class FarsiVowels(unittest.TestCase):
    """2026-09-27: «یکی ترک می‌گه» was said "ta-ra-k" where "tork" was meant."""

    def test_a_spoken_reply_is_asked_to_mark_words_that_read_two_ways(self):
        from simorgh.orchestration import scaffolds

        self.assertIn("تُرک", scaffolds.FARSI_VOWELS)
        self.assertIn("ezafe", scaffolds.FARSI_VOWELS)

    def test_few_marks_only_when_sure_and_poems_from_their_text(self):
        """Live 2026-09-27: marks on nearly every word, «دُلِ» for «دلِ», a
        misquoted Hafez, and the model talking about its marks."""
        from simorgh.orchestration import scaffolds

        for said in ("wherever it is read", "only when you are", "Never talk about the marks", "exact text",
                     "generously", "the slips are the recogniser's", "foreign word"):
            self.assertIn(said, scaffolds.FARSI_VOWELS)


if __name__ == "__main__":
    unittest.main()


class WhereYouRun(unittest.TestCase):
    """Live, 2026-09-29, from the phone: "I can't reach the MacBook's
    processes from here" and "Tailscale isn't installed on this host"."""

    def test_a_phone_or_spoken_turn_is_told_which_machine_sim_is(self):
        from simorgh.orchestration import profiles
        from simorgh.orchestration.scaffolds import render

        for channel, profile in (("api", profiles.CHAT), ("voice", profiles.VOICE_CHAT)):
            with self.subTest(channel=channel):
                body = render(profile, channel=channel, speaker="Saeed")
                self.assertIn("You run on the computer called", body)
                self.assertIn("never say you cannot reach it", body)

    def test_a_task_session_is_not(self):
        from simorgh.orchestration import profiles
        from simorgh.orchestration.scaffolds import render

        self.assertNotIn("You run on the computer called", render(profiles.PATCH, task="x", subject="a.py"))


class CasualTehraniNotFormal(unittest.TestCase):
    """The creator, 2026-10-04: "I don't like when sim talks formal ... for
    Farsi I prefer casual Farsi, as spoken in Tehran"."""

    def test_every_conversation_is_told_to_talk_casually(self):
        from simorgh.orchestration import profiles
        from simorgh.orchestration.scaffolds import SPEAKING_STYLE, render

        for channel, profile in (("voice", profiles.VOICE_CHAT), ("api", profiles.CHAT), ("cli", profiles.CHAT)):
            with self.subTest(channel=channel):
                self.assertIn(SPEAKING_STYLE, render(profile, channel=channel, speaker="Saeed"))
        self.assertIn("محاوره‌ی تهرانی", SPEAKING_STYLE)
        self.assertIn("Poems, quotes and names stay exactly as written", SPEAKING_STYLE)

    def test_a_code_task_is_not(self):
        from simorgh.orchestration import profiles
        from simorgh.orchestration.scaffolds import SPEAKING_STYLE, render

        self.assertNotIn(SPEAKING_STYLE, render(profiles.PATCH, task="x", subject="a.py"))
