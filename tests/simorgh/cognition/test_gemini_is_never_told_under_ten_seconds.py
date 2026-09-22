"""Gemini refuses a request whose deadline is under 10 s.

`400 INVALID_ARGUMENT: Manually set deadline 8s is too short. Minimum
allowed deadline is 10s.` Cognition's `review` slice is 8 s, so the first
review call failed, the Router rested Gemini, and every later call fell
to the floor (a Gemini-only benchmark, 2026-09-22: two cases answered,
then nothing). The server is told at least 10 s; the Router still waits
only its own slice.
"""

import unittest

from simorgh.cognition.providers.gemini import MIN_SERVER_DEADLINE_S, _server_deadline_ms


class TheServerDeadline(unittest.TestCase):
    def test_a_short_slice_is_raised_to_the_minimum(self):
        self.assertEqual(_server_deadline_ms(8.0), int(MIN_SERVER_DEADLINE_S * 1000))

    def test_a_long_one_is_left_alone(self):
        self.assertEqual(_server_deadline_ms(45.0), 45_000)


if __name__ == "__main__":
    unittest.main()
