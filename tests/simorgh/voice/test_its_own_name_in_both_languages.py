"""Sim hears its own name the way whisper actually writes it.

Measured, not guessed: the creator's calibration set -- 60 takes that say
"Sim", his voice, his room -- replayed through the real recogniser on
2026-09-22. `_names_sim` recognised 14 of them.

Farsi was missing entirely, although `backchannel._NAMED` has carried
سیم all along: Sim was deaf to its own name in half the house. And
whisper writes the name as an ordinary English word where a name goes
("Zim paused the music", "See him, who came to the front door"), which
counts only in name position, because "see" and "team" are common words
anywhere else.
"""

import unittest

from simorgh.voice.backchannel import _NAMED
from simorgh.voice.session import VoiceSession

HEARD_AS = [
    "سیم هوای فرد و چطوره؟",                      # fa-002
    "سیم ممنون خیلی کمکم کردی",                    # fa-014
    "فکر کنم سیم باید زودتر را بیفتیم",            # fa-016
    "Zim paused the music.",                       # en-015
    "See him, who came to the front door this afternoon.",   # en-020
    "Team, what's the plan for tomorrow?",         # en-049
    "Sim, turn off the kitchen lights.",
]

NOT_ITS_NAME = [
    "I can see him over there in the driveway",
    "the team is coming over on Saturday",
    "that seemed to work",          # `seem` is deliberately IN the list; "seemed" is not
    "Turn off the kitchen lights.",
]


class SimHearsItsOwnName(unittest.TestCase):
    def test_every_way_the_recogniser_wrote_it(self):
        for heard in HEARD_AS:
            self.assertTrue(VoiceSession._names_sim(heard), heard)  # noqa: SLF001

    def test_and_not_the_same_words_where_a_name_is_not(self):
        for heard in NOT_ITS_NAME:
            self.assertFalse(VoiceSession._names_sim(heard), heard)  # noqa: SLF001

    def test_the_backchannel_agrees_about_farsi(self):
        """The two lists disagreeing is what hid this: one had سیم and
        the other did not."""
        for heard in HEARD_AS[:3]:
            self.assertTrue(_NAMED.search(heard), heard)


if __name__ == "__main__":
    unittest.main()
