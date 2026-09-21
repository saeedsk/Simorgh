"""Telling the model once is not enough.

A marker is a tool call only when it starts its own line. When one
turns up mid-sentence the session refuses it, records a failed step,
and tells the model -- and that correction used to happen ONCE per
session, on the reasoning that a repeat is "an answer about a tool
and not a request for one".

That is true of the same marker twice running and wrong for a
different tool ten steps later. A trial on 2026-09-20 paid for it in
full:

    step 10  a replace_in_file marker mid-sentence was not run
    step 11  replace_in_file  simorgh/benchmark/config.py: 1 change applied
    step 13  "...let the result decide. RUN_TESTS: tests/simorgh/benchmark"
    step 14  verification fail: no run_tests call in this session at all
    step 15  verification fail: no run_tests call in this session at all
    step 16  verification fail: no run_tests call in this session at all

The first correction worked -- the model wrote a proper marker and
made a real edit. Its RUN_TESTS marker afterwards was mid-sentence
too, nothing was said because the one correction was spent, the call
silently did not happen, and the model spent its last three rounds
saying "I already issued the RUN_TESTS call and am waiting on its
result" while the verifier failed it for never running the tests.
"""

import unittest

from simorgh.orchestration.session import MARKER_CORRECTIONS


class HowManyTimes(unittest.TestCase):
    def test_more_than_once(self):
        """The whole bug: the second stray marker got no correction."""
        self.assertGreater(MARKER_CORRECTIONS, 1)

    def test_and_not_forever(self):
        """A model that cannot put a marker on its own line after
        three tries will not manage it on the fourth, and the rounds
        are the task's budget."""
        self.assertLessEqual(MARKER_CORRECTIONS, 5)

    def test_a_session_starts_with_none_spent(self):
        from simorgh.orchestration.api import Session
        from simorgh.orchestration import profiles

        session = Session(task_id="t", kind="patch", mode="execute", profile=profiles.PATCH)
        self.assertEqual(session.markers_corrected, 0)


class WhatTheSecondCorrectionSays(unittest.TestCase):
    """The model's false belief was specific -- that a call was in
    flight -- so the message has to contradict that specific thing."""

    @staticmethod
    def _message(again: bool) -> str:
        stray = "run_tests"
        return (
            f"Nothing ran: your {stray.upper()}: marker had text before it on the same "
            f"line, and a marker is only a tool call when it starts its own line. Write it "
            f"again on a line of its own if you still want it -- or, if you are finished, "
            f"give your final answer with no marker in it at all."
            + (" Nothing is pending and no result is coming back to you: a marker that did "
               "not start its own line was never a call, so there is nothing to wait for."
               if again else "")
        )

    def test_the_first_correction_explains_the_rule(self):
        first = self._message(False)
        self.assertIn("starts its own line", first)
        self.assertIn("RUN_TESTS", first)

    def test_a_later_one_says_nothing_is_pending(self):
        again = self._message(True)
        self.assertIn("nothing to wait for", again)
        self.assertIn("Nothing is pending", again)

    def test_the_wording_in_the_session_matches(self):
        """Read off the source, so the message and this test cannot
        drift apart the way two copies of a command table did."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[3] / "simorgh" / "orchestration" / "session.py").read_text()
        self.assertIn("Nothing is pending and no result is coming back to you", source)
        self.assertIn("session.markers_corrected < MARKER_CORRECTIONS", source)


if __name__ == "__main__":
    unittest.main()
