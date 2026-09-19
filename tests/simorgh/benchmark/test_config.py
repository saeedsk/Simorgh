"""`[benchmark]` declares only keys something reads.

`concurrency` was declared and never read (cases always ran one at a
time); it was removed 2026-09-19 rather than wired, because the system
under test has one worker and a shared budget.
"""

from __future__ import annotations

import dataclasses
import unittest

from simorgh.benchmark.config import Config


class TestNoUnreadKeys(unittest.TestCase):
    def test_concurrency_is_not_a_key(self) -> None:
        self.assertNotIn("concurrency", {f.name for f in dataclasses.fields(Config)})

    def test_a_leftover_concurrency_key_is_ignored(self) -> None:
        self.assertEqual(Config.from_mapping({"concurrency": 4, "default_cases": 3}), Config(default_cases=3))


if __name__ == "__main__":
    unittest.main()
