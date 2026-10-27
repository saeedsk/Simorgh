"""A task whose branch could not be put on main ends `blocked`
`landing failed: ...` with its worktree kept for the next attempt
(`orchestration/session.py::_continues` lists LANDING_REASON). Planning
must bring it back on the continuation delay like the other kept-edit
reasons, not after the five-minute blocked delay (wave A review,
2026-10-27).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from simorgh.planning.config import Config
from simorgh.planning.service import LANDING_REASON, Service


class AFailedLandingRetriesAsAContinuationTestCase(unittest.TestCase):
    def test_the_continuation_delay_applies(self):
        config = Config()
        holder = SimpleNamespace(config=config)
        self.assertEqual(Service._retry_delay(holder, "landing failed: rebase conflict in simorgh/x.py"),
                         config.continuation_delay_seconds)
        self.assertNotEqual(config.continuation_delay_seconds, config.blocked_retry_delay_seconds)

    def test_the_text_matches_orchestration(self):
        from simorgh.orchestration import session
        self.assertEqual(LANDING_REASON, session.LANDING_REASON)


if __name__ == "__main__":
    unittest.main()
