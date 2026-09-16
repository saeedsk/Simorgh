"""A reply must not describe what no tool did, nor promise what nothing
keeps (orchestration/session.py)."""

from __future__ import annotations

import types
import unittest

from simorgh.orchestration.session import claimed_to_commit, promised_behaviour


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

    def test_an_answer_that_promises_nothing_is_left_alone(self):
        self.assertEqual(promised_behaviour("That's COIN, down 8.2%.", _session()), "")
        self.assertEqual(promised_behaviour("I'll check the camera now.", _session()), "")


if __name__ == "__main__":
    unittest.main()
