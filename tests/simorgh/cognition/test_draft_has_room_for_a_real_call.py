"""A purpose's deadline is SHARED: each candidate gets
`remaining / (still to try + 1)`. With four providers, `draft`'s 180 s
gave 36 s a call -- and live drafting calls on SWE-bench cases ran to
42.5 s (2026-09-22). The slow tail timed out and the case lost its
answer while the model was working normally.
"""

import unittest

from simorgh.cognition.config import DEFAULT_PURPOSE_BUDGETS as PURPOSE_BUDGETS


class DraftsGetRoom(unittest.TestCase):
    def test_a_slice_of_draft_outlasts_a_real_drafting_call(self):
        share = PURPOSE_BUDGETS["draft"].max_seconds / 5      # four candidates + one
        self.assertGreaterEqual(share, 45.0, "a 42.5 s drafting call must fit in one candidate's slice")

    def test_chat_is_not_slowed_to_match(self):
        self.assertLessEqual(PURPOSE_BUDGETS["chat"].max_seconds, 90.0)


if __name__ == "__main__":
    unittest.main()
