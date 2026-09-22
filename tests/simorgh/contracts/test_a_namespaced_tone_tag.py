"""`[c.playful]` is a tone tag, and it was being read out loud.

Live, 2026-09-21, twice in one conversation:

    🔊 sim: [c.bright] Still the same answer, Saeed -- no number
            without an enrolment.

The tag reached the screen AND the speaker, which said it. `[playful]`
has always been understood; `[c.playful]` was not, because `_TAG`
did not allow a dot inside the token, so the tag never matched at
all and travelled through as ordinary words.

The `c.` is the model's own invention and there is no list of such
prefixes worth keeping. What settles it is whether the last part
names a feeling Sim knows.
"""

import unittest

from simorgh.contracts.tone import split_tone


class ANamespacedTagIsUnderstood(unittest.TestCase):
    def test_the_two_the_creator_heard(self):
        self.assertEqual(split_tone("[c.bright] Still the same answer, Saeed."),
                         ("bright", "Still the same answer, Saeed."))
        self.assertEqual(split_tone("[c.playful] Same as before, Saeed."),
                         ("playful", "Same as before, Saeed."))

    def test_other_prefixes_too(self):
        self.assertEqual(split_tone("[voice.warm] Hello.")[0], "warm")
        self.assertEqual(split_tone("[tone:calm] Fine.")[0], "calm")

    def test_an_alias_after_the_prefix(self):
        self.assertEqual(split_tone("[c.happy] Good news.")[0], "bright")

    def test_a_prefix_on_something_that_is_not_a_tone_is_still_dropped(self):
        """It is plainly a tag, whatever it names -- it must not be
        spoken, and it is not a feeling either."""
        self.assertEqual(split_tone("[c.unknownthing] Hi."), ("", "Hi."))


class WhatMustNotChange(unittest.TestCase):
    def test_a_plain_tag_still_works(self):
        self.assertEqual(split_tone("[warm] Hello."), ("warm", "Hello."))

    def test_prose_in_brackets_is_untouched(self):
        """The dot is allowed in a SINGLE token only. Allowing it in
        the multi-word form swallowed this, which is a sentence and
        not a tag."""
        self.assertEqual(split_tone("[see the file.txt] is prose"),
                         ("", "[see the file.txt] is prose"))

    def test_a_ticker_in_capitals_is_text(self):
        self.assertEqual(split_tone("[NVDA] is a ticker"), ("", "[NVDA] is a ticker"))

    def test_the_scores_glm_opened_with_are_still_dropped(self):
        self.assertEqual(split_tone("[sd:0.55, sv:0.45] Sah-EED."), ("", "Sah-EED."))

    def test_several_words_still_give_the_feeling_among_them(self):
        self.assertEqual(split_tone("[loud and warm] Hello.")[0], "warm")


if __name__ == "__main__":
    unittest.main()
