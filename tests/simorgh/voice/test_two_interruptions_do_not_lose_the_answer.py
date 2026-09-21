"""Two people talking over a slow answer used to lose it entirely.

Live, 2026-09-21. The twins were talking in the room while a reply
waited on a 9.1-second failover to Gemini:

    🎤 Iris?: You're not sim.  (0.54)
    ⏺ 💬 chat · voice · You're not sim.  [d20a309e]
    🎤 Ira?: But it's only that one part.
    🎤 Iris: Okay, let me do the one part.
    [warning] thinking moved from together to gemini
      ⎿ completed in 9.1s -- I really am Sim! Who else would be right here chatting with you?

There is no `🔊 sim:` line. The creator heard nothing at all.

`_superseded` held ONE turn. The comment above it records the
2026-09-13 fix for exactly this shape -- "a 15 s answer was dropped
because the creator spoke meanwhile ... and Sim was blamed for
silence" -- and a single slot only survives ONE interruption. The
second overwrote the first, so when the answer arrived it matched
neither `_asked_turn` nor `_superseded` and was dropped without a
word.

Every final transcript takes the slot, whatever the quiet rules
decide afterwards, so a room with two children in it fills it in
seconds.
"""

import unittest

from simorgh.voice.api import TranscriptEvent, VadEvent
from simorgh.voice.turns import OWED_KEPT, THINKING, Actions, TurnManager


def _kinds(actions):
    return [a.kind for a in actions]


def _hear(tm: TurnManager, text: str) -> int:
    """One complete utterance; returns the turn it was heard as."""
    tm.handle_vad(VadEvent("speech_start", speech_ms=30))
    turn = tm.turn_id
    tm.handle_transcript(TranscriptEvent("final", text, turn))
    return turn


class AnAnswerSurvivesInterruptions(unittest.TestCase):
    def setUp(self):
        self.tm = TurnManager()
        self.tm.start()

    def test_one_interruption(self):
        """Already true before today, and must stay true."""
        first = _hear(self.tm, "you're not sim")
        _hear(self.tm, "but it's only that one part")
        self.assertEqual(_kinds(self.tm.reply_ready(first)), [Actions.SPEAK])

    def test_two_interruptions_the_live_case(self):
        first = _hear(self.tm, "you're not sim")
        _hear(self.tm, "but it's only that one part")
        _hear(self.tm, "okay, let me do the one part")
        self.assertEqual(_kinds(self.tm.reply_ready(first)), [Actions.SPEAK],
                         "the creator heard nothing at all here")

    def test_three(self):
        first = _hear(self.tm, "you're not sim")
        for text in ("one", "two", "three"):
            _hear(self.tm, text)
        self.assertEqual(_kinds(self.tm.reply_ready(first)), [Actions.SPEAK])

    def test_the_newest_turn_is_still_answered_normally(self):
        _hear(self.tm, "you're not sim")
        newest = _hear(self.tm, "what time is it")
        self.assertEqual(_kinds(self.tm.reply_ready(newest)), [Actions.SPEAK])


class WhatIsStillDropped(unittest.TestCase):
    def setUp(self):
        self.tm = TurnManager()
        self.tm.start()

    def test_a_turn_nobody_ever_asked(self):
        _hear(self.tm, "you're not sim")
        self.assertEqual(_kinds(self.tm.reply_ready(9999)), [Actions.DROP_REPLY])

    def test_the_owed_list_is_bounded(self):
        """Beyond a handful the oldest answer is stale enough that
        saying it would be worse than the silence."""
        first = _hear(self.tm, "the first thing")
        for i in range(OWED_KEPT + 3):
            _hear(self.tm, f"interruption {i}")
        self.assertEqual(_kinds(self.tm.reply_ready(first)), [Actions.DROP_REPLY])

    def test_answering_the_newest_clears_what_was_owed(self):
        """Once the newer turn is answered the older ones are stale --
        the rule the single slot was written for."""
        first = _hear(self.tm, "you're not sim")
        newest = _hear(self.tm, "what time is it")
        self.tm.reply_ready(newest)
        self.assertEqual(_kinds(self.tm.reply_ready(first)), [Actions.DROP_REPLY])


class TheLateAnswerStillSaysSo(unittest.TestCase):
    def test_it_is_spoken_with_a_reason(self):
        tm = TurnManager()
        tm.start()
        first = _hear(tm, "you're not sim")
        _hear(tm, "but it's only that one part")
        _hear(tm, "okay, let me do the one part")
        [action] = tm.reply_ready(first)
        self.assertEqual(tm.state, THINKING)
        self.assertIn("late", action.reason)


if __name__ == "__main__":
    unittest.main()
