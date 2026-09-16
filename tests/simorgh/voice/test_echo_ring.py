"""Sim's own voice coming back through the microphone (voice/pipeline.py).

Live 2026-09-15: a spoken reply was picked up by the microphone,
transcribed as the creator, and answered -- which produced another
reply, which was heard again. Eighteen turns queued, replies arriving
fifty seconds late, and one echo attributed to an enrolled person.
"""

from __future__ import annotations

import unittest

from simorgh.voice.pipeline import echoes_recent, is_echo

REPLY = ("Hot stocks right now biggest day movers: COIN -8.2%, SOUN -4.5%, SMCI -3.8%; "
         "ABNB is the fastest mover of the last 30m, up about 1%.")
LATER = "That's ABNB - the fastest mover of the last thirty minutes, up about one percent."


class FragmentsOfSimsOwnReply(unittest.TestCase):
    def test_a_short_fragment_is_caught_although_is_echo_cannot_see_it(self):
        """`is_echo` gives up below four words on purpose -- "Can you hear
        me?" must survive -- so short text needs a stricter test, not a
        looser one: every word of it, in order, inside what Sim said."""
        self.assertFalse(is_echo("minus 8.2%", REPLY), "the run matcher is too short-sighted here")
        self.assertTrue(echoes_recent("minus 8.2%", [REPLY]))

    def test_the_written_sign_and_the_heard_word_are_the_same_thing(self):
        """Sim writes "-8.2%", says "minus eight point two percent", and
        whisper writes that back as "minus 8.2%"."""
        self.assertTrue(echoes_recent("minus 4.5%", [REPLY]))

    def test_a_fragment_of_an_older_reply_still_counts(self):
        """The reason one string was not enough: by the time the second
        fragment arrived, `last_said` held the answer to the first."""
        self.assertTrue(echoes_recent("minus 8.2%", [REPLY, LATER]), "the older utterance is still in the ring")
        self.assertTrue(echoes_recent("Up about one.", [REPLY, LATER]))

    def test_a_long_echo_is_still_caught_the_old_way(self):
        self.assertTrue(echoes_recent("fastest mover of the last 30m up about 1%", [REPLY]))

    def test_nothing_recent_means_nothing_to_echo(self):
        self.assertFalse(echoes_recent("minus 8.2%", []))
        self.assertFalse(echoes_recent("", [REPLY]))


class RealSpeechSurvives(unittest.TestCase):
    """The failure that matters more than a missed echo: throwing away
    something a person actually said."""

    def test_short_questions_and_commands_are_not_echoes(self):
        for heard in ("Can you hear me?", "I said fix it.", "what is the time", "stop",
                      "yes please", "turn the lights off", "play 8 tracks", "no"):
            self.assertFalse(echoes_recent(heard, [REPLY, LATER]), heard)

    def test_a_single_word_is_never_an_echo(self):
        self.assertFalse(echoes_recent("percent", [REPLY]), "one word is not evidence")


if __name__ == "__main__":
    unittest.main()
