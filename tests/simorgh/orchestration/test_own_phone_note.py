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
