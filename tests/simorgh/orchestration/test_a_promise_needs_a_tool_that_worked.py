"""A tool that RAN is not a tool that worked.

Live, 2026-09-22. Iris, a child, asked Sim not to cheer while she
played. The promise guard fired, and Sim did exactly the right thing:
it reached for `overheard_note` to make the promise real. Guardian
escalated that -- Iris is a child and the note is irreversible, so an
adult had to say yes. One second later, without waiting, Sim answered:

    I'll keep it, Iris -- no cheering, I'll just sit here quietly
    while you play. Good luck!

Forty-four seconds after that, the request was DENIED. She was promised
something no part of the system now remembers -- by the very turn this
guard had already corrected once.

The guard asked whether any tool had run. A denied one had.
`claimed_effect` in the same file has always asked whether one
SUCCEEDED, which is the question.
"""

import unittest

from simorgh.orchestration.stophook import claimed_tv_act, promised_behaviour

PROMISE = "I'll keep it, Iris -- no cheering, I'll just stay quiet while you play."


class _Step:
    def __init__(self, tool, ok=True, denied=False):
        self.tool, self.ok, self.denied = tool, ok, denied


class _Profile:
    scaffold = "chat"
    tools = ("overheard_note", "cast_show", "remember")


class _Session:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.profile = _Profile()
        self.user_text = "don't cheer for me while I play"


class APromiseNeedsAToolThatWorked(unittest.TestCase):
    def test_an_escalated_note_does_not_back_the_promise(self):
        """The live case: proposed, sent to a human, never approved."""
        session = _Session(_Step("overheard_note", ok=None))
        self.assertTrue(promised_behaviour(PROMISE, session),
                        "a note waiting on an adult keeps nothing yet")

    def test_a_denied_note_does_not_back_it_either(self):
        session = _Session(_Step("overheard_note", ok=False, denied=True))
        self.assertTrue(promised_behaviour(PROMISE, session))

    def test_a_note_that_was_written_does(self):
        session = _Session(_Step("overheard_note", ok=True))
        self.assertEqual(promised_behaviour(PROMISE, session), "",
                         "it is stored; the promise has something keeping it")

    def test_reading_something_never_backs_a_promise(self):
        session = _Session(_Step("read_file", ok=True), _Step("search_code", ok=True))
        self.assertTrue(promised_behaviour(PROMISE, session),
                        "reading is not remembering")

    def test_the_tv_guard_holds_to_the_same_rule(self):
        claim = "The K-pop chart is on the TV now."
        self.assertTrue(claimed_tv_act(claim, _Session(_Step("cast_show", ok=False))),
                        "a cast that failed left the screen as it was")
        self.assertEqual(claimed_tv_act(claim, _Session(_Step("cast_show", ok=True))), "")


if __name__ == "__main__":
    unittest.main()
