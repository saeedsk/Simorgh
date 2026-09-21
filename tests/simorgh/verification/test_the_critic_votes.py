"""Ending an attempt takes more than one cheap sample (stage 7 item 6).

The critic runs at every progress note on the cheap tier, and two
`drifting` verdicts in a row throw away everything the attempt has
done. That is a large consequence for a single sample of a small
model, which is why the plan asks for a majority of three.

Three at every note would be three times the cost of a question whose
answer is usually "yes, fine", so the vote is spent where it changes
something: `on_track` and `insufficient_evidence` both mean carry on,
which is what happens anyway, and only a verdict that would end the
attempt is worth asking twice more about.
"""

import unittest

from simorgh.verification.checkpoint import ACTIONABLE, SAMPLES, majority, wants_confirming


class WhichVerdictsAreWorthConfirming(unittest.TestCase):
    def test_only_the_ones_that_change_something(self):
        for verdict in ACTIONABLE:
            self.assertTrue(wants_confirming(verdict), verdict)
        for verdict in ("on_track", "insufficient_evidence", "", "nonsense"):
            self.assertFalse(wants_confirming(verdict), verdict)

    def test_three_samples(self):
        self.assertEqual(SAMPLES, 3)


class TheVote(unittest.TestCase):
    def test_two_of_three_agreeing_carries_the_verdict(self):
        answer = majority([{"verdict": "drifting", "why": "first"},
                           {"verdict": "on_track"},
                           {"verdict": "drifting", "why": "third"}])
        self.assertEqual(answer["verdict"], "drifting")
        self.assertEqual(answer["votes"], "2/3")
        self.assertEqual(answer["why"], "first", "the reasoning comes from a sample that agreed")

    def test_no_agreement_decides_nothing(self):
        """Three samples, three answers. A plurality of one is the
        single sample this vote exists to stop trusting."""
        answer = majority([{"verdict": "drifting", "why": "first"},
                           {"verdict": "on_track"},
                           {"verdict": "blocked"}])
        self.assertEqual(answer["verdict"], "insufficient_evidence")
        self.assertIn("did not agree", answer["why"])

    def test_that_cuts_both_ways(self):
        """An encouraging plurality of one is no better evidence than
        a damning one."""
        answer = majority([{"verdict": "on_track"},
                           {"verdict": "drifting"},
                           {"verdict": "insufficient_evidence"}])
        self.assertEqual(answer["verdict"], "insufficient_evidence")

    def test_a_critic_that_could_not_read_the_trajectory_gets_a_vote(self):
        """Two unreadable replies out of three have not established
        drifting, and abandoning an attempt on that is the rubber
        stamp in reverse."""
        answer = majority([{"verdict": "drifting", "why": "first"},
                           {"verdict": "insufficient_evidence"},
                           {"verdict": "insufficient_evidence"}])
        self.assertEqual(answer["verdict"], "insufficient_evidence")
        self.assertEqual(answer["votes"], "2/3")

    def test_one_sample_stands_alone(self):
        self.assertEqual(majority([{"verdict": "blocked"}])["votes"], "1/1")

    def test_nobody_asked_is_not_a_verdict(self):
        self.assertEqual(majority([])["verdict"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
