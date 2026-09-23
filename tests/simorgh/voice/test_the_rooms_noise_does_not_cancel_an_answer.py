"""A turn that was not for Sim must not cancel the answer Sim owes.

The creator, 2026-09-22: "in general sim skips responding me, i see the
reply on screen within an accepted response time but many times I don't
hear the voice". Measured that evening: nine replies dropped with
`reason='a later turn was asked'`, while the room ran at ~6 voice turns
a minute.

The later turn was usually the ROOM -- the TV, the twins, a passing
sentence. It became a turn, went to the model, came back "not for me",
and was discarded... but it had already taken the floor from the
question that was really waiting. With enough of them the real turn fell
off `_superseded` (OWED_KEPT slots) and its answer was dropped.

`_repeat_waits` had always withdrawn a turn that asked nothing. The
quiet path had not.
"""

import unittest

from simorgh.voice.api import TranscriptEvent, VadEvent
from simorgh.voice.turns import OWED_KEPT, Actions, TurnManager


def _hear(tm: TurnManager, text: str) -> int:
    tm.handle_vad(VadEvent("speech_start", speech_ms=30))
    turn = tm.turn_id
    tm.handle_transcript(TranscriptEvent("final", text, turn))
    return turn


def _kinds(actions):
    return [a.kind for a in actions]


class TheRoomsNoiseDoesNotCancelAnAnswer(unittest.TestCase):
    def setUp(self):
        self.tm = TurnManager()
        self.tm.start()

    def _stayed_quiet(self, turn: int) -> None:
        """What `session._stay_quiet` does to the turn manager."""
        self.tm.quiet_reply(turn)

    def test_a_turn_that_was_not_for_sim_gives_the_floor_back(self):
        mine = _hear(self.tm, "hey sim, what's the conversation history with Said?")
        tv = _hear(self.tm, "I can't erase this moment. It's only one side.")
        self._stayed_quiet(tv)
        self.assertEqual(self.tm.asked_turn, mine, "the question is still the one being answered")
        self.assertEqual(_kinds(self.tm.reply_ready(mine)), [Actions.SPEAK])

    def test_a_roomful_of_them_still_leaves_the_question_owed(self):
        """The live shape: the answer took ~20 s and the room filled the
        owed list with chatter meant for nobody."""
        mine = _hear(self.tm, "hey sim, what's on my calendar tomorrow?")
        for i in range(OWED_KEPT + 4):
            self._stayed_quiet(_hear(self.tm, f"television dialogue {i}"))
        self.assertEqual(_kinds(self.tm.reply_ready(mine)), [Actions.SPEAK],
                         "nine of these were dropped in one evening")

    def test_a_real_later_question_still_supersedes(self):
        """The rule that stays: somebody who asks something new has moved
        on, and the old answer is not spoken over the new one."""
        first = _hear(self.tm, "what time is it")
        for i in range(OWED_KEPT + 3):
            _hear(self.tm, f"and another real question {i}")
        self.assertEqual(_kinds(self.tm.reply_ready(first)), [Actions.DROP_REPLY])


if __name__ == "__main__":
    unittest.main()
