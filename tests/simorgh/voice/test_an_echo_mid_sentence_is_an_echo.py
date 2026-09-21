"""Sim's own reply, heard while it is still saying it.

Live, 2026-09-21. The creator asked how Sim was; Sim answered "Doing
well, Saeed - quiet afternoon, all systems steady. How are you?"; the
microphone picked that up and it was written down as HIS turn:

    🎤 Saeed: Hey, Sim. How are you doing today?  (0.47)
      ⎿ completed -- Doing well, Saeed - quiet afternoon, all systems steady...
      🎤 listening...
    🎤 you: Doing well, Saeed Khwai.
      🤫 not for me -- staying quiet
    🔊 sim: Doing well, Saeed - quiet afternoon, all systems steady.

Note the order: the echo was transcribed BEFORE the spoken line
printed. A quiet rule happened to catch it, which is luck -- an echo
worded a little differently is answered.

The two halves of a reply are written down at different moments:
`recent_said` and `speaking` before the audio goes out, `_sim_spoke_at`
and `last_said` only once it has finished. So an echo arriving
mid-sentence found `recent_said` already holding the reply and
`_sim_spoke_at` still on the previous turn -- `in_exchange_now` false,
and the check fell through to `is_echo` against the reply BEFORE this
one.
"""

import unittest

from simorgh.voice.pipeline import echoes_recent, is_echo

REPLY = "Doing well, Saeed — quiet afternoon, all systems steady. How are you?"
HEARD = "Doing well, Saeed Khwai."
EARLIER = "The kitchen light is on."


class TheMatcherWasNeverTheProblem(unittest.TestCase):
    def test_the_live_fragment_matches_the_live_reply(self):
        """`echoes_recent` catches this pair. It was never asked."""
        self.assertTrue(echoes_recent(HEARD, [REPLY]))

    def test_and_does_not_match_the_previous_reply(self):
        """Which is what the code compared it against instead."""
        self.assertFalse(is_echo(HEARD, EARLIER))


class TheBranchIsChosenOnWhetherSimIsSpeaking(unittest.TestCase):
    """Read off the source: the condition has to include `speaking`,
    because `_sim_spoke_at` cannot have been updated yet while the
    audio is still going out."""

    @staticmethod
    def _source() -> str:
        from pathlib import Path

        return (Path(__file__).resolve().parents[3] / "simorgh" / "voice" / "session.py").read_text()

    def test_speaking_now_takes_the_recent_said_branch(self):
        self.assertIn("if (in_exchange_now or self._pipeline.speaking)", self._source())

    def test_recent_said_is_still_filled_before_playback(self):
        """The fix depends on it: the ring must already hold the reply
        when the echo arrives, and that was fixed on 2026-09-17."""
        source = self._source()
        append = source.index("self._pipeline.recent_said.append(said)")
        played = source.index("self._sim_spoke_at = self._now()", append)
        self.assertLess(append, played, "the ring is filled before the audio, not after")

    def test_speaking_is_set_before_playback_too(self):
        source = self._source()
        speaking = source.index("self._pipeline.speaking = True")
        spoke_at = source.index("self._sim_spoke_at = self._now()", speaking)
        self.assertLess(speaking, spoke_at)


if __name__ == "__main__":
    unittest.main()
