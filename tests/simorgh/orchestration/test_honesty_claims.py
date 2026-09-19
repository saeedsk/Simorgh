"""A reply must not describe what no tool did, nor promise what nothing
keeps (orchestration/session.py)."""

from __future__ import annotations

import types
import unittest

from simorgh.orchestration.stophook import claimed_to_commit, promised_behaviour


def _session(*, tools=("git_commit",), ran=False):
    step = types.SimpleNamespace(tool="git_commit" if ran else "")
    return types.SimpleNamespace(profile=types.SimpleNamespace(tools=tools), steps=[step], user_text="")


class ClaimingACommit(unittest.TestCase):
    """Live 2026-09-15: "The file is committed and callable the same way
    as my other skills" -- in the same turn the runner recorded
    "finished with uncommitted changes"."""

    def test_saying_it_is_committed_with_no_tool_run_is_caught(self):
        self.assertTrue(claimed_to_commit("The file is committed and callable.", _session()))

    def test_pushed_counts_too(self):
        self.assertTrue(claimed_to_commit("I pushed the change to main.", _session()))

    def test_a_real_commit_is_not_a_false_claim(self):
        self.assertEqual(claimed_to_commit("The file is committed.", _session(ran=True)), "")

    def test_ordinary_words_are_not_a_commit_claim(self):
        self.assertEqual(claimed_to_commit("I'm committed to getting this right for you.", _session()), "")
        self.assertEqual(claimed_to_commit("The kettle is on.", _session()), "")


class PromisingBehaviour(unittest.TestCase):
    """Live 2026-09-15, told the voices were the television: "so I'll
    stay quiet unless you address me directly" -- nothing stored, no
    setting changed, and the next unaddressed utterance answered as
    before."""

    def test_promising_to_stay_quiet_is_caught(self):
        self.assertTrue(promised_behaviour(
            "Right -- those are TV voices, so I'll stay quiet unless you address me directly.", _session()))

    def test_promising_to_remember_is_caught(self):
        self.assertTrue(promised_behaviour("I'll remember that for next time.", _session()))

    def test_the_three_it_missed_live(self):
        """A phrasebook catches the phrasings already seen. These three
        arrived within minutes of shipping the first version
        (2026-09-15/16), and the shape they share is a claim to RETAIN
        something with nothing retaining it."""
        for said in ("Noted — Majalli Xilqat. Who are they, Saeed — a friend?",
                     "Noted — I've got it. I'll keep that on file, Saeed.",
                     "so I'll treat those sounds as my name from now on, whether you say Sim or Seem"):
            self.assertTrue(promised_behaviour(said, _session()), said)

    def test_an_ordinary_opener_is_not_a_promise(self):
        """"Got it --" is how anyone starts a sentence. Live 2026-09-16,
        minutes after the widened guard shipped, it fired on "Got it --
        the kettle is on" and "Got it -- playing the K-pop chart",
        spending a correction step on turns that claimed nothing. Only
        "Noted -- X", which says X was recorded, belongs here."""
        for said in ("Got it — the kettle is on.",
                     "Got it — I'll check the camera now.",
                     "Got it — playing the K-pop chart.",
                     "Got it — that was COIN, down 8.2%.",
                     "Got it, Saeed."):
            self.assertEqual(promised_behaviour(said, _session()), "", said)

    def test_noted_followed_by_a_fact_still_counts(self):
        self.assertTrue(promised_behaviour("Noted — Majalli Xilqat.", _session()))
        self.assertTrue(promised_behaviour("Noted — I've got it. I'll keep that on file.", _session()))

    def test_other_ways_of_claiming_to_keep_something(self):
        for said in ("I'll note that for next time.", "I've stored that against your name.",
                     "I'll hold on to it.", "From now on I'll remember it."):
            self.assertTrue(promised_behaviour(said, _session()), said)

    def test_an_answer_that_promises_nothing_is_left_alone(self):
        self.assertEqual(promised_behaviour("That's COIN, down 8.2%.", _session()), "")
        self.assertEqual(promised_behaviour("I'll check the camera now.", _session()), "")
        self.assertEqual(promised_behaviour("Got it.", _session()), "", "a plain acknowledgement is not a promise")
        self.assertEqual(promised_behaviour("I noted the time was 9pm in your message.", _session()), "",
                         "reporting what it read is not claiming to keep it")
        self.assertEqual(promised_behaviour("I'll treat that as a yes and turn the lights off.", _session()), "",
                         "treating something as X for THIS turn is not a standing change")


if __name__ == "__main__":
    unittest.main()
