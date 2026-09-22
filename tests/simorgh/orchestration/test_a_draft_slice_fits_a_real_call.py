"""A think's deadline is the SMALLER of what the worker waits and the
purpose's own cap, and Cognition then SHARES it between candidates. At
`think_timeout_s = 200` a `draft` candidate got 40 s while real drafting
calls on SWE-bench cases ran to 42.5 s (live, 2026-09-22) -- three
providers in a row timed out on one case and it fell to the floor model.
"""

import unittest

from simorgh.cognition.config import DEFAULT_PURPOSE_BUDGETS
from simorgh.orchestration.config import Config

CANDIDATES = 4          # together_strong, together, gemini, claude_code_cli


class ADraftCandidateGetsEnoughTime(unittest.TestCase):
    def _slice(self, purpose: str) -> float:
        budget = DEFAULT_PURPOSE_BUDGETS[purpose].max_seconds
        return min(budget, Config().think_timeout_s - 0.5) / (CANDIDATES + 1)

    def test_a_drafting_candidate_outlasts_a_42_second_call(self):
        self.assertGreaterEqual(self._slice("draft"), 45.0)

    def test_the_worker_still_outwaits_the_purpose_it_calls(self):
        self.assertGreater(Config().think_timeout_s, DEFAULT_PURPOSE_BUDGETS["draft"].max_seconds,
                           "the caller must not kill a provider Cognition is still waiting on")

    def test_chat_is_unchanged_by_it(self):
        self.assertLessEqual(DEFAULT_PURPOSE_BUDGETS["chat"].max_seconds, 90.0,
                             "voice latency is bounded by chat's own cap, not by the worker's")


if __name__ == "__main__":
    unittest.main()
