"""A drift review asks a real model a real question, so it must wait
long enough for one candidate to answer.

`review_timeout_s` is not one provider's timeout: it is the deadline
Cognition SHARES between candidates (`router._share_of`:
`remaining / (still to try + 1)`, never below `_MIN_CANDIDATE_SECONDS`).
At 8 s over the `review` route's two providers, each got the 5 s floor --
a slice smaller than the work, handed out anyway. Live on 2026-09-22:
`Together request failed after 5.1s of 5.0s`. Because these reviews pass
`require_real_provider: False`, the monitor then read "unknown" rather
than reporting that it never got an answer, so the drift check looked
like it was working.
"""

import unittest

from simorgh.cognition.router import _MIN_CANDIDATE_SECONDS
from simorgh.growth.monitors.config import Config

CANDIDATES = 2          # `[cognition.routes] review = ["together_strong", "together"]`


class ADriftReviewGetsAnAnswer(unittest.TestCase):
    def test_a_candidate_gets_more_than_the_floor(self):
        share = Config().review_timeout_s / (CANDIDATES + 1)
        self.assertGreater(share, _MIN_CANDIDATE_SECONDS,
                           "a slice at the floor is not a chance to answer, it is a billed call thrown away")

    def test_and_enough_for_a_real_review_call(self):
        # Measured live 2026-09-22: `review` calls to together_strong ran
        # 0.7 s mean, 1.6 s max over 60 calls -- but the tail is what the
        # floor was cutting off.
        self.assertGreaterEqual(Config().review_timeout_s / (CANDIDATES + 1), 15.0)


if __name__ == "__main__":
    unittest.main()
