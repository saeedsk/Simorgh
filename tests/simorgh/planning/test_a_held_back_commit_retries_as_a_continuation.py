"""Stage 16 (decided 2026-10-27): a last-step `git_commit` whose
`run_tests` never ran is not proposed, and the attempt ends `blocked`
`prerequisite not done: run_tests` with its edit kept in the tree
(`orchestration/session.py::_continues`). That edit is only safe to keep
because the next attempt comes back in seconds; on the five-minute
blocked delay it would sit uncommitted in the checkout meanwhile.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from simorgh.planning.config import Config
from simorgh.planning.service import Service


class AHeldBackCommitRetriesAsAContinuationTestCase(unittest.TestCase):
    def test_the_continuation_delay_applies(self):
        config = Config()
        holder = SimpleNamespace(config=config)
        self.assertEqual(Service._retry_delay(holder, "prerequisite not done: run_tests"),
                         config.continuation_delay_seconds)

    def test_a_block_on_something_outside_still_waits(self):
        config = Config()
        holder = SimpleNamespace(config=config)
        self.assertEqual(Service._retry_delay(holder, "prerequisites not done: git_commit needs run_tests"),
                         config.blocked_retry_delay_seconds)
        self.assertNotEqual(config.continuation_delay_seconds, config.blocked_retry_delay_seconds)


if __name__ == "__main__":
    unittest.main()
